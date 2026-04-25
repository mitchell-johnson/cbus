/**
 * @file test_exhaustive.c
 * @brief Exhaustive positive and negative tests for C-Bus C++ protocol code.
 * 150+ test assertions covering every function and edge case.
 */
#include <stdio.h>
#include <string.h>
#include "cbus_protocol.h"
#include "cbus_bridge.h"

static int passes = 0, failures = 0;
#define T(cond, msg) do { if (!(cond)) { printf("FAIL: %s (line %d)\n", msg, __LINE__); failures++; } else { passes++; } } while(0)

/* ============================================================
 * CHECKSUM TESTS (positive + negative)
 * ============================================================ */

void test_checksum(void) {
    /* Positive: boundary byte values */
    uint8_t boundary[] = {0, 1, 127, 128, 254, 255};
    for (int i = 0; i < 6; i++) {
        uint8_t d[] = {boundary[i]};
        uint8_t cs = cbus_checksum(d, 1);
        T(((d[0] + cs) & 0xFF) == 0, "checksum single byte");
    }

    /* Multi-byte */
    uint8_t d1[] = {0x05, 0x38, 0x00, 0x79, 0x01};
    uint8_t cs1 = cbus_checksum(d1, 5);
    uint8_t sum = 0; for (int i=0;i<5;i++) sum += d1[i]; sum += cs1;
    T((sum & 0xFF) == 0, "checksum 5 bytes");

    /* All zeros */
    uint8_t zeros[] = {0,0,0,0,0,0,0,0};
    T(cbus_checksum(zeros, 8) == 0, "checksum all zeros");

    /* All 0xFF */
    uint8_t ffs[] = {0xFF,0xFF,0xFF,0xFF};
    uint8_t csff = cbus_checksum(ffs, 4);
    sum = 0; for (int i=0;i<4;i++) sum += ffs[i]; sum += csff;
    T((sum & 0xFF) == 0, "checksum all FF");

    /* Verify valid */
    uint8_t vd[] = {0x05, 0x38, 0x00, 0x79, 0x01, 0x00};
    vd[5] = cbus_checksum(vd, 5);
    T(cbus_verify_checksum(vd, 6), "verify valid checksum");

    /* Verify invalid */
    uint8_t bad[] = {0x05, 0x38, 0x00, 0x79, 0x01, 0xFF};
    T(!cbus_verify_checksum(bad, 6), "verify invalid checksum");

    /* Verify too short */
    T(!cbus_verify_checksum(bad, 1), "verify too short");
    T(!cbus_verify_checksum(bad, 0), "verify empty");
}

/* ============================================================
 * HEX ENCODING/DECODING TESTS
 * ============================================================ */

