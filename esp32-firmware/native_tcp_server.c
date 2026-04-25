/**
 * @file native_tcp_server.c
 * @brief Native TCP test server using the same C-Bus protocol code as the ESP32.
 *
 * This compiles the EXACT same cbus_protocol.c and cbus_bridge.c code
 * that runs on the ESP32 into a native TCP server. The Python test suite
 * connects to this server to verify protocol correctness end-to-end.
 *
 * Usage: ./native_tcp_server [port]
 * Default port: 10001
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

#define MAX_CLIENTS 10
#define RECV_BUF_SIZE 1024

static volatile int running = 1;
static cbus_bridge_state_t bridge_state;

static void signal_handler(int sig) {
    (void)sig;
    running = 0;
}

static void process_client_data(int client_fd, uint8_t* buf, size_t* buf_len) {
    // Find CR or CR+LF in buffer
    while (1) {
        size_t end_pos = (size_t)-1;
        size_t end_len = 0;

        for (size_t i = 0; i < *buf_len; i++) {
            if (buf[i] == CBUS_CR) {
                end_pos = i;
                if (i + 1 < *buf_len && buf[i + 1] == CBUS_LF) {
                    end_len = 2;
                } else {
                    end_len = 1;
                }
                break;
            }
        }

        if (end_pos == (size_t)-1) break;

        // Extract command (without terminator)
        size_t cmd_len = end_pos;

        if (cmd_len > 0) {
            uint8_t resp[512];
            int resp_len = bridge_process_command(&bridge_state,
                                                   buf, cmd_len,
                                                   resp, sizeof(resp));
            if (resp_len > 0) {
                send(client_fd, resp, resp_len, 0);
            }
        }

        // Remove processed command from buffer
        size_t consumed = end_pos + end_len;
        memmove(buf, buf + consumed, *buf_len - consumed);
        *buf_len -= consumed;
    }
}

int main(int argc, char* argv[]) {
    int port = (argc > 1) ? atoi(argv[1]) : 0;  // 0 = auto-assign

    signal(SIGINT, signal_handler);
    signal(SIGTERM, signal_handler);
    signal(SIGPIPE, SIG_IGN);

    bridge_init(&bridge_state);

    // Create server socket
    int server_fd = socket(AF_INET, SOCK_STREAM, 0);
    if (server_fd < 0) {
        perror("socket");
        return 1;
    }

    int opt = 1;
    setsockopt(server_fd, SOL_SOCKET, SO_REUSEADDR, &opt, sizeof(opt));

    struct sockaddr_in addr;
    memset(&addr, 0, sizeof(addr));
    addr.sin_family = AF_INET;
    addr.sin_addr.s_addr = INADDR_ANY;
    addr.sin_port = htons(port);

    if (bind(server_fd, (struct sockaddr*)&addr, sizeof(addr)) < 0) {
        perror("bind");
        close(server_fd);
        return 1;
    }

    if (listen(server_fd, 5) < 0) {
        perror("listen");
        close(server_fd);
        return 1;
    }

    // Get actual port
    struct sockaddr_in bound_addr;
    socklen_t bound_len = sizeof(bound_addr);
    getsockname(server_fd, (struct sockaddr*)&bound_addr, &bound_len);
    int actual_port = ntohs(bound_addr.sin_port);

    // Print port on stdout (Python test reads this)
    printf("PORT:%d\n", actual_port);
    fflush(stdout);

    fprintf(stderr, "C-Bus native TCP server started on port %d\n", actual_port);

    int client_fds[MAX_CLIENTS];
    uint8_t client_bufs[MAX_CLIENTS][RECV_BUF_SIZE];
    size_t client_buf_lens[MAX_CLIENTS];
    memset(client_fds, -1, sizeof(client_fds));
    memset(client_buf_lens, 0, sizeof(client_buf_lens));

    while (running) {
        fd_set read_fds;
        FD_ZERO(&read_fds);
        FD_SET(server_fd, &read_fds);
        int max_fd = server_fd;

        for (int i = 0; i < MAX_CLIENTS; i++) {
            if (client_fds[i] >= 0) {
                FD_SET(client_fds[i], &read_fds);
                if (client_fds[i] > max_fd) max_fd = client_fds[i];
            }
        }

        struct timeval tv = {0, 100000};  // 100ms timeout
        int ready = select(max_fd + 1, &read_fds, NULL, NULL, &tv);
        if (ready < 0) {
            if (errno == EINTR) continue;
            break;
        }

        // Accept new connections
        if (FD_ISSET(server_fd, &read_fds)) {
            struct sockaddr_in client_addr;
            socklen_t client_len = sizeof(client_addr);
            int client_fd = accept(server_fd, (struct sockaddr*)&client_addr, &client_len);
            if (client_fd >= 0) {
                int placed = 0;
                for (int i = 0; i < MAX_CLIENTS; i++) {
                    if (client_fds[i] < 0) {
                        client_fds[i] = client_fd;
                        client_buf_lens[i] = 0;
                        placed = 1;
                        fprintf(stderr, "Client %d connected\n", i);
                        break;
                    }
                }
                if (!placed) {
                    close(client_fd);
                    fprintf(stderr, "Max clients reached, rejected connection\n");
                }
            }
        }

        // Handle client data
        for (int i = 0; i < MAX_CLIENTS; i++) {
            if (client_fds[i] >= 0 && FD_ISSET(client_fds[i], &read_fds)) {
                uint8_t tmp[512];
                ssize_t n = recv(client_fds[i], tmp, sizeof(tmp), 0);
                if (n <= 0) {
                    // Client disconnected
                    close(client_fds[i]);
                    client_fds[i] = -1;
                    client_buf_lens[i] = 0;
                    fprintf(stderr, "Client %d disconnected\n", i);
                } else {
                    // Append to buffer
                    size_t space = RECV_BUF_SIZE - client_buf_lens[i];
                    size_t copy = (size_t)n < space ? (size_t)n : space;
                    memcpy(client_bufs[i] + client_buf_lens[i], tmp, copy);
                    client_buf_lens[i] += copy;

                    // Process commands
                    process_client_data(client_fds[i], client_bufs[i], &client_buf_lens[i]);
                }
            }
        }
    }

    // Cleanup
    for (int i = 0; i < MAX_CLIENTS; i++) {
        if (client_fds[i] >= 0) close(client_fds[i]);
    }
    close(server_fd);
    fprintf(stderr, "Server stopped\n");
    return 0;
}
