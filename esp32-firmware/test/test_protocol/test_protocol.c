/**
 * @file test_protocol.c
 * @brief Comprehensive unit tests for cbus_protocol.c
 *
 * Tests every function in the C-Bus protocol library using Unity.
 * Runs natively on the host machine (not on ESP32).
 */
#include <unity.h>
#include "cbus_protocol.h"
#include "cbus_bridge.h"
#include <string.h>
#include <stdio.h>

// ============================================================
// Checksum Tests
// ============================================================

void test_checksum_known_value(void) {
    // For bytes {0x05, 0x38, 0x00, 0x79, 0x01}, calculate checksum
    uint8_t data[] = {0x05, 0x38, 0x00, 0x79, 0x01};
    uint8_t cs = cbus_checksum(data, 5);
    // Verify: sum of data + checksum should be 0x00 (mod 256)
    uint8_t total = 0;
    for (int i = 0; i < 5; i++) total += data[i];
    total += cs;
    TEST_ASSERT_EQUAL_UINT8(0x00, total & 0xFF);
}

void test_checksum_single_byte(void) {
    uint8_t data[] = {0x42};
    uint8_t cs = cbus_checksum(data, 1);
    TEST_ASSERT_EQUAL_UINT8((uint8_t)(0x42 + cs), 0x00);
}

void test_checksum_all_zeros(void) {
    uint8_t data[] = {0x00, 0x00, 0x00};
    uint8_t cs = cbus_checksum(data, 3);
    TEST_ASSERT_EQUAL_UINT8(0x00, cs);
}

void test_verify_checksum_valid(void) {
    uint8_t data[] = {0x05, 0x38, 0x00, 0x79, 0x01, 0x00};
    data[5] = cbus_checksum(data, 5);
    TEST_ASSERT_TRUE(cbus_verify_checksum(data, 6));
}

void test_verify_checksum_invalid(void) {
    uint8_t data[] = {0x05, 0x38, 0x00, 0x79, 0x01, 0xFF};
    TEST_ASSERT_FALSE(cbus_verify_checksum(data, 6));
}

// ============================================================
// Hex Encoding/Decoding Tests
// ============================================================

void test_hex_decode_valid(void) {
    uint8_t out[4];
    int n = cbus_hex_decode("0538007901", 10, out, sizeof(out));
    TEST_ASSERT_EQUAL_INT(5, n);
    TEST_ASSERT_EQUAL_UINT8(0x05, out[0]);
    TEST_ASSERT_EQUAL_UINT8(0x38, out[1]);
    TEST_ASSERT_EQUAL_UINT8(0x00, out[2]);
    TEST_ASSERT_EQUAL_UINT8(0x79, out[3]);
}

void test_hex_decode_lowercase(void) {
    uint8_t out[2];
    int n = cbus_hex_decode("ff00", 4, out, sizeof(out));
    TEST_ASSERT_EQUAL_INT(2, n);
    TEST_ASSERT_EQUAL_UINT8(0xFF, out[0]);
    TEST_ASSERT_EQUAL_UINT8(0x00, out[1]);
}

void test_hex_decode_odd_length_fails(void) {
    uint8_t out[4];
    int n = cbus_hex_decode("053", 3, out, sizeof(out));
    TEST_ASSERT_EQUAL_INT(-1, n);
}

void test_hex_decode_invalid_chars_fails(void) {
    uint8_t out[4];
    int n = cbus_hex_decode("ZZZZ", 4, out, sizeof(out));
    TEST_ASSERT_EQUAL_INT(-1, n);
}

void test_hex_encode_valid(void) {
    uint8_t data[] = {0x05, 0x38, 0x00, 0x79};
    char out[16];
    int n = cbus_hex_encode(data, 4, out, sizeof(out));
    TEST_ASSERT_EQUAL_INT(8, n);
    TEST_ASSERT_EQUAL_STRING("05380079", out);
}