void test_hex(void) {
    uint8_t out[32];
    char hex[64];

    /* Positive: decode valid */
    T(cbus_hex_decode("0538", 4, out, 32) == 2, "hex decode 2 bytes");
    T(out[0] == 0x05 && out[1] == 0x38, "hex decode values");

    T(cbus_hex_decode("FF00", 4, out, 32) == 2, "hex decode FF00");
    T(out[0] == 0xFF && out[1] == 0x00, "hex decode FF00 values");

    T(cbus_hex_decode("ff00", 4, out, 32) == 2, "hex decode lowercase");
    T(cbus_hex_decode("aAbBcCdDeEfF", 12, out, 32) == 6, "hex decode mixed case");

    /* Negative: odd length */
    T(cbus_hex_decode("053", 3, out, 32) == -1, "hex decode odd length");
    T(cbus_hex_decode("0", 1, out, 32) == -1, "hex decode single char");

    /* Negative: invalid chars */
    T(cbus_hex_decode("ZZZZ", 4, out, 32) == -1, "hex decode invalid Z");
    T(cbus_hex_decode("GG", 2, out, 32) == -1, "hex decode invalid G");
    T(cbus_hex_decode("  ", 2, out, 32) == -1, "hex decode spaces");

    /* Negative: buffer too small */
    T(cbus_hex_decode("0538007901", 10, out, 2) == -1, "hex decode buf too small");

    /* Positive: encode */
    uint8_t data[] = {0x05, 0x38, 0x00, 0x79};
    T(cbus_hex_encode(data, 4, hex, 64) == 8, "hex encode length");
    T(strcmp(hex, "05380079") == 0, "hex encode value");

    /* Roundtrip */
    uint8_t orig[] = {0xDE, 0xAD, 0xBE, 0xEF, 0x00, 0xFF};
    cbus_hex_encode(orig, 6, hex, 64);
    uint8_t decoded[6];
    T(cbus_hex_decode(hex, 12, decoded, 6) == 6, "hex roundtrip decode");
    T(memcmp(orig, decoded, 6) == 0, "hex roundtrip match");

    /* Negative: encode buffer too small */
    T(cbus_hex_encode(data, 4, hex, 5) == -1, "hex encode buf too small");

    /* Edge: empty */
    T(cbus_hex_decode("", 0, out, 32) == 0, "hex decode empty");
    T(cbus_hex_encode(data, 0, hex, 64) == 0, "hex encode empty");
}

/* ============================================================
 * CONFIRMATION CODE TESTS
 * ============================================================ */

void test_confirmation_codes(void) {
    /* Positive: all 20 valid codes */
    const char* codes = "hijklmnopqrstuvwxyzg";
    for (int i = 0; i < 20; i++) {
        T(cbus_is_confirmation_code((uint8_t)codes[i]), "valid conf code");
    }

    /* Negative: letters not in set */
    T(!cbus_is_confirmation_code('a'), "not conf a");
    T(!cbus_is_confirmation_code('b'), "not conf b");
    T(!cbus_is_confirmation_code('c'), "not conf c");
    T(!cbus_is_confirmation_code('d'), "not conf d");
    T(!cbus_is_confirmation_code('e'), "not conf e");
    T(!cbus_is_confirmation_code('f'), "not conf f");

    /* Negative: uppercase */
    T(!cbus_is_confirmation_code('H'), "not conf H");
    T(!cbus_is_confirmation_code('Z'), "not conf Z");
    T(!cbus_is_confirmation_code('A'), "not conf A");

    /* Negative: digits */
    T(!cbus_is_confirmation_code('0'), "not conf 0");
    T(!cbus_is_confirmation_code('9'), "not conf 9");

    /* Negative: special chars */
    T(!cbus_is_confirmation_code(0), "not conf null");
    T(!cbus_is_confirmation_code(0xFF), "not conf 0xFF");
    T(!cbus_is_confirmation_code(' '), "not conf space");
    T(!cbus_is_confirmation_code('.'), "not conf dot");
    T(!cbus_is_confirmation_code('#'), "not conf hash");
}

/* ============================================================
 * RAMP RATE TESTS
 * ============================================================ */

void test_ramp_rates(void) {
    /* Positive: all 16 valid rates */
    uint8_t rates[] = {0x02,0x0A,0x12,0x1A,0x22,0x2A,0x32,0x3A,
                       0x42,0x4A,0x52,0x5A,0x62,0x6A,0x72,0x7A};
    int secs[] = {0,4,8,12,20,30,40,60,90,120,180,300,420,600,900,1020};
    for (int i = 0; i < 16; i++) {
        T(cbus_is_ramp_rate(rates[i]), "valid ramp rate");
        T(cbus_ramp_rate_to_seconds(rates[i]) == secs[i], "ramp rate seconds");
    }

    /* Negative: invalid rates */
    T(!cbus_is_ramp_rate(0x00), "invalid ramp 0x00");
    T(!cbus_is_ramp_rate(0x01), "invalid ramp 0x01 (OFF cmd)");
    T(!cbus_is_ramp_rate(0x03), "invalid ramp 0x03");
    T(!cbus_is_ramp_rate(0x79), "invalid ramp 0x79 (ON cmd)");
    T(!cbus_is_ramp_rate(0x80), "invalid ramp 0x80");
    T(!cbus_is_ramp_rate(0xFF), "invalid ramp 0xFF");
    T(cbus_ramp_rate_to_seconds(0x00) == -1, "invalid ramp secs 0x00");
    T(cbus_ramp_rate_to_seconds(0xFF) == -1, "invalid ramp secs 0xFF");
}

