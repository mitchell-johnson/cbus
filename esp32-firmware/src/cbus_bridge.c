/**
 * @file cbus_bridge.c
 * @brief C-Bus Bridge state management and command processing.
 */
#include "cbus_bridge.h"
#include <string.h>

void bridge_init(cbus_bridge_state_t* state) {
    if (!state) return;
    memset(state, 0, sizeof(*state));
    state->smart_mode = true;
    state->source_address = 0xFF;  // PCI default
}

void bridge_reset(cbus_bridge_state_t* state) {
    if (!state) return;
    memset(state->levels, 0, sizeof(state->levels));
    state->confirmation_index = 0;
    state->smart_mode = false;  // Reset to basic mode
}

uint8_t bridge_get_group_level(const cbus_bridge_state_t* state, uint8_t group) {
    return state->levels[group];
}

void bridge_set_group_level(cbus_bridge_state_t* state, uint8_t group, uint8_t level) {
    state->levels[group] = level;
}

int bridge_process_command(cbus_bridge_state_t* state,
                          const uint8_t* cmd, size_t cmd_len,
                          uint8_t* resp, size_t resp_size) {
    if (!state || !cmd || !resp || cmd_len == 0 || resp_size < 4) return 0;

    state->commands_received++;
    int resp_len = 0;

    cbus_parsed_packet_t pkt;
    if (!cbus_parse_command(cmd, cmd_len, &pkt)) {
        state->errors++;
        return 0;
    }

    state->commands_processed++;

    switch (pkt.type) {
        case CBUS_PKT_RESET:
            bridge_reset(state);
            // No response for reset
            break;

        case CBUS_PKT_SCS_SHORTCUT:
            state->smart_mode = true;
            break;

        case CBUS_PKT_DEVICE_MGMT:
            // Process device management and send confirmation
            if (pkt.dm_parameter == CBUS_DM_IFACE_OPT_1) {
                // Interface options #1 - check for SMART mode bit
                if (pkt.dm_value & 0x10) {
                    state->smart_mode = true;
                }
            }
            // Always confirm DM commands with 'g'
            resp_len = cbus_encode_confirmation('g', true, resp, resp_size);
            break;

        case CBUS_PKT_LIGHTING_ON:
            state->levels[pkt.group_addr] = 255;
            if (pkt.conf_code) {
                resp_len = cbus_encode_confirmation(pkt.conf_code, true, resp, resp_size);
            }
            break;

        case CBUS_PKT_LIGHTING_OFF:
            state->levels[pkt.group_addr] = 0;
            if (pkt.conf_code) {
                resp_len = cbus_encode_confirmation(pkt.conf_code, true, resp, resp_size);
            }
            break;

        case CBUS_PKT_LIGHTING_RAMP:
            state->levels[pkt.group_addr] = pkt.level;
            if (pkt.conf_code) {
                resp_len = cbus_encode_confirmation(pkt.conf_code, true, resp, resp_size);
            }
            break;

        case CBUS_PKT_LIGHTING_TERMINATE:
            // Keep current level (stop ramping)
            if (pkt.conf_code) {
                resp_len = cbus_encode_confirmation(pkt.conf_code, true, resp, resp_size);
            }
            break;

        case CBUS_PKT_STATUS_REQUEST: {
            // Send confirmation first if requested
            if (pkt.conf_code) {
                resp_len = cbus_encode_confirmation(pkt.conf_code, true, resp, resp_size);
            }
            // Then send level status report
            uint8_t levels[32];
            for (int i = 0; i < 32; i++) {
                int gid = (int)pkt.block_start + i;
                levels[i] = (gid < CBUS_MAX_GROUPS) ? state->levels[gid] : 0;
            }
            int status_len = cbus_encode_level_status(
                pkt.child_app, pkt.block_start, levels,
                resp + resp_len, resp_size - resp_len
            );
            if (status_len > 0) resp_len += status_len;
            break;
        }

        case CBUS_PKT_CLOCK_UPDATE:
            if (pkt.conf_code) {
                resp_len = cbus_encode_confirmation(pkt.conf_code, true, resp, resp_size);
            }
            break;

        default:
            break;
    }

    return resp_len;
}