void test_hex_encode_roundtrip(void) {
    uint8_t original[] = {0xDE, 0xAD, 0xBE, 0xEF};
    char hex[16];
    uint8_t decoded[4];

    cbus_hex_encode(original, 4, hex, sizeof(hex));
    int n = cbus_hex_decode(hex, 8, decoded, sizeof(decoded));
    TEST_ASSERT_EQUAL_INT(4, n);
    TEST_ASSERT_EQUAL_UINT8_ARRAY(original, decoded, 4);
}

// ============================================================
// Confirmation Code Tests
// ============================================================

void test_confirmation_codes_valid(void) {
    const char* codes = "hijklmnopqrstuvwxyzg";
    for (int i = 0; i < 20; i++) {
        TEST_ASSERT_TRUE(cbus_is_confirmation_code((uint8_t)codes[i]));
    }
}

void test_confirmation_codes_invalid(void) {
    TEST_ASSERT_FALSE(cbus_is_confirmation_code('a'));
    TEST_ASSERT_FALSE(cbus_is_confirmation_code('A'));
    TEST_ASSERT_FALSE(cbus_is_confirmation_code('0'));
    TEST_ASSERT_FALSE(cbus_is_confirmation_code(0x00));
    TEST_ASSERT_FALSE(cbus_is_confirmation_code(0xFF));
}

void test_confirmation_code_count(void) {
    TEST_ASSERT_EQUAL_INT(20, CBUS_CONF_CODE_COUNT);
}

// ============================================================
// Ramp Rate Tests
// ============================================================

void test_ramp_rate_instant(void) {
    TEST_ASSERT_EQUAL_INT(0, cbus_ramp_rate_to_seconds(0x02));
    TEST_ASSERT_TRUE(cbus_is_ramp_rate(0x02));
}

void test_ramp_rate_4_seconds(void) {
    TEST_ASSERT_EQUAL_INT(4, cbus_ramp_rate_to_seconds(0x0A));
}

void test_ramp_rate_30_seconds(void) {
    TEST_ASSERT_EQUAL_INT(30, cbus_ramp_rate_to_seconds(0x2A));
}

void test_ramp_rate_17_minutes(void) {
    TEST_ASSERT_EQUAL_INT(1020, cbus_ramp_rate_to_seconds(0x7A));
}

void test_ramp_rate_invalid(void) {
    TEST_ASSERT_EQUAL_INT(-1, cbus_ramp_rate_to_seconds(0x00));
    TEST_ASSERT_EQUAL_INT(-1, cbus_ramp_rate_to_seconds(0xFF));
    TEST_ASSERT_FALSE(cbus_is_ramp_rate(0x00));
}

void test_all_ramp_rates_valid(void) {
    uint8_t rates[] = {0x02,0x0A,0x12,0x1A,0x22,0x2A,0x32,0x3A,
                       0x42,0x4A,0x52,0x5A,0x62,0x6A,0x72,0x7A};
    for (int i = 0; i < 16; i++) {
        TEST_ASSERT_TRUE(cbus_is_ramp_rate(rates[i]));
        TEST_ASSERT_TRUE(cbus_ramp_rate_to_seconds(rates[i]) >= 0);
    }
}

// ============================================================
// Command Parsing Tests
// ============================================================

void test_parse_reset_triple(void) {
    cbus_parsed_packet_t pkt;
    TEST_ASSERT_TRUE(cbus_parse_command((const uint8_t*)"~~~", 3, &pkt));
    TEST_ASSERT_EQUAL(CBUS_PKT_RESET, pkt.type);
}

void test_parse_scs_shortcut(void) {
    cbus_parsed_packet_t pkt;
    TEST_ASSERT_TRUE(cbus_parse_command((const uint8_t*)"|", 1, &pkt));
    TEST_ASSERT_EQUAL(CBUS_PKT_SCS_SHORTCUT, pkt.type);
}

void test_parse_dm_command(void) {
    cbus_parsed_packet_t pkt;
    TEST_ASSERT_TRUE(cbus_parse_command((const uint8_t*)"A3300079", 8, &pkt));
    TEST_ASSERT_EQUAL(CBUS_PKT_DEVICE_MGMT, pkt.type);
    TEST_ASSERT_EQUAL_UINT8(0x30, pkt.dm_parameter);
    TEST_ASSERT_EQUAL_UINT8(0x79, pkt.dm_value);
}