/* ============================================================
 * COMMAND PARSING POSITIVE TESTS
 * ============================================================ */

static cbus_parsed_packet_t g_pkt;

void test_parse_positive(void) {
    cbus_parsed_packet_t *pkt = &g_pkt;

    /* Reset */
    T(cbus_parse_command((const uint8_t*)"~~~", 3, pkt), "parse ~~~");
    T(pkt->type == CBUS_PKT_RESET, "~~~ is reset");

    T(cbus_parse_command((const uint8_t*)"~", 1, pkt), "parse ~");
    T(pkt->type == CBUS_PKT_RESET, "~ is reset");

    /* SCS */
    T(cbus_parse_command((const uint8_t*)"|", 1, pkt), "parse |");
    T(pkt->type == CBUS_PKT_SCS_SHORTCUT, "| is SCS");

    /* DM commands */
    T(cbus_parse_command((const uint8_t*)"A32100FF", 8, pkt), "parse DM 21");
    T(pkt->dm_parameter == 0x21 && pkt->dm_value == 0xFF, "DM 21 FF values");

    T(cbus_parse_command((const uint8_t*)"A32200FF", 8, pkt), "parse DM 22");
    T(pkt->dm_parameter == 0x22, "DM 22 param");

    T(cbus_parse_command((const uint8_t*)"A342000E", 8, pkt), "parse DM 42");
    T(pkt->dm_parameter == 0x42 && pkt->dm_value == 0x0E, "DM 42 0E values");

    T(cbus_parse_command((const uint8_t*)"A3300079", 8, pkt), "parse DM 30");
    T(pkt->dm_parameter == 0x30 && pkt->dm_value == 0x79, "DM 30 79 values");

    /* Lighting ON with all 20 conf codes */
    const char* codes = "hijklmnopqrstuvwxyzg";
    for (int i = 0; i < 20; i++) {
        char cmd[32];
        snprintf(cmd, sizeof(cmd), "\\0538007901%c", codes[i]);
        T(cbus_parse_command((const uint8_t*)cmd, strlen(cmd), pkt), "parse ON with conf");
        T(pkt->type == CBUS_PKT_LIGHTING_ON, "ON type");
        T(pkt->conf_code == (uint8_t)codes[i], "ON conf code");
        T(pkt->group_addr == 1, "ON group 1");
    }

    /* Lighting ON for boundary groups */
    {
        uint8_t test_groups[] = {0, 1, 2, 50, 100, 127, 128, 200, 254, 255};
        for (int i = 0; i < 10; i++) {
            char cmd[32];
            snprintf(cmd, sizeof(cmd), "\\053800%02X%02Xh", 0x79, test_groups[i]);
            T(cbus_parse_command((const uint8_t*)cmd, strlen(cmd), pkt), "parse ON group");
            T(pkt->group_addr == test_groups[i], "ON group addr");
        }
    }

    /* Lighting OFF */
    T(cbus_parse_command((const uint8_t*)"\\053800010Ai", 12, pkt), "parse OFF");
    T(pkt->type == CBUS_PKT_LIGHTING_OFF, "OFF type");
    T(pkt->group_addr == 10, "OFF group");
    T(pkt->level == 0, "OFF level 0");

    /* Lighting RAMP: all 16 rates */
    uint8_t ramps[] = {0x02,0x0A,0x12,0x1A,0x22,0x2A,0x32,0x3A,
                       0x42,0x4A,0x52,0x5A,0x62,0x6A,0x72,0x7A};
    for (int i = 0; i < 16; i++) {
        char cmd[32];
        snprintf(cmd, sizeof(cmd), "\\053800%02X0580h", ramps[i]);
        T(cbus_parse_command((const uint8_t*)cmd, strlen(cmd), pkt), "parse RAMP");
        T(pkt->type == CBUS_PKT_LIGHTING_RAMP, "RAMP type");
        T(pkt->ramp_rate == ramps[i], "RAMP rate");
        T(pkt->level == 0x80, "RAMP level");
    }

    /* Lighting TERMINATE */
    T(cbus_parse_command((const uint8_t*)"\\053800090Ah", 12, pkt), "parse TERMINATE");
    T(pkt->type == CBUS_PKT_LIGHTING_TERMINATE, "TERMINATE type");

    /* No confirmation code */
    T(cbus_parse_command((const uint8_t*)"\\053800790A", 11, pkt), "parse no conf");
    T(pkt->conf_code == 0, "no conf code");

    /* Clock */
    T(cbus_parse_command((const uint8_t*)"\\05DF000801h", 12, pkt), "parse clock");
    T(pkt->type == CBUS_PKT_CLOCK_UPDATE, "clock type");
    T(pkt->application == CBUS_APP_CLOCK, "clock app");
}

