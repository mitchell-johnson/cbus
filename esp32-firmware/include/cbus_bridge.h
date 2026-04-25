/**
 * @file cbus_bridge.h
 * @brief ESP32 C-Bus Bridge - TCP server and group state management.
 *
 * Platform-independent bridge logic. On ESP32, this is called from
 * Arduino main.cpp. For testing, it's called from the native test server.
 */
#ifndef CBUS_BRIDGE_H
#define CBUS_BRIDGE_H

#include "cbus_protocol.h"

#ifdef __cplusplus
extern "C" {
#endif

#define BRIDGE_MAX_CLIENTS      5
#define BRIDGE_RECV_BUF_SIZE    1024

typedef struct {
    uint8_t levels[CBUS_MAX_GROUPS];       // Current level for each group
    uint8_t confirmation_index;            // Next confirmation code index
    bool    smart_mode;                    // Whether in SMART mode
    uint8_t source_address;                // Default source address
    // Statistics
    uint32_t commands_received;
    uint32_t commands_processed;
    uint32_t errors;
} cbus_bridge_state_t;

/**
 * Initialize bridge state to defaults.
 */
void bridge_init(cbus_bridge_state_t* state);

/**
 * Reset bridge state (called on ~~~ reset command).
 */
void bridge_reset(cbus_bridge_state_t* state);

/**
 * Process a single command and generate response.
 *
 * @param state     Bridge state
 * @param cmd       Command bytes (without CR/LF terminator)
 * @param cmd_len   Length of command
 * @param resp      Output buffer for response
 * @param resp_size Size of output buffer
 * @return          Number of response bytes written, or 0 for no response
 */
int bridge_process_command(cbus_bridge_state_t* state,
                          const uint8_t* cmd, size_t cmd_len,
                          uint8_t* resp, size_t resp_size);

/**
 * Get the level of a lighting group.
 */
uint8_t bridge_get_group_level(const cbus_bridge_state_t* state, uint8_t group);

/**
 * Set the level of a lighting group directly (for testing/web UI).
 */
void bridge_set_group_level(cbus_bridge_state_t* state, uint8_t group, uint8_t level);

#ifdef __cplusplus
}
#endif

#endif // CBUS_BRIDGE_H