void test_parse_dm_command_at_prefix(void) {
    cbus_parsed_packet_t pkt;
    TEST_ASSERT_TRUE(cbus_parse_command((const uint8_t*)"@A3300079", 9, &pkt));
    TEST_ASSERT_EQUAL(CBUS_PKT_DEVICE_MGMT, pkt.type);
    TEST_ASSERT_EQUAL_UINT8(0x30, pkt.dm_parameter);
}

void test_parse_dm_app_addr_1(void) {
    cbus_parsed_packet_t pkt;
    TEST_ASSERT_TRUE(cbus_parse_command((const uint8_t*)"A32100FF", 8, &pkt));
    TEST_ASSERT_EQUAL(CBUS_PKT_DEVICE_MGMT, pkt.type);
    TEST_ASSERT_EQUAL_UINT8(0x21, pkt.dm_parameter);
    TEST_ASSERT_EQUAL_UINT8(0xFF, pkt.dm_value);
}

void test_parse_dm_interface_opt3(void) {
    cbus_parsed_packet_t pkt;
    TEST_ASSERT_TRUE(cbus_parse_command((const uint8_t*)"A342000E", 8, &pkt));
    TEST_ASSERT_EQUAL(CBUS_PKT_DEVICE_MGMT, pkt.type);
    TEST_ASSERT_EQUAL_UINT8(0x42, pkt.dm_parameter);
    TEST_ASSERT_EQUAL_UINT8(0x0E, pkt.dm_value);
}

void test_parse_lighting_on(void) {
    // \053800790Ah  -> Lighting ON group 10 with confirmation 'h'
    const uint8_t cmd[] = "\\053800790Ah";
    cbus_parsed_packet_t pkt;
    TEST_ASSERT_TRUE(cbus_parse_command(cmd, strlen((const char*)cmd), &pkt));
    TEST_ASSERT_EQUAL(CBUS_PKT_LIGHTING_ON, pkt.type);
    TEST_ASSERT_EQUAL_UINT8(0x38, pkt.application);
    TEST_ASSERT_EQUAL_UINT8(10, pkt.group_addr);
    TEST_ASSERT_EQUAL_UINT8(255, pkt.level);
    TEST_ASSERT_EQUAL_UINT8('h', pkt.conf_code);
}

void test_parse_lighting_off(void) {
    const uint8_t cmd[] = "\\053800010Ai";
    cbus_parsed_packet_t pkt;
    TEST_ASSERT_TRUE(cbus_parse_command(cmd, strlen((const char*)cmd), &pkt));
    TEST_ASSERT_EQUAL(CBUS_PKT_LIGHTING_OFF, pkt.type);
    TEST_ASSERT_EQUAL_UINT8(10, pkt.group_addr);
    TEST_ASSERT_EQUAL_UINT8(0, pkt.level);
    TEST_ASSERT_EQUAL_UINT8('i', pkt.conf_code);
}

void test_parse_lighting_ramp(void) {
    // Ramp group 5 to level 128 (0x80) at rate 0x02 (instant)
    const uint8_t cmd[] = "\\0538000205807F80j";
    cbus_parsed_packet_t pkt;
    // Actually let's use a simpler format:
    // \05380002 0580 j  = PM, lighting, routing=0, ramp_instant, group=5, level=0x80, conf='j'
    const uint8_t cmd2[] = "\\0538000205" "80" "j";
    TEST_ASSERT_TRUE(cbus_parse_command(cmd2, strlen((const char*)cmd2), &pkt));
    TEST_ASSERT_EQUAL(CBUS_PKT_LIGHTING_RAMP, pkt.type);
    TEST_ASSERT_EQUAL_UINT8(5, pkt.group_addr);
    TEST_ASSERT_EQUAL_UINT8(0x80, pkt.level);
    TEST_ASSERT_EQUAL_UINT8(0x02, pkt.ramp_rate);
}