/* ============================================================
 * COMMAND PARSING NEGATIVE TESTS
 * ============================================================ */

void test_parse_negative(void) {
    cbus_parsed_packet_t *pkt = &g_pkt;

    /* Empty */
    T(!cbus_parse_command((const uint8_t*)"", 0, pkt), "reject empty");

    /* Invalid hex after escape */
    T(!cbus_parse_command((const uint8_t*)"\\ZZZZ", 5, pkt), "reject invalid hex");
    T(!cbus_parse_command((const uint8_t*)"\\GG", 3, pkt), "reject GG");

    /* Too short escape */
    T(!cbus_parse_command((const uint8_t*)"\\", 1, pkt), "reject lone backslash");
    T(!cbus_parse_command((const uint8_t*)"\\0", 2, pkt), "reject too short");

    /* DM too short */
    T(!cbus_parse_command((const uint8_t*)"A3", 2, pkt), "reject DM too short 2");
    T(!cbus_parse_command((const uint8_t*)"A330", 4, pkt), "reject DM too short 4");
    T(!cbus_parse_command((const uint8_t*)"A33000", 6, pkt), "reject DM too short 6");

    /* Random garbage */
    T(!cbus_parse_command((const uint8_t*)"hello", 5, pkt), "reject hello");
    T(!cbus_parse_command((const uint8_t*)"12345", 5, pkt), "reject digits");
    T(!cbus_parse_command((const uint8_t*)"\xFF\xFE", 2, pkt), "reject binary garbage");

    /* Almost valid but not */
    T(!cbus_parse_command((const uint8_t*)"A4300079", 8, pkt), "reject A4 not A3");
    T(!cbus_parse_command((const uint8_t*)"B3300079", 8, pkt), "reject B3 not A3");
}

/* ============================================================
 * RESPONSE ENCODING TESTS
 * ============================================================ */

