/**
 * @file cbus_protocol.h
 * @brief Platform-independent C-Bus PCI protocol parser and encoder.
 *
 * Implements the Clipsal C-Bus serial/TCP protocol at the byte level.
 * This code compiles for both ESP32 (Arduino) and native (testing).
 */
#ifndef CBUS_PROTOCOL_H
#define CBUS_PROTOCOL_H

#include <stdint.h>
#include <stddef.h>
#include <stdbool.h>

#ifdef __cplusplus
extern "C" {
#endif

// ---- Constants ----

#define CBUS_MAX_PACKET_SIZE    256
#define CBUS_MAX_GROUPS         256
#define CBUS_MAX_HEX_SIZE      (CBUS_MAX_PACKET_SIZE * 2 + 16)
#define CBUS_CONF_CODE_COUNT    20
#define CBUS_DEFAULT_TCP_PORT   10001

// Packet terminators
#define CBUS_CR                 0x0D
#define CBUS_LF                 0x0A
#define CBUS_ESCAPE             0x5C  // '\'

// Special characters
#define CBUS_RESET_CHAR         0x7E  // '~'
#define CBUS_SCS_SHORTCUT       0x7C  // '|'
#define CBUS_POWERUP_CHAR       0x2B  // '+'
#define CBUS_ERROR_CHAR         0x21  // '!'

// Confirmation result markers
#define CBUS_CONF_SUCCESS       0x2E  // '.'
#define CBUS_CONF_FAILURE       0x23  // '#'

// Destination Address Types (lower 3 bits of flags byte)
#define CBUS_DAT_PM             0x05  // Point-to-Multipoint
#define CBUS_DAT_PP             0x06  // Point-to-Point
#define CBUS_DAT_PPM            0x03  // Point-to-Point-to-Multipoint
#define CBUS_FLAG_DM            0x20  // Device Management flag

// Application IDs
#define CBUS_APP_LIGHTING       0x38
#define CBUS_APP_CLOCK          0xDF
#define CBUS_APP_STATUS_REQ     0xFF

// Lighting commands
#define CBUS_LIGHT_ON           0x79
#define CBUS_LIGHT_OFF          0x01
#define CBUS_LIGHT_RAMP_INSTANT 0x02
#define CBUS_LIGHT_TERMINATE    0x09

// Status request types
#define CBUS_STATUS_BINARY      0x7A
#define CBUS_STATUS_LEVEL       0x73
#define CBUS_STATUS_LEVEL_2     0x07

// Device Management parameters
#define CBUS_DM_APP_ADDR_1      0x21
#define CBUS_DM_APP_ADDR_2      0x22
#define CBUS_DM_IFACE_OPT_3    0x42
#define CBUS_DM_IFACE_OPT_1    0x30

// Clock attributes
#define CBUS_CLOCK_ATTR_TIME    0x01
#define CBUS_CLOCK_ATTR_DATE    0x02

// ---- Confirmation codes ----

extern const uint8_t CBUS_CONFIRMATION_CODES[CBUS_CONF_CODE_COUNT];

// ---- Data types ----

typedef enum {
    CBUS_PKT_UNKNOWN = 0,
    CBUS_PKT_RESET,
    CBUS_PKT_SCS_SHORTCUT,
    CBUS_PKT_POWERUP,
    CBUS_PKT_ERROR,
    CBUS_PKT_CONFIRMATION,
    CBUS_PKT_DEVICE_MGMT,
    CBUS_PKT_LIGHTING_ON,
    CBUS_PKT_LIGHTING_OFF,
    CBUS_PKT_LIGHTING_RAMP,
    CBUS_PKT_LIGHTING_TERMINATE,
    CBUS_PKT_STATUS_REQUEST,
    CBUS_PKT_CLOCK_UPDATE,
    CBUS_PKT_CLOCK_REQUEST,
    CBUS_PKT_IDENTIFY,
    CBUS_PKT_PP_OTHER,
} cbus_packet_type_t;

typedef struct {
    cbus_packet_type_t type;
    uint8_t application;    // Application ID (0x38, 0xDF, 0xFF, etc.)
    uint8_t group_addr;     // Group address (0-255)
    uint8_t level;          // Level (0-255, for ramp commands)
    uint8_t ramp_rate;      // Ramp rate code
    uint8_t conf_code;      // Confirmation code byte (0 if none)
    uint8_t source_addr;    // Source address (for PP packets)
    uint8_t dm_parameter;   // Device Management parameter
    uint8_t dm_value;       // Device Management value
    bool    has_checksum;   // Whether packet had valid checksum
    // Status request specifics
    uint8_t child_app;      // Child application for status requests
    uint8_t block_start;    // Block start address for status requests
    bool    level_request;  // True for level request, false for binary
    // Status report level data (decoded from Manchester)
    uint8_t level_data[32];
    uint8_t level_count;    // Number of valid entries in level_data
    // Raw data
    uint8_t raw[CBUS_MAX_PACKET_SIZE];
    size_t  raw_len;
} cbus_parsed_packet_t;

// ---- Checksum ----

/**
 * Calculate C-Bus checksum for a byte array.
 * The checksum is the two's complement of the sum of all bytes.
 */
uint8_t cbus_checksum(const uint8_t* data, size_t len);

/**
 * Verify a C-Bus checksum. The sum of all bytes (including checksum)
 * should be 0x00.
 */
bool cbus_verify_checksum(const uint8_t* data, size_t len);

// ---- Hex encoding/decoding ----

/**
 * Decode hex-encoded ASCII string to binary bytes.
 * @return Number of decoded bytes, or -1 on error.
 */
int cbus_hex_decode(const char* hex, size_t hex_len, uint8_t* out, size_t out_size);

/**
 * Encode binary bytes to hex-encoded ASCII string.
 * @return Number of characters written (excluding null terminator).
 */
int cbus_hex_encode(const uint8_t* data, size_t len, char* out, size_t out_size);

// ---- Packet Parsing ----

/**
 * Parse a raw command received from a client.
 * This handles the full C-Bus command format including:
 * - Reset (~~~)
 * - Smart+Connect shortcut (|)
 * - Device Management (A3XXYY)
 * - Escaped hex commands (\XXXX...CC)
 *
 * @param data      Raw bytes from client (without CR/LF terminator)
 * @param len       Length of data
 * @param out       Parsed packet output
 * @return          true if packet was successfully parsed
 */
bool cbus_parse_command(const uint8_t* data, size_t len, cbus_parsed_packet_t* out);

/**
 * Check if a byte is a valid confirmation code.
 */
bool cbus_is_confirmation_code(uint8_t byte);

// ---- Packet Encoding (responses FROM PCI TO client) ----

/**
 * Encode a confirmation response.
 * Format: <conf_code><'.' or '#'><CR><LF>
 * @return Number of bytes written.
 */
int cbus_encode_confirmation(uint8_t conf_code, bool success, uint8_t* out, size_t out_size);

/**
 * Encode a PCI error response.
 * @return Number of bytes written.
 */
int cbus_encode_error(uint8_t* out, size_t out_size);

/**
 * Encode a power-up notification.
 * @return Number of bytes written.
 */
int cbus_encode_powerup(uint8_t* out, size_t out_size);

/**
 * Encode a level status report for a block of 32 groups.
 * Builds a Point-to-Point Extended CAL response.
 * @param app_id      Application ID
 * @param block_start Start group address (must be multiple of 32)
 * @param levels      Array of 32 level values (0-255)
 * @return Number of bytes written.
 */
int cbus_encode_level_status(uint8_t app_id, uint8_t block_start,
                             const uint8_t levels[32],
                             uint8_t* out, size_t out_size);

/**
 * Encode a lighting event notification (broadcast from PCI to monitoring clients).
 * Builds a Point-to-Multipoint packet indicating a group state change.
 * @return Number of bytes written.
 */
int cbus_encode_lighting_event(uint8_t source_addr, uint8_t app_id,
                               uint8_t group_addr, uint8_t command,
                               uint8_t level,
                               uint8_t* out, size_t out_size);

// ---- Manchester encoding (used in status reports) ----

/**
 * Manchester-decode 2 bytes into a single level value (0-255).
 * @return Decoded value, or -1 on decode error.
 */
int cbus_manchester_decode(uint8_t byte0, uint8_t byte1);

/**
 * Check if a byte is a lighting application (0x30-0x5F).
 */
bool cbus_is_lighting_app(uint8_t app_id);

/**
 * Parse a hex-encoded response FROM a PCI/CNI.
 * Extracts lighting events and level status reports.
 *
 * @param hex_data  Raw hex bytes from CNI (without CR/LF)
 * @param hex_len   Length of hex data
 * @param out       Parsed packet output
 * @return          true if a lighting-relevant packet was parsed
 */
bool cbus_parse_pci_response(const uint8_t* hex_data, size_t hex_len,
                             cbus_parsed_packet_t* out);

// ---- Ramp rate utilities ----

/**
 * Get the ramp duration in seconds for a ramp rate code.
 * @return Duration in seconds, or -1 if not a valid ramp code.
 */
int cbus_ramp_rate_to_seconds(uint8_t ramp_rate);

/**
 * Check if a byte is a valid ramp rate code.
 */
bool cbus_is_ramp_rate(uint8_t code);

#ifdef __cplusplus
}
#endif

#endif // CBUS_PROTOCOL_H