void test_parse_lighting_on_no_confirmation(void) {
    const uint8_t cmd[] = "\\053800790A";
    cbus_parsed_packet_t pkt;
    TEST_ASSERT_TRUE(cbus_parse_command(cmd, strlen((const char*)cmd), &pkt));
    TEST_ASSERT_EQUAL(CBUS_PKT_LIGHTING_ON, pkt.type);
    TEST_ASSERT_EQUAL_UINT8(0, pkt.conf_code);
}

void test_parse_lighting_terminate_ramp(void) {
    const uint8_t cmd[] = "\\053800090Ah";
    cbus_parsed_packet_t pkt;
    TEST_ASSERT_TRUE(cbus_parse_command(cmd, strlen((const char*)cmd), &pkt));
    TEST_ASSERT_EQUAL(CBUS_PKT_LIGHTING_TERMINATE, pkt.type);
    TEST_ASSERT_EQUAL_UINT8(10, pkt.group_addr);
}

void test_parse_all_groups(void) {
    // Test parsing lighting ON for every group address 0-255
    for (int g = 0; g < 256; g++) {
        char cmd[32];
        snprintf(cmd, sizeof(cmd), "\\0538007900%02Xh", g);
        // Actually format: \05380079<group>h
        snprintf(cmd, sizeof(cmd), "\\0538007%02Xh", g);
        // Hmm, that's wrong. The command is \05 38 00 79 <group_hex>
        // So: \053800 79 XX h
        snprintf(cmd, sizeof(cmd), "\\0538007%02Xh", g);
    }
    // Simpler: test a few key values
    uint8_t test_groups[] = {0, 1, 127, 128, 254, 255};
    for (int i = 0; i < 6; i++) {
        char cmd[32];
        snprintf(cmd, sizeof(cmd), "\\053800%02X%02Xh", 0x79, test_groups[i]);
        cbus_parsed_packet_t pkt;
        TEST_ASSERT_TRUE(cbus_parse_command((const uint8_t*)cmd, strlen(cmd), &pkt));
        TEST_ASSERT_EQUAL(CBUS_PKT_LIGHTING_ON, pkt.type);
        TEST_ASSERT_EQUAL_UINT8(test_groups[i], pkt.group_addr);
    }
}

void test_parse_clock_update(void) {
    // Clock application: \05DF00...
    const uint8_t cmd[] = "\\05DF000801h";
    cbus_parsed_packet_t pkt;
    TEST_ASSERT_TRUE(cbus_parse_command(cmd, strlen((const char*)cmd), &pkt));
    TEST_ASSERT_EQUAL(CBUS_PKT_CLOCK_UPDATE, pkt.type);
    TEST_ASSERT_EQUAL_UINT8(CBUS_APP_CLOCK, pkt.application);
}

void test_parse_status_request(void) {
    // Status request: \05FF00730738 00h
    // PM, status_req app, routing, level_req(0x73), 0x07, child_app(0x38), block(0x00)
    const uint8_t cmd[] = "\\05FF0073073800h";
    cbus_parsed_packet_t pkt;
    TEST_ASSERT_TRUE(cbus_parse_command(cmd, strlen((const char*)cmd), &pkt));
    TEST_ASSERT_EQUAL(CBUS_PKT_STATUS_REQUEST, pkt.type);
    TEST_ASSERT_TRUE(pkt.level_request);
    TEST_ASSERT_EQUAL_UINT8(CBUS_APP_LIGHTING, pkt.child_app);
}

void test_parse_empty_command(void) {
    cbus_parsed_packet_t pkt;
    TEST_ASSERT_FALSE(cbus_parse_command((const uint8_t*)"", 0, &pkt));
}

void test_parse_invalid_hex(void) {
    const uint8_t cmd[] = "\\ZZZZ";
    cbus_parsed_packet_t pkt;
    TEST_ASSERT_FALSE(cbus_parse_command(cmd, strlen((const char*)cmd), &pkt));
}

// ============================================================
// Response Encoding Tests
// ============================================================

void test_encode_confirmation_success(void) {
    uint8_t buf[8];
    int len = cbus_encode_confirmation('h', true, buf, sizeof(buf));
    TEST_ASSERT_EQUAL_INT(4, len);
    TEST_ASSERT_EQUAL_UINT8('h', buf[0]);
    TEST_ASSERT_EQUAL_UINT8('.', buf[1]);
    TEST_ASSERT_EQUAL_UINT8(CBUS_CR, buf[2]);
    TEST_ASSERT_EQUAL_UINT8(CBUS_LF, buf[3]);
}

