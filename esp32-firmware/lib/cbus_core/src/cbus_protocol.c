/**
 * @file cbus_protocol.c
 * @brief Platform-independent C-Bus PCI protocol implementation.
 */
#include "cbus_protocol.h"
#include <string.h>

// ---- Confirmation codes: hijklmnopqrstuvwxyzg ----
const uint8_t CBUS_CONFIRMATION_CODES[CBUS_CONF_CODE_COUNT] = {
    'h','i','j','k','l','m','n','o','p','q',
    'r','s','t','u','v','w','x','y','z','g'
};

// ---- Ramp rate lookup table: code -> seconds ----
typedef struct { uint8_t code; int seconds; } ramp_entry_t;
static const ramp_entry_t RAMP_TABLE[] = {
    {0x02,    0}, // instant
    {0x0A,    4},
    {0x12,    8},
    {0x1A,   12},
    {0x22,   20},
    {0x2A,   30},
    {0x32,   40},
    {0x3A,   60},
    {0x42,   90},
    {0x4A,  120},
    {0x52,  180},
    {0x5A,  300},
    {0x62,  420},
    {0x6A,  600},
    {0x72,  900},
    {0x7A, 1020},
};
#define RAMP_TABLE_SIZE (sizeof(RAMP_TABLE) / sizeof(RAMP_TABLE[0]))

// ---- Checksum ----

uint8_t cbus_checksum(const uint8_t* data, size_t len) {
    uint8_t sum = 0;
    for (size_t i = 0; i < len; i++) {
        sum += data[i];
    }
    return (uint8_t)(((~sum) & 0xFF) + 1);
}

bool cbus_verify_checksum(const uint8_t* data, size_t len) {
    if (len < 2) return false;
    uint8_t sum = 0;
    for (size_t i = 0; i < len; i++) {
        sum += data[i];
    }
    return (sum & 0xFF) == 0;
}

// ---- Hex encoding/decoding ----

static int hex_digit(char c) {
    if (c >= '0' && c <= '9') return c - '0';
    if (c >= 'A' && c <= 'F') return c - 'A' + 10;
    if (c >= 'a' && c <= 'f') return c - 'a' + 10;
    return -1;
}

int cbus_hex_decode(const char* hex, size_t hex_len, uint8_t* out, size_t out_size) {
    if (hex_len % 2 != 0) return -1;
    size_t byte_count = hex_len / 2;
    if (byte_count > out_size) return -1;

    for (size_t i = 0; i < byte_count; i++) {
        int hi = hex_digit(hex[i * 2]);
        int lo = hex_digit(hex[i * 2 + 1]);
        if (hi < 0 || lo < 0) return -1;
        out[i] = (uint8_t)((hi << 4) | lo);
    }
    return (int)byte_count;
}

static const char HEX_CHARS[] = "0123456789ABCDEF";

int cbus_hex_encode(const uint8_t* data, size_t len, char* out, size_t out_size) {
    size_t needed = len * 2 + 1;
    if (needed > out_size) return -1;

    for (size_t i = 0; i < len; i++) {
        out[i * 2]     = HEX_CHARS[(data[i] >> 4) & 0x0F];
        out[i * 2 + 1] = HEX_CHARS[data[i] & 0x0F];
    }
    out[len * 2] = '\0';
    return (int)(len * 2);
}

// ---- Helpers ----

bool cbus_is_confirmation_code(uint8_t byte) {
    for (int i = 0; i < CBUS_CONF_CODE_COUNT; i++) {
        if (CBUS_CONFIRMATION_CODES[i] == byte) return true;
    }
    return false;
}

bool cbus_is_ramp_rate(uint8_t code) {
    for (size_t i = 0; i < RAMP_TABLE_SIZE; i++) {
        if (RAMP_TABLE[i].code == code) return true;
    }
    return false;
}

