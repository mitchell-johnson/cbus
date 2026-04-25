/**
 * @file native_e2e_bridge.c
 * @brief End-to-end test bridge: forwards between client TCP and C-Bus simulator TCP.
 *
 * This is the EXACT same C protocol code as the ESP32 firmware, but instead of
 * using UART for the C-Bus network, it connects to the cbus-simulator via TCP.
 *
 * Architecture:
 *   Python test client → TCP:client_port → this bridge → TCP:simulator_port → cbus-simulator
 *
 * The bridge:
 * 1. Accepts client connections on client_port
 * 2. Connects to cbus-simulator on simulator_port
 * 3. Forwards client commands to simulator
 * 4. Forwards simulator responses back to client
 * 5. Also processes commands locally (group state tracking)
 *
 * Usage: ./native_e2e_bridge <simulator_port>
 * Prints "BRIDGE_PORT:<port>" on stdout when ready.
 */
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <unistd.h>
#include <errno.h>
#include <sys/socket.h>
#include <sys/select.h>
#include <netinet/in.h>
#include <arpa/inet.h>
#include <signal.h>

#include "cbus_protocol.h"
#include "cbus_bridge.h"

#define MAX_CLIENTS 5
#define BUF_SIZE 1024

static volatile int running = 1;
static cbus_bridge_state_t bridge_state;

static void signal_handler(int sig) {
    (void)sig;
    running = 0;
}

/* Connect to the cbus-simulator backend */
static int connect_to_simulator(int sim_port) {
    int fd = socket(AF_INET, SOCK_STREAM, 0);
    if (fd < 0) return -1;

    struct sockaddr_in addr;
    memset(&addr, 0, sizeof(addr));
    addr.sin_family = AF_INET;
    addr.sin_addr.s_addr = inet_addr("127.0.0.1");
    addr.sin_port = htons(sim_port);

    if (connect(fd, (struct sockaddr*)&addr, sizeof(addr)) < 0) {
        close(fd);
        return -1;
    }
    return fd;
}