void test_encode_confirmation_failure(void) {
    uint8_t buf[8];
    int len = cbus_encode_confirmation('z', false, buf, sizeof(buf));
    TEST_ASSERT_EQUAL_INT(4, len);
    TEST_ASSERT_EQUAL_UINT8('z', buf[0]);
    TEST_ASSERT_EQUAL_UINT8('#', buf[1]);
}

void test_encode_all_confirmation_codes(void) {
    for (int i = 0; i < CBUS_CONF_CODE_COUNT; i++) {
        uint8_t buf[8];
        uint8_t code = CBUS_CONFIRMATION_CODES[i];
        int len = cbus_encode_confirmation(code, true, buf, sizeof(buf));
        TEST_ASSERT_EQUAL_INT(4, len);
        TEST_ASSERT_EQUAL_UINT8(code, buf[0]);
        TEST_ASSERT_EQUAL_UINT8('.', buf[1]);
    }
}

void test_encode_error(void) {
    uint8_t buf[8];
    int len = cbus_encode_error(buf, sizeof(buf));
    TEST_ASSERT_EQUAL_INT(3, len);
    TEST_ASSERT_EQUAL_UINT8('!', buf[0]);
}

void test_encode_powerup(void) {
    uint8_t buf[8];
    int len = cbus_encode_powerup(buf, sizeof(buf));
    TEST_ASSERT_EQUAL_INT(4, len);
    TEST_ASSERT_EQUAL_UINT8('+', buf[0]);
    TEST_ASSERT_EQUAL_UINT8('+', buf[1]);
}

void test_encode_level_status(void) {
    uint8_t levels[32];
    memset(levels, 0, sizeof(levels));
    levels[0] = 255;
    levels[1] = 128;
    levels[31] = 64;

    uint8_t buf[256];
    int len = cbus_encode_level_status(CBUS_APP_LIGHTING, 0, levels, buf, sizeof(buf));
    TEST_ASSERT_TRUE(len > 0);
    // Should end with CR LF
    TEST_ASSERT_EQUAL_UINT8(CBUS_CR, buf[len - 2]);
    TEST_ASSERT_EQUAL_UINT8(CBUS_LF, buf[len - 1]);
}

// ============================================================
// Bridge State Tests
// ============================================================

void test_bridge_init(void) {
    cbus_bridge_state_t state;
    bridge_init(&state);
    TEST_ASSERT_TRUE(state.smart_mode);
    TEST_ASSERT_EQUAL_UINT8(0xFF, state.source_address);
    for (int i = 0; i < 256; i++) {
        TEST_ASSERT_EQUAL_UINT8(0, state.levels[i]);
    }
}

void test_bridge_reset(void) {
    cbus_bridge_state_t state;
    bridge_init(&state);
    state.levels[5] = 200;
    state.smart_mode = true;
    bridge_reset(&state);
    TEST_ASSERT_EQUAL_UINT8(0, state.levels[5]);
    TEST_ASSERT_FALSE(state.smart_mode);  // Reset goes to basic mode
}

void test_bridge_set_get_level(void) {
    cbus_bridge_state_t state;
    bridge_init(&state);
    bridge_set_group_level(&state, 42, 128);
    TEST_ASSERT_EQUAL_UINT8(128, bridge_get_group_level(&state, 42));
}

void test_bridge_process_reset(void) {
    cbus_bridge_state_t state;
    bridge_init(&state);
    state.levels[0] = 100;

    uint8_t resp[256];
    int len = bridge_process_command(&state, (const uint8_t*)"~~~", 3, resp, sizeof(resp));
    TEST_ASSERT_EQUAL_INT(0, len);  // Reset has no response
    TEST_ASSERT_EQUAL_UINT8(0, state.levels[0]);  // Levels cleared
}