int cbus_ramp_rate_to_seconds(uint8_t ramp_rate) {
    for (size_t i = 0; i < RAMP_TABLE_SIZE; i++) {
        if (RAMP_TABLE[i].code == ramp_rate) return RAMP_TABLE[i].seconds;
    }
    return -1;
}

// ---- Manchester encoding ----

// Manchester nibble lookup: value 0-3 maps to encoded nibble
static const uint8_t MANCHESTER_NIBBLES[4] = {0x0A, 0x09, 0x06, 0x05};

int cbus_manchester_decode(uint8_t byte0, uint8_t byte1) {
    // Each byte contains two Manchester-encoded 2-bit values in its nibbles
    int n0 = -1, n1 = -1, n2 = -1, n3 = -1;
    for (int i = 0; i < 4; i++) {
        if (MANCHESTER_NIBBLES[i] == (byte0 & 0x0F)) n0 = i;
        if (MANCHESTER_NIBBLES[i] == (byte0 >> 4))   n1 = i;
        if (MANCHESTER_NIBBLES[i] == (byte1 & 0x0F)) n2 = i;
        if (MANCHESTER_NIBBLES[i] == (byte1 >> 4))   n3 = i;
    }
    if (n0 < 0 || n1 < 0 || n2 < 0 || n3 < 0) return -1;
    return n0 | (n1 << 2) | (n2 << 4) | (n3 << 6);
}

bool cbus_is_lighting_app(uint8_t app_id) {
    return app_id >= 0x30 && app_id <= 0x5F;
}

static void init_parsed(cbus_parsed_packet_t* p);

// ---- PCI Response Parser ----