void test_encode(void) {
    uint8_t buf[256];

    /* Confirmation success for all 20 codes */
    for (int i = 0; i < 20; i++) {
        uint8_t code = CBUS_CONFIRMATION_CODES[i];
        int len = cbus_encode_confirmation(code, true, buf, 256);
        T(len == 4, "conf encode len");
        T(buf[0] == code, "conf encode code");
        T(buf[1] == '.', "conf encode success");
        T(buf[2] == 0x0D && buf[3] == 0x0A, "conf encode CRLF");
    }

    /* Confirmation failure */
    int len = cbus_encode_confirmation('h', false, buf, 256);
    T(len == 4 && buf[1] == '#', "conf encode failure");

    /* Error */
    len = cbus_encode_error(buf, 256);
    T(len == 3 && buf[0] == '!', "error encode");

    /* Powerup */
    len = cbus_encode_powerup(buf, 256);
    T(len == 4 && buf[0] == '+' && buf[1] == '+', "powerup encode");

    /* Buffer too small */
    T(cbus_encode_confirmation('h', true, buf, 2) == -1, "conf buf too small");
    T(cbus_encode_error(buf, 1) == -1, "error buf too small");
    T(cbus_encode_powerup(buf, 2) == -1, "powerup buf too small");

    /* Level status */
    uint8_t levels[32];
    memset(levels, 0, 32);
    levels[0] = 255; levels[15] = 128; levels[31] = 64;
    len = cbus_encode_level_status(0x38, 0, levels, buf, 256);
    T(len > 0, "level status encode");
    T(buf[len-2] == 0x0D && buf[len-1] == 0x0A, "level status CRLF");
}

/* ============================================================
 * BRIDGE STATE TESTS
 * ============================================================ */

static cbus_bridge_state_t g_state;
static uint8_t g_resp[512];