int main(int argc, char* argv[]) {
    if (argc < 2) {
        fprintf(stderr, "Usage: %s <simulator_port>\n", argv[0]);
        return 1;
    }
    int sim_port = atoi(argv[1]);

    signal(SIGINT, signal_handler);
    signal(SIGTERM, signal_handler);
    signal(SIGPIPE, SIG_IGN);
    bridge_init(&bridge_state);

    /* Connect to simulator backend */
    int sim_fd = connect_to_simulator(sim_port);
    if (sim_fd < 0) {
        fprintf(stderr, "Failed to connect to simulator on port %d\n", sim_port);
        return 1;
    }
    fprintf(stderr, "Connected to C-Bus simulator on port %d\n", sim_port);

    /* Drain simulator's initial prompt */
    {
        uint8_t drain[1024];
        fd_set rset;
        struct timeval tv = {0, 500000};
        FD_ZERO(&rset);
        FD_SET(sim_fd, &rset);
        if (select(sim_fd + 1, &rset, NULL, NULL, &tv) > 0) {
            recv(sim_fd, drain, sizeof(drain), 0);
        }
    }

    /* Create client-facing server */
    int server_fd = socket(AF_INET, SOCK_STREAM, 0);
    int opt = 1;
    setsockopt(server_fd, SOL_SOCKET, SO_REUSEADDR, &opt, sizeof(opt));

    struct sockaddr_in srv_addr;
    memset(&srv_addr, 0, sizeof(srv_addr));
    srv_addr.sin_family = AF_INET;
    srv_addr.sin_addr.s_addr = INADDR_ANY;
    srv_addr.sin_port = 0; /* auto-assign */

    bind(server_fd, (struct sockaddr*)&srv_addr, sizeof(srv_addr));
    listen(server_fd, 5);

    struct sockaddr_in bound;
    socklen_t blen = sizeof(bound);
    getsockname(server_fd, (struct sockaddr*)&bound, &blen);
    int client_port = ntohs(bound.sin_port);

    printf("BRIDGE_PORT:%d\n", client_port);
    fflush(stdout);
    fprintf(stderr, "E2E bridge listening on port %d\n", client_port);

    int client_fds[MAX_CLIENTS];
    uint8_t client_bufs[MAX_CLIENTS][BUF_SIZE];
    size_t client_buf_lens[MAX_CLIENTS];
    memset(client_fds, -1, sizeof(client_fds));
    memset(client_buf_lens, 0, sizeof(client_buf_lens));

    while (running) {
        fd_set rfds;
        FD_ZERO(&rfds);
        FD_SET(server_fd, &rfds);
        FD_SET(sim_fd, &rfds);
        int max_fd = server_fd > sim_fd ? server_fd : sim_fd;

        for (int i = 0; i < MAX_CLIENTS; i++) {
            if (client_fds[i] >= 0) {
                FD_SET(client_fds[i], &rfds);
                if (client_fds[i] > max_fd) max_fd = client_fds[i];
            }
        }

        struct timeval tv = {0, 100000};
        int ready = select(max_fd + 1, &rfds, NULL, NULL, &tv);
        if (ready < 0) { if (errno == EINTR) continue; break; }

        /* Accept new client */
        if (FD_ISSET(server_fd, &rfds)) {
            int cfd = accept(server_fd, NULL, NULL);
            if (cfd >= 0) {
                for (int i = 0; i < MAX_CLIENTS; i++) {
                    if (client_fds[i] < 0) {
                        client_fds[i] = cfd;
                        client_buf_lens[i] = 0;
                        fprintf(stderr, "Client %d connected\n", i);
                        break;
                    }
                }
            }
        }

        /* Data from simulator → forward to all clients */
        if (FD_ISSET(sim_fd, &rfds)) {
            uint8_t buf[BUF_SIZE];
            ssize_t n = recv(sim_fd, buf, sizeof(buf), 0);
            if (n <= 0) {
                fprintf(stderr, "Simulator disconnected\n");
                break;
            }
            for (int i = 0; i < MAX_CLIENTS; i++) {
                if (client_fds[i] >= 0) {
                    send(client_fds[i], buf, n, 0);
                }
            }
        }

        /* Data from clients → process locally AND forward to simulator */
        for (int i = 0; i < MAX_CLIENTS; i++) {
            if (client_fds[i] < 0 || !FD_ISSET(client_fds[i], &rfds)) continue;

            uint8_t tmp[BUF_SIZE];
            ssize_t n = recv(client_fds[i], tmp, sizeof(tmp), 0);
            if (n <= 0) {
                close(client_fds[i]);
                client_fds[i] = -1;
                client_buf_lens[i] = 0;
                fprintf(stderr, "Client %d disconnected\n", i);
                continue;
            }

            /* Append to client buffer */
            size_t space = BUF_SIZE - client_buf_lens[i];
            size_t copy = (size_t)n < space ? (size_t)n : space;
            memcpy(client_bufs[i] + client_buf_lens[i], tmp, copy);
            client_buf_lens[i] += copy;

            /* Process complete commands */
            while (1) {
                size_t end_pos = (size_t)-1;
                size_t end_len = 0;
                for (size_t j = 0; j < client_buf_lens[i]; j++) {
                    if (client_bufs[i][j] == 0x0D) {
                        end_pos = j;
                        if (j + 1 < client_buf_lens[i] && client_bufs[i][j+1] == 0x0A)
                            end_len = 2;
                        else
                            end_len = 1;
                        break;
                    }
                }
                if (end_pos == (size_t)-1) break;

                size_t cmd_len = end_pos;
                if (cmd_len > 0) {
                    /* 1. Process locally (update bridge state) */
                    uint8_t resp[512];
                    int resp_len = bridge_process_command(&bridge_state,
                        client_bufs[i], cmd_len, resp, sizeof(resp));

                    /* 2. Forward the raw command to the simulator */
                    send(sim_fd, client_bufs[i], cmd_len + end_len, 0);

                    /* 3. Send local response to client (confirmations) */
                    if (resp_len > 0) {
                        send(client_fds[i], resp, resp_len, 0);
                    }
                }

                size_t consumed = end_pos + end_len;
                memmove(client_bufs[i], client_bufs[i] + consumed,
                        client_buf_lens[i] - consumed);
                client_buf_lens[i] -= consumed;
            }
        }
    }

    for (int i = 0; i < MAX_CLIENTS; i++)
        if (client_fds[i] >= 0) close(client_fds[i]);
    close(sim_fd);
    close(server_fd);
    fprintf(stderr, "Bridge stopped\n");
    return 0;
}