bool cbus_parse_pci_response(const uint8_t* hex_data, size_t hex_len,
                             cbus_parsed_packet_t* out) {
    if (!hex_data || !out || hex_len < 4) return false;
    init_parsed(out);

    // Skip confirmations (2 bytes: code + '.' or '#')
    if (hex_len == 2 && (hex_data[1] == '.' || hex_data[1] == '#')) {
        out->type = CBUS_PKT_CONFIRMATION;
        out->conf_code = hex_data[0];
        return true;
    }
    // Skip power-up, error, prompt
    if (hex_data[0] == '+' || hex_data[0] == '!' || hex_data[0] == '>') return false;

    // Hex decode the response
    uint8_t pkt[CBUS_MAX_PACKET_SIZE];
    int pkt_len = cbus_hex_decode((const char*)hex_data, hex_len, pkt, sizeof(pkt));
    if (pkt_len < 4) return false;

    // Verify checksum (last byte is checksum)
    if (pkt_len >= 3 && cbus_verify_checksum(pkt, pkt_len)) {
        pkt_len--;  // Strip checksum
    }

    memcpy(out->raw, pkt, pkt_len);
    out->raw_len = pkt_len;

    uint8_t flags = pkt[0];
    uint8_t dat = flags & 0x07;

    if (dat == CBUS_DAT_PM && pkt_len >= 5) {
        // Point-to-Multipoint from PCI: flags, source_addr, app, routing, SAL...
        // When from_pci=True, byte 1 is source address
        out->source_addr = pkt[1];
        out->application = pkt[2];
        // routing = pkt[3]

        if (cbus_is_lighting_app(out->application) && pkt_len >= 6) {
            uint8_t cmd = pkt[4];
            out->group_addr = pkt[5];

            if (cmd == CBUS_LIGHT_ON) {
                out->type = CBUS_PKT_LIGHTING_ON;
                out->level = 255;
            } else if (cmd == CBUS_LIGHT_OFF) {
                out->type = CBUS_PKT_LIGHTING_OFF;
                out->level = 0;
            } else if (cmd == CBUS_LIGHT_TERMINATE) {
                out->type = CBUS_PKT_LIGHTING_TERMINATE;
            } else if (cbus_is_ramp_rate(cmd) && pkt_len >= 7) {
                out->type = CBUS_PKT_LIGHTING_RAMP;
                out->ramp_rate = cmd;
                out->level = pkt[6];
            }
        } else if (out->application == CBUS_APP_CLOCK) {
            out->type = CBUS_PKT_CLOCK_UPDATE;
        }
    } else if (dat == CBUS_DAT_PP && pkt_len >= 5) {
        // Point-to-Point from PCI: flags, source_addr, unit_addr, routing, CAL...
        out->source_addr = pkt[1];

        // Look for Extended Status CAL (upper 3 bits = 0xE0)
        // CAL data starts after flags(1) + source(1) + unit(1) + routing(1) = pkt[4]
        int cal_start = 4;
        if (cal_start < pkt_len) {
            uint8_t cal_cmd = pkt[cal_start];
            if ((cal_cmd & 0xE0) == 0xE0) {
                // Extended CAL: lower 5 bits + 1 = total bytes after cmd byte
                // Python: cal_end = (cmd & 0x1f) + 1; reply_data = data[1:cal_end]
                int cal_total = (cal_cmd & 0x1F) + 1;  // total span including cmd byte
                int cal_end = cal_start + cal_total;
                int reply_len = cal_total - 1;  // bytes after the cmd byte
                if (cal_end <= pkt_len && reply_len >= 3) {
                    // reply_data: coding_byte, child_app, block_start, manchester_data...
                    // uint8_t coding = pkt[cal_start + 1];
                    uint8_t child_app = pkt[cal_start + 2];
                    uint8_t block_start = pkt[cal_start + 3];
                    int data_start = cal_start + 4;
                    int data_len = reply_len - 3;  // subtract coding, child_app, block_start

                    if (cbus_is_lighting_app(child_app) && data_len >= 2 && data_len % 2 == 0) {
                        out->type = CBUS_PKT_STATUS_REQUEST;  // Reuse as "status report"
                        out->child_app = child_app;
                        out->block_start = block_start;
                        out->level_count = 0;

                        // Manchester decode pairs of bytes into levels
                        for (int i = 0; i < data_len && out->level_count < 32; i += 2) {
                            int level = cbus_manchester_decode(
                                pkt[data_start + i], pkt[data_start + i + 1]);
                            if (level >= 0) {
                                out->level_data[out->level_count++] = (uint8_t)level;
                            } else {
                                out->level_data[out->level_count++] = 0;  // Decode error
                            }
                        }
                        return true;
                    }
                }
            }
        }
        out->type = CBUS_PKT_PP_OTHER;
    }

    return out->type != CBUS_PKT_UNKNOWN;
}

// ---- Packet Parsing ----

static void init_parsed(cbus_parsed_packet_t* p) {
    memset(p, 0, sizeof(*p));
    p->type = CBUS_PKT_UNKNOWN;
}

static bool parse_dm_command(const uint8_t* data, size_t len, cbus_parsed_packet_t* out) {
    // Device Management commands: A3<param_hex><00><value_hex>
    // Example: "A3300079" = param=0x30, padding=0x00, value=0x79
    // Or with @ prefix: "@A3300079"
    size_t offset = 0;
    if (len > 0 && data[0] == '@') offset = 1;

    if (len < offset + 8) return false;
    if (data[offset] != 'A' || data[offset + 1] != '3') return false;

    // Parse 3 hex bytes: parameter, padding(00), value
    uint8_t decoded[3];
    int n = cbus_hex_decode((const char*)&data[offset + 2], 6, decoded, 3);
    if (n != 3) return false;

    out->type = CBUS_PKT_DEVICE_MGMT;
    out->dm_parameter = decoded[0];
    // decoded[1] is the 0x00 padding byte
    out->dm_value = decoded[2];
    return true;
}

