#include <stdio.h>
#include <string.h>
#include "cbus_protocol.h"
#include "cbus_bridge.h"

#define ASSERT(cond, msg) do { if (!(cond)) { printf("FAIL: %s (line %d)\n", msg, __LINE__); failures++; } else { printf("PASS: %s\n", msg); passes++; } } while(0)

int main(void) {
    int passes = 0, failures = 0;

    // Checksum
    {
        uint8_t data[] = {0x05, 0x38, 0x00, 0x79, 0x01};
        uint8_t cs = cbus_checksum(data, 5);
        uint8_t total = 0;
        for (int i = 0; i < 5; i++) total += data[i];
        total += cs;
        ASSERT((total & 0xFF) == 0, "checksum two's complement");
    }

    // Verify checksum
    {
        uint8_t data[] = {0x05, 0x38, 0x00, 0x79, 0x01, 0x00};
        data[5] = cbus_checksum(data, 5);
        ASSERT(cbus_verify_checksum(data, 6), "verify valid checksum");
    }
    {
        uint8_t data[] = {0x05, 0x38, 0x00, 0x79, 0x01, 0xFF};
        ASSERT(!cbus_verify_checksum(data, 6), "verify invalid checksum");
    }

    // Hex decode
    {
        uint8_t out[8];
        int n = cbus_hex_decode("0538007901", 10, out, sizeof(out));
        ASSERT(n == 5, "hex decode length");
        ASSERT(out[0] == 0x05, "hex decode byte 0");
        ASSERT(out[1] == 0x38, "hex decode byte 1");
        ASSERT(out[3] == 0x79, "hex decode byte 3");
    }
    {
        uint8_t out[4];
        ASSERT(cbus_hex_decode("053", 3, out, sizeof(out)) == -1, "hex decode odd length");
        ASSERT(cbus_hex_decode("ZZZZ", 4, out, sizeof(out)) == -1, "hex decode invalid chars");
    }

    // Hex encode
    {
        uint8_t data[] = {0x05, 0x38, 0x00, 0x79};
        char out[16];
        int n = cbus_hex_encode(data, 4, out, sizeof(out));
        ASSERT(n == 8, "hex encode length");
        ASSERT(strcmp(out, "05380079") == 0, "hex encode value");
    }

    // Confirmation codes
    {
        ASSERT(cbus_is_confirmation_code('h'), "conf code h");
        ASSERT(cbus_is_confirmation_code('z'), "conf code z");
        ASSERT(cbus_is_confirmation_code('g'), "conf code g");
        ASSERT(!cbus_is_confirmation_code('a'), "not conf code a");
        ASSERT(!cbus_is_confirmation_code('A'), "not conf code A");
    }

    // Ramp rates
    {
        ASSERT(cbus_ramp_rate_to_seconds(0x02) == 0, "ramp instant");
        ASSERT(cbus_ramp_rate_to_seconds(0x2A) == 30, "ramp 30s");
        ASSERT(cbus_ramp_rate_to_seconds(0x7A) == 1020, "ramp 17min");
        ASSERT(cbus_ramp_rate_to_seconds(0x00) == -1, "ramp invalid");
    }

    // Parse reset
    {
        cbus_parsed_packet_t pkt;
        ASSERT(cbus_parse_command((const uint8_t*)"~~~", 3, &pkt), "parse reset");
        ASSERT(pkt.type == CBUS_PKT_RESET, "reset type");
    }

    // Parse SCS shortcut
    {
        cbus_parsed_packet_t pkt;
        ASSERT(cbus_parse_command((const uint8_t*)"|", 1, &pkt), "parse scs");
        ASSERT(pkt.type == CBUS_PKT_SCS_SHORTCUT, "scs type");
    }

    // Parse DM command
    {
        cbus_parsed_packet_t pkt;
        ASSERT(cbus_parse_command((const uint8_t*)"A3300079", 8, &pkt), "parse DM");
        ASSERT(pkt.type == CBUS_PKT_DEVICE_MGMT, "DM type");
        ASSERT(pkt.dm_parameter == 0x30, "DM param");
        ASSERT(pkt.dm_value == 0x79, "DM value");
    }

    // Parse lighting ON
    {
        cbus_parsed_packet_t pkt;
        const char* cmd = "\\053800790Ah";
        ASSERT(cbus_parse_command((const uint8_t*)cmd, strlen(cmd), &pkt), "parse lighting ON");
        ASSERT(pkt.type == CBUS_PKT_LIGHTING_ON, "lighting ON type");
        ASSERT(pkt.application == 0x38, "lighting app");
        ASSERT(pkt.group_addr == 10, "lighting group");
        ASSERT(pkt.conf_code == 'h', "lighting conf code");
    }

    // Parse lighting OFF
    {
        cbus_parsed_packet_t pkt;
        const char* cmd = "\\053800010Ai";
        ASSERT(cbus_parse_command((const uint8_t*)cmd, strlen(cmd), &pkt), "parse lighting OFF");
        ASSERT(pkt.type == CBUS_PKT_LIGHTING_OFF, "lighting OFF type");
        ASSERT(pkt.group_addr == 10, "lighting OFF group");
    }

    // Parse lighting RAMP
    {
        cbus_parsed_packet_t pkt;
        const char* cmd = "\\0538000205" "80" "j";
        ASSERT(cbus_parse_command((const uint8_t*)cmd, strlen(cmd), &pkt), "parse lighting RAMP");
        ASSERT(pkt.type == CBUS_PKT_LIGHTING_RAMP, "lighting RAMP type");
        ASSERT(pkt.group_addr == 5, "ramp group");
        ASSERT(pkt.level == 0x80, "ramp level");
        ASSERT(pkt.ramp_rate == 0x02, "ramp rate");
    }

    // Encode confirmation
    {
        uint8_t buf[8];
        int len = cbus_encode_confirmation('h', true, buf, sizeof(buf));
        ASSERT(len == 4, "conf encode len");
        ASSERT(buf[0] == 'h', "conf code");
        ASSERT(buf[1] == '.', "conf success");
        ASSERT(buf[2] == 0x0D, "conf CR");
        ASSERT(buf[3] == 0x0A, "conf LF");
    }

    // All 20 confirmation codes
    {
        for (int i = 0; i < CBUS_CONF_CODE_COUNT; i++) {
            uint8_t buf[8];
            int len = cbus_encode_confirmation(CBUS_CONFIRMATION_CODES[i], true, buf, sizeof(buf));
            ASSERT(len == 4 && buf[1] == '.', "all conf codes");
        }
    }

    // Bridge init/reset
    {
        cbus_bridge_state_t state;
        bridge_init(&state);
        ASSERT(state.smart_mode == true, "bridge init smart mode");
        ASSERT(state.levels[0] == 0, "bridge init level 0");

        state.levels[5] = 200;
        bridge_reset(&state);
        ASSERT(state.levels[5] == 0, "bridge reset clears levels");
    }

    // Bridge process lighting ON
    {
        cbus_bridge_state_t state;
        bridge_init(&state);
        const char* cmd = "\\0538007905h";
        uint8_t resp[256];
        int len = bridge_process_command(&state, (const uint8_t*)cmd, strlen(cmd), resp, sizeof(resp));
        ASSERT(state.levels[5] == 255, "bridge ON sets level 255");
        ASSERT(len > 0, "bridge ON has response");
        ASSERT(resp[0] == 'h' && resp[1] == '.', "bridge ON confirmation");
    }

    // Bridge process lighting OFF
    {
        cbus_bridge_state_t state;
        bridge_init(&state);
        state.levels[5] = 255;
        const char* cmd = "\\0538000105i";
        uint8_t resp[256];
        bridge_process_command(&state, (const uint8_t*)cmd, strlen(cmd), resp, sizeof(resp));
        ASSERT(state.levels[5] == 0, "bridge OFF sets level 0");
    }

    // Bridge full init sequence (mimics Python pci_reset)
    {
        cbus_bridge_state_t state;
        bridge_init(&state);
        uint8_t resp[512];

        bridge_process_command(&state, (const uint8_t*)"~~~", 3, resp, sizeof(resp));
        bridge_process_command(&state, (const uint8_t*)"~~~", 3, resp, sizeof(resp));
        bridge_process_command(&state, (const uint8_t*)"~~~", 3, resp, sizeof(resp));
        bridge_process_command(&state, (const uint8_t*)"|", 1, resp, sizeof(resp));
        ASSERT(state.smart_mode, "init sequence smart mode after SCS");

        int l1 = bridge_process_command(&state, (const uint8_t*)"A32100FF", 8, resp, sizeof(resp));
        int l2 = bridge_process_command(&state, (const uint8_t*)"A32200FF", 8, resp, sizeof(resp));
        int l3 = bridge_process_command(&state, (const uint8_t*)"A342000E", 8, resp, sizeof(resp));
        int l4 = bridge_process_command(&state, (const uint8_t*)"A3300079", 8, resp, sizeof(resp));
        ASSERT(l1 > 0 && l2 > 0 && l3 > 0 && l4 > 0, "init sequence DM confirmations");
        ASSERT(state.smart_mode, "init sequence final smart mode");
        ASSERT(state.commands_processed == 8, "init sequence 8 commands");
    }

    // Bridge all 256 groups
    {
        cbus_bridge_state_t state;
        bridge_init(&state);
        uint8_t resp[256];
        int all_ok = 1;
        for (int g = 0; g < 256; g++) {
            char cmd[32];
            snprintf(cmd, sizeof(cmd), "\\053800%02X%02Xh", CBUS_LIGHT_ON, g);
            bridge_process_command(&state, (const uint8_t*)cmd, strlen(cmd), resp, sizeof(resp));
            if (state.levels[g] != 255) { all_ok = 0; break; }
        }
        ASSERT(all_ok, "all 256 groups ON");
    }

    printf("\n========================================\n");
    printf("Results: %d passed, %d failed\n", passes, failures);
    printf("========================================\n");
    return failures > 0 ? 1 : 0;
}