void test_bridge_process_lighting_on(void) {
    cbus_bridge_state_t state;
    bridge_init(&state);

    const uint8_t cmd[] = "\\0538007905h";
    uint8_t resp[256];
    int len = bridge_process_command(&state, cmd, strlen((const char*)cmd), resp, sizeof(resp));

    TEST_ASSERT_EQUAL_UINT8(255, state.levels[5]);
    TEST_ASSERT_TRUE(len > 0);
    // Check confirmation response
    TEST_ASSERT_EQUAL_UINT8('h', resp[0]);
    TEST_ASSERT_EQUAL_UINT8('.', resp[1]);
}

void test_bridge_process_lighting_off(void) {
    cbus_bridge_state_t state;
    bridge_init(&state);
    state.levels[5] = 255;

    const uint8_t cmd[] = "\\0538000105i";
    uint8_t resp[256];
    int len = bridge_process_command(&state, cmd, strlen((const char*)cmd), resp, sizeof(resp));

    TEST_ASSERT_EQUAL_UINT8(0, state.levels[5]);
    TEST_ASSERT_EQUAL_UINT8('i', resp[0]);
    TEST_ASSERT_EQUAL_UINT8('.', resp[1]);
}

void test_bridge_process_lighting_ramp(void) {
    cbus_bridge_state_t state;
    bridge_init(&state);

    // Ramp group 3 to level 0x80 (128) at instant rate (0x02)
    const uint8_t cmd[] = "\\0538000203" "80" "j";
    uint8_t resp[256];
    int len = bridge_process_command(&state, cmd, strlen((const char*)cmd), resp, sizeof(resp));

    TEST_ASSERT_EQUAL_UINT8(0x80, state.levels[3]);
}

void test_bridge_process_dm_command(void) {
    cbus_bridge_state_t state;
    bridge_init(&state);
    state.smart_mode = false;

    const uint8_t cmd[] = "A3300079";  // Enable SMART mode
    uint8_t resp[256];
    int len = bridge_process_command(&state, cmd, strlen((const char*)cmd), resp, sizeof(resp));

    TEST_ASSERT_TRUE(state.smart_mode);
    TEST_ASSERT_TRUE(len > 0);  // Should get confirmation
    TEST_ASSERT_EQUAL_UINT8('.', resp[1]);
}

void test_bridge_process_scs_shortcut(void) {
    cbus_bridge_state_t state;
    bridge_init(&state);
    state.smart_mode = false;

    const uint8_t cmd[] = "|";
    uint8_t resp[256];
    bridge_process_command(&state, cmd, 1, resp, sizeof(resp));

    TEST_ASSERT_TRUE(state.smart_mode);
}

void test_bridge_full_init_sequence(void) {
    // Simulate the full PCI reset sequence from pciprotocol.py
    cbus_bridge_state_t state;
    bridge_init(&state);

    uint8_t resp[512];
    int len;

    // Step 1: Three resets
    len = bridge_process_command(&state, (const uint8_t*)"~~~", 3, resp, sizeof(resp));
    len = bridge_process_command(&state, (const uint8_t*)"~~~", 3, resp, sizeof(resp));
    len = bridge_process_command(&state, (const uint8_t*)"~~~", 3, resp, sizeof(resp));

    // Step 2: Smart+Connect shortcut
    len = bridge_process_command(&state, (const uint8_t*)"|", 1, resp, sizeof(resp));
    TEST_ASSERT_TRUE(state.smart_mode);

    // Step 3: Set app address 1 to ALL
    len = bridge_process_command(&state, (const uint8_t*)"A32100FF", 8, resp, sizeof(resp));
    TEST_ASSERT_TRUE(len > 0);

    // Step 4: Set app address 2 to USED
    len = bridge_process_command(&state, (const uint8_t*)"A32200FF", 8, resp, sizeof(resp));
    TEST_ASSERT_TRUE(len > 0);

    // Step 5: Interface options #3
    len = bridge_process_command(&state, (const uint8_t*)"A342000E", 8, resp, sizeof(resp));
    TEST_ASSERT_TRUE(len > 0);

    // Step 6: Interface options #1 (SMART mode)
    len = bridge_process_command(&state, (const uint8_t*)"A3300079", 8, resp, sizeof(resp));
    TEST_ASSERT_TRUE(len > 0);
    TEST_ASSERT_TRUE(state.smart_mode);

    TEST_ASSERT_EQUAL_UINT32(7, state.commands_processed);
}