static bool parse_escaped_command(const uint8_t* data, size_t len, cbus_parsed_packet_t* out) {
    // Escaped command format: \<hex_encoded_packet>[conf_code]
    // data[0] is '\', so payload starts at data[1]
    if (len < 3) return false;

    const uint8_t* hex_start = data + 1;
    size_t hex_len = len - 1;

    // Check for confirmation code at the end
    out->conf_code = 0;
    if (hex_len > 0 && cbus_is_confirmation_code(hex_start[hex_len - 1])) {
        out->conf_code = hex_start[hex_len - 1];
        hex_len--;
    }

    // Hex decode the payload
    uint8_t packet[CBUS_MAX_PACKET_SIZE];
    int pkt_len = cbus_hex_decode((const char*)hex_start, hex_len, packet, sizeof(packet));
    if (pkt_len < 1) return false;

    // Store raw decoded bytes
    memcpy(out->raw, packet, pkt_len);
    out->raw_len = pkt_len;

    // Parse flags byte
    uint8_t flags = packet[0];
    uint8_t dat = flags & 0x07;

    if (dat == CBUS_DAT_PM && pkt_len >= 4) {
        // Point-to-Multipoint
        out->application = packet[1];
        uint8_t routing = packet[2];
        (void)routing;

        if (out->application == CBUS_APP_LIGHTING) {
            uint8_t cmd = packet[3];
            out->group_addr = (pkt_len > 4) ? packet[4] : 0;

            if (cmd == CBUS_LIGHT_ON) {
                out->type = CBUS_PKT_LIGHTING_ON;
                out->level = 255;
            } else if (cmd == CBUS_LIGHT_OFF) {
                out->type = CBUS_PKT_LIGHTING_OFF;
                out->level = 0;
            } else if (cmd == CBUS_LIGHT_TERMINATE) {
                out->type = CBUS_PKT_LIGHTING_TERMINATE;
            } else if (cbus_is_ramp_rate(cmd)) {
                out->type = CBUS_PKT_LIGHTING_RAMP;
                out->ramp_rate = cmd;
                out->level = (pkt_len > 5) ? packet[5] : 255;
            }
        } else if (out->application == CBUS_APP_STATUS_REQ) {
            out->type = CBUS_PKT_STATUS_REQUEST;
            // Parse status request details
            if (pkt_len >= 5) {
                uint8_t req_type = packet[3];
                if (req_type == CBUS_STATUS_BINARY) {
                    out->level_request = false;
                    out->child_app = packet[4];
                    out->block_start = (pkt_len > 5) ? packet[5] : 0;
                } else if (req_type == CBUS_STATUS_LEVEL && pkt_len >= 6) {
                    out->level_request = true;
                    out->child_app = packet[5];
                    out->block_start = (pkt_len > 6) ? packet[6] : 0;
                }
            }
        } else if (out->application == CBUS_APP_CLOCK) {
            out->type = CBUS_PKT_CLOCK_UPDATE;
        }
    } else if (dat == CBUS_DAT_PP && pkt_len >= 3) {
        // Point-to-Point
        out->type = CBUS_PKT_PP_OTHER;
        out->source_addr = packet[1];
    }

    return out->type != CBUS_PKT_UNKNOWN;
}

bool cbus_parse_command(const uint8_t* data, size_t len, cbus_parsed_packet_t* out) {
    init_parsed(out);

    if (len == 0) return false;

    // Reset: ~~~
    if (len == 3 && data[0] == '~' && data[1] == '~' && data[2] == '~') {
        out->type = CBUS_PKT_RESET;
        return true;
    }
    // Single reset
    if (len == 1 && data[0] == '~') {
        out->type = CBUS_PKT_RESET;
        return true;
    }

    // Smart+Connect shortcut: |
    if (len == 1 && data[0] == CBUS_SCS_SHORTCUT) {
        out->type = CBUS_PKT_SCS_SHORTCUT;
        return true;
    }

    // Device Management: A3XXYY or @A3XXYY
    if ((len >= 6 && data[0] == 'A' && data[1] == '3') ||
        (len >= 7 && data[0] == '@' && data[1] == 'A' && data[2] == '3')) {
        return parse_dm_command(data, len, out);
    }

    // Escaped hex command: \XXXX...
    if (data[0] == CBUS_ESCAPE) {
        return parse_escaped_command(data, len, out);
    }

    return false;
}