void test_bridge(void) {
    int len;

    /* Init */
    bridge_init(&g_state);
    T(g_state.smart_mode == true, "init smart mode");
    T(g_state.source_address == 0xFF, "init source addr");
    int all_zero = 1;
    for (int i = 0; i < 256; i++) { if (g_state.levels[i] != 0) all_zero = 0; }
    T(all_zero, "init all levels zero");

    /* Reset */
    g_state.levels[50] = 200;
    bridge_reset(&g_state);
    T(g_state.levels[50] == 0, "reset clears levels");
    T(g_state.smart_mode == false, "reset clears smart mode");

    /* Set/get boundary groups */
    bridge_init(&g_state);
    {
        uint8_t tg[] = {0,1,50,127,128,254,255};
        for (int i = 0; i < 7; i++) {
            bridge_set_group_level(&g_state, tg[i], tg[i]);
            T(bridge_get_group_level(&g_state, tg[i]) == tg[i], "set/get group");
        }
    }

    /* Process reset */
    bridge_init(&g_state);
    g_state.levels[10] = 100;
    len = bridge_process_command(&g_state, (const uint8_t*)"~~~", 3, g_resp, 512);
    T(len == 0, "reset no response");
    T(g_state.levels[10] == 0, "reset clears via process");

    /* Process SCS */
    bridge_init(&g_state);
    g_state.smart_mode = false;
    bridge_process_command(&g_state, (const uint8_t*)"|", 1, g_resp, 512);
    T(g_state.smart_mode == true, "SCS enables smart mode");

    /* Process ON for boundary groups */
    bridge_init(&g_state);
    {
        uint8_t tg[] = {0,1,50,100,127,128,200,254,255};
        for (int i = 0; i < 9; i++) {
            char cmd[32];
            snprintf(cmd, sizeof(cmd), "\\053800%02X%02Xh", 0x79, tg[i]);
            bridge_process_command(&g_state, (const uint8_t*)cmd, strlen(cmd), g_resp, 512);
            T(g_state.levels[tg[i]] == 255, "process ON group");
        }
    }

    /* Process OFF for boundary groups */
    {
        uint8_t tg[] = {0,1,50,100,127,128,200,254,255};
        for (int i = 0; i < 9; i++) {
            char cmd[32];
            snprintf(cmd, sizeof(cmd), "\\053800%02X%02Xh", 0x01, tg[i]);
            bridge_process_command(&g_state, (const uint8_t*)cmd, strlen(cmd), g_resp, 512);
            T(g_state.levels[tg[i]] == 0, "process OFF group");
        }
    }

    /* Process RAMP to specific levels */
    bridge_init(&g_state);
    {
        uint8_t test_levels[] = {0, 1, 64, 127, 128, 191, 254, 255};
        for (int i = 0; i < 8; i++) {
            char cmd[32];
            snprintf(cmd, sizeof(cmd), "\\053800%02X01%02Xh", 0x02, test_levels[i]);
            bridge_process_command(&g_state, (const uint8_t*)cmd, strlen(cmd), g_resp, 512);
            T(g_state.levels[1] == test_levels[i], "process RAMP level");
        }
    }

    /* Process DM and verify confirmation */
    bridge_init(&g_state);
    len = bridge_process_command(&g_state, (const uint8_t*)"A3300079", 8, g_resp, 512);
    T(len > 0, "DM has response");
    T(g_resp[1] == '.', "DM confirmation success");
    T(g_state.smart_mode == true, "DM sets smart mode");

    /* Full init sequence */
    bridge_init(&g_state);
    bridge_process_command(&g_state, (const uint8_t*)"~~~", 3, g_resp, 512);
    bridge_process_command(&g_state, (const uint8_t*)"~~~", 3, g_resp, 512);
    bridge_process_command(&g_state, (const uint8_t*)"~~~", 3, g_resp, 512);
    bridge_process_command(&g_state, (const uint8_t*)"|", 1, g_resp, 512);
    T(g_state.smart_mode, "init SCS smart");
    bridge_process_command(&g_state, (const uint8_t*)"A32100FF", 8, g_resp, 512);
    bridge_process_command(&g_state, (const uint8_t*)"A32200FF", 8, g_resp, 512);
    bridge_process_command(&g_state, (const uint8_t*)"A342000E", 8, g_resp, 512);
    bridge_process_command(&g_state, (const uint8_t*)"A3300079", 8, g_resp, 512);
    T(g_state.commands_processed == 8, "init 8 commands");

    /* Negative: empty command */
    bridge_init(&g_state);
    len = bridge_process_command(&g_state, (const uint8_t*)"", 0, g_resp, 512);
    T(len == 0, "empty command no response");

    /* Negative: garbage */
    len = bridge_process_command(&g_state, (const uint8_t*)"garbage", 7, g_resp, 512);
    T(len == 0, "garbage no response");

    /* Negative: resp buffer too small */
    len = bridge_process_command(&g_state, (const uint8_t*)"A3300079", 8, g_resp, 2);
    T(len == 0, "small resp buf");

    /* Confirm code in ON response matches request */
    bridge_init(&g_state);
    {
        const char* codes = "hijklmnopqrstuvwxyzg";
        for (int i = 0; i < 20; i++) {
            char cmd[32];
            snprintf(cmd, sizeof(cmd), "\\0538007901%c", codes[i]);
            len = bridge_process_command(&g_state, (const uint8_t*)cmd, strlen(cmd), g_resp, 512);
            T(len >= 4, "ON response length");
            T(g_resp[0] == (uint8_t)codes[i], "ON response conf code matches");
            T(g_resp[1] == '.', "ON response success");
        }
    }

    /* Statistics */
    bridge_init(&g_state);
    bridge_process_command(&g_state, (const uint8_t*)"\\0538007901h", 12, g_resp, 512);
    T(g_state.commands_received == 1, "stats received");
    T(g_state.commands_processed == 1, "stats processed");
    bridge_process_command(&g_state, (const uint8_t*)"garbage", 7, g_resp, 512);
    T(g_state.commands_received == 2, "stats received 2");
    T(g_state.errors == 1, "stats errors");
}

int main(void) {
    setvbuf(stdout, NULL, _IONBF, 0);
    test_checksum();
    test_hex();
    test_confirmation_codes();
    test_ramp_rates();
    test_parse_positive();
    test_parse_negative();
    test_encode();
    test_bridge();

    printf("\n========================================\n");
    printf("C++ Results: %d passed, %d failed\n", passes, failures);
    printf("========================================\n");
    return failures > 0 ? 1 : 0;
}