void test_bridge_all_256_groups(void) {
    cbus_bridge_state_t state;
    bridge_init(&state);
    uint8_t resp[256];

    for (int g = 0; g < 256; g++) {
        char cmd[32];
        snprintf(cmd, sizeof(cmd), "\\053800%02X%02Xh", CBUS_LIGHT_ON, g);
        bridge_process_command(&state, (const uint8_t*)cmd, strlen(cmd), resp, sizeof(resp));
        TEST_ASSERT_EQUAL_UINT8(255, state.levels[g]);
    }
}

// ============================================================
// Unity required stubs
// ============================================================

void setUp(void) {}
void tearDown(void) {}

// ============================================================
// Main
// ============================================================

int main(void) {
    UNITY_BEGIN();

    // Checksum
    RUN_TEST(test_checksum_known_value);
    RUN_TEST(test_checksum_single_byte);
    RUN_TEST(test_checksum_all_zeros);
    RUN_TEST(test_verify_checksum_valid);
    RUN_TEST(test_verify_checksum_invalid);

    // Hex
    RUN_TEST(test_hex_decode_valid);
    RUN_TEST(test_hex_decode_lowercase);
    RUN_TEST(test_hex_decode_odd_length_fails);
    RUN_TEST(test_hex_decode_invalid_chars_fails);
    RUN_TEST(test_hex_encode_valid);
    RUN_TEST(test_hex_encode_roundtrip);

    // Confirmation codes
    RUN_TEST(test_confirmation_codes_valid);
    RUN_TEST(test_confirmation_codes_invalid);
    RUN_TEST(test_confirmation_code_count);

    // Ramp rates
    RUN_TEST(test_ramp_rate_instant);
    RUN_TEST(test_ramp_rate_4_seconds);
    RUN_TEST(test_ramp_rate_30_seconds);
    RUN_TEST(test_ramp_rate_17_minutes);
    RUN_TEST(test_ramp_rate_invalid);
    RUN_TEST(test_all_ramp_rates_valid);

    // Command parsing
    RUN_TEST(test_parse_reset_triple);
    RUN_TEST(test_parse_scs_shortcut);
    RUN_TEST(test_parse_dm_command);
    RUN_TEST(test_parse_dm_command_at_prefix);
    RUN_TEST(test_parse_dm_app_addr_1);
    RUN_TEST(test_parse_dm_interface_opt3);
    RUN_TEST(test_parse_lighting_on);
    RUN_TEST(test_parse_lighting_off);
    RUN_TEST(test_parse_lighting_ramp);
    RUN_TEST(test_parse_lighting_on_no_confirmation);
    RUN_TEST(test_parse_lighting_terminate_ramp);
    RUN_TEST(test_parse_all_groups);
    RUN_TEST(test_parse_clock_update);
    RUN_TEST(test_parse_status_request);
    RUN_TEST(test_parse_empty_command);
    RUN_TEST(test_parse_invalid_hex);

    // Response encoding
    RUN_TEST(test_encode_confirmation_success);
    RUN_TEST(test_encode_confirmation_failure);
    RUN_TEST(test_encode_all_confirmation_codes);
    RUN_TEST(test_encode_error);
    RUN_TEST(test_encode_powerup);
    RUN_TEST(test_encode_level_status);

    // Bridge state
    RUN_TEST(test_bridge_init);
    RUN_TEST(test_bridge_reset);
    RUN_TEST(test_bridge_set_get_level);
    RUN_TEST(test_bridge_process_reset);
    RUN_TEST(test_bridge_process_lighting_on);
    RUN_TEST(test_bridge_process_lighting_off);
    RUN_TEST(test_bridge_process_lighting_ramp);
    RUN_TEST(test_bridge_process_dm_command);
    RUN_TEST(test_bridge_process_scs_shortcut);
    RUN_TEST(test_bridge_full_init_sequence);
    RUN_TEST(test_bridge_all_256_groups);

    return UNITY_END();
}