// ---- Packet Encoding ----

int cbus_encode_confirmation(uint8_t conf_code, bool success, uint8_t* out, size_t out_size) {
    if (out_size < 4) return -1;
    out[0] = conf_code;
    out[1] = success ? CBUS_CONF_SUCCESS : CBUS_CONF_FAILURE;
    out[2] = CBUS_CR;
    out[3] = CBUS_LF;
    return 4;
}

int cbus_encode_error(uint8_t* out, size_t out_size) {
    if (out_size < 3) return -1;
    out[0] = CBUS_ERROR_CHAR;
    out[1] = CBUS_CR;
    out[2] = CBUS_LF;
    return 3;
}

int cbus_encode_powerup(uint8_t* out, size_t out_size) {
    if (out_size < 4) return -1;
    out[0] = CBUS_POWERUP_CHAR;
    out[1] = CBUS_POWERUP_CHAR;
    out[2] = CBUS_CR;
    out[3] = CBUS_LF;
    return 4;
}

int cbus_encode_level_status(uint8_t app_id, uint8_t block_start,
                             const uint8_t levels[32],
                             uint8_t* out, size_t out_size) {
    // Build a hex-encoded level status response
    // Format: PP extended CAL: 86FFFF00<app>E0<block><32 level bytes><checksum>
    uint8_t binary[40]; // 7 header + 32 levels + 1 checksum
    binary[0] = 0x86;         // PP flags (from PCI, priority class 2)
    binary[1] = 0xFF;         // Source: PCI
    binary[2] = 0xFF;         // Routing: none
    binary[3] = 0x00;         // Reserved
    binary[4] = app_id;       // Child application
    binary[5] = 0xE0;         // Extended status indicator
    binary[6] = block_start;  // Block start address

    for (int i = 0; i < 32; i++) {
        binary[7 + i] = levels[i];
    }

    size_t bin_len = 39;
    // Add checksum
    binary[bin_len - 1] = cbus_checksum(binary, bin_len - 1);

    // Hex encode
    size_t hex_needed = bin_len * 2 + 3; // hex + CR + LF + null
    if (out_size < hex_needed) return -1;

    int hex_len = cbus_hex_encode(binary, bin_len, (char*)out, out_size - 2);
    if (hex_len < 0) return -1;

    out[hex_len] = CBUS_CR;
    out[hex_len + 1] = CBUS_LF;
    return hex_len + 2;
}

int cbus_encode_lighting_event(uint8_t source_addr, uint8_t app_id,
                               uint8_t group_addr, uint8_t command,
                               uint8_t level,
                               uint8_t* out, size_t out_size) {
    // Build a hex-encoded PM lighting event notification
    uint8_t binary[8];
    size_t bin_len;

    binary[0] = CBUS_DAT_PM;  // PM flags
    binary[1] = app_id;
    binary[2] = 0x00;         // Routing: none
    binary[3] = command;
    binary[4] = group_addr;

    if (command == CBUS_LIGHT_ON || command == CBUS_LIGHT_OFF ||
        command == CBUS_LIGHT_TERMINATE) {
        bin_len = 5;
    } else {
        // Ramp: includes level
        binary[5] = level;
        bin_len = 6;
    }

    // Add source address encoding
    // The source is typically prepended in the response
    // For simplicity, include it in the routing field area

    // Add checksum
    binary[bin_len] = cbus_checksum(binary, bin_len);
    bin_len++;

    size_t hex_needed = bin_len * 2 + 3;
    if (out_size < hex_needed) return -1;

    int hex_len = cbus_hex_encode(binary, bin_len, (char*)out, out_size - 2);
    if (hex_len < 0) return -1;

    out[hex_len] = CBUS_CR;
    out[hex_len + 1] = CBUS_LF;
    return hex_len + 2;
}
