/**
 * @file main.cpp
 * @brief ESP32 C-Bus -> MQTT Bridge (replaces cmqttd Docker container)
 *
 * Connects to:
 *   1. C-Bus CNI (TCP client, configurable address)
 *   2. MQTT broker (configurable address)
 *
 * Bridges C-Bus lighting events to Home Assistant via MQTT Discovery.
 * Supports all lighting applications 0x30-0x5F.
 *
 * Serial console commands:
 *   wifi <ssid> <pass>   - Set WiFi credentials
 *   cni <host> <port>    - Set CNI address
 *   mqtt <host> <port>   - Set MQTT broker address
 *   mqttauth <user> <pw> - Set MQTT credentials
 *   tz <posix_tz>        - Set timezone (POSIX TZ string)
 *   scan                 - Scan WiFi networks
 *   status               - Show current status
 *   reset                - Reboot
 *   factory              - Erase config & reboot
 *   help                 - Show commands
 */

#ifdef PLATFORM_ESP32

#include <Arduino.h>
#include <WiFi.h>
#include <ESPmDNS.h>
#include <DNSServer.h>
#include <Preferences.h>
#include <WebServer.h>
#include <PubSubClient.h>
#include <ArduinoJson.h>
#include <time.h>

extern "C" {
#include "cbus_protocol.h"
#include "cbus_bridge.h"
}

// ---- Configuration ----
static Preferences prefs;
static String wifi_ssid, wifi_pass;
static String cni_host = "";
static uint16_t cni_port = 10001;
static String mqtt_host = "";
static uint16_t mqtt_port = 1883;
static String mqtt_user, mqtt_pass;
static String tz_str = "UTC0";
static bool ap_mode = false;

// ---- State ----
static cbus_bridge_state_t bridge;
static WiFiClient cni_client;       // TCP connection to CNI
static WiFiClient mqtt_wifi_client;  // WiFi client for MQTT
static PubSubClient mqtt(mqtt_wifi_client);
static uint8_t cni_buf[1024];
static size_t cni_buf_len = 0;
static bool cni_connected = false;
static bool cni_initialized = false;
static unsigned long last_timesync = 0;
static unsigned long last_status_req = 0;
static unsigned long last_cni_attempt = 0;
static unsigned long last_mqtt_attempt = 0;
static unsigned long last_cni_send = 0;
static uint8_t conf_idx = 0;
static bool published[256];  // Track which groups have HA discovery published
static WebServer* web_server = nullptr;
static DNSServer* dns_server = nullptr;

// ---- Configured group labels (only these get HA discovery) ----
// Label table: group_addr -> name. NULL = not configured (no discovery).
// Populated from NVS or defaults below. Max label length 47 chars.
#define MAX_CONFIGURED_GROUPS 64
static struct {
    uint8_t ga;
    uint8_t app;
    char label[48];
} group_labels[MAX_CONFIGURED_GROUPS];
static uint8_t num_configured_groups = 0;

// Returns the label for a (app, ga) pair, or NULL if not configured
static const char* get_group_label(uint8_t app, uint8_t ga) {
    for (uint8_t i = 0; i < num_configured_groups; i++) {
        if (group_labels[i].app == app && group_labels[i].ga == ga) {
            return group_labels[i].label;
        }
    }
    return NULL;
}

// Returns true if this (app, ga) has a configured label
static bool is_group_configured(uint8_t app, uint8_t ga) {
    return get_group_label(app, ga) != NULL;
}

static void add_group_label(uint8_t app, uint8_t ga, const char* label) {
    if (num_configured_groups >= MAX_CONFIGURED_GROUPS) return;
    group_labels[num_configured_groups].app = app;
    group_labels[num_configured_groups].ga = ga;
    strncpy(group_labels[num_configured_groups].label, label, 47);
    group_labels[num_configured_groups].label[47] = '\0';
    num_configured_groups++;
}

// Default labels for Mitchell's C-Bus installation
static void load_default_group_labels() {
    num_configured_groups = 0;
    add_group_label(CBUS_APP_LIGHTING, 0, "outside wall light");
    add_group_label(CBUS_APP_LIGHTING, 1, "outside wall light front");
    add_group_label(CBUS_APP_LIGHTING, 2, "tread lights x 2");
    add_group_label(CBUS_APP_LIGHTING, 3, "under staircase storage");
    add_group_label(CBUS_APP_LIGHTING, 4, "tread lights stairwell");
    add_group_label(CBUS_APP_LIGHTING, 5, "outside wall light rear");
    add_group_label(CBUS_APP_LIGHTING, 6, "outside wall light side");
    add_group_label(CBUS_APP_LIGHTING, 7, "prov 1");
    add_group_label(CBUS_APP_LIGHTING, 8, "prov 2");
    add_group_label(CBUS_APP_LIGHTING, 9, "prov 3");
    add_group_label(CBUS_APP_LIGHTING, 10, "prov 4");
    add_group_label(CBUS_APP_LIGHTING, 11, "prov 5");
    add_group_label(CBUS_APP_LIGHTING, 12, "downstairs toilet");
    add_group_label(CBUS_APP_LIGHTING, 13, "laundry");
    add_group_label(CBUS_APP_LIGHTING, 14, "garage");
    add_group_label(CBUS_APP_LIGHTING, 15, "bathroom fan");
    add_group_label(CBUS_APP_LIGHTING, 16, "kitchen island");
    add_group_label(CBUS_APP_LIGHTING, 17, "bathroom vanity");
    add_group_label(CBUS_APP_LIGHTING, 18, "bathroom lights");
    add_group_label(CBUS_APP_LIGHTING, 19, "ensuite vanity");
    add_group_label(CBUS_APP_LIGHTING, 20, "ensuite fan");
    add_group_label(CBUS_APP_LIGHTING, 21, "ensuite shower");
    add_group_label(CBUS_APP_LIGHTING, 22, "ensuite ceiling light");
    add_group_label(CBUS_APP_LIGHTING, 23, "master walk in robe");
    add_group_label(CBUS_APP_LIGHTING, 24, "loungeroom");
    add_group_label(CBUS_APP_LIGHTING, 25, "hallway downstairs");
    add_group_label(CBUS_APP_LIGHTING, 26, "study");
    add_group_label(CBUS_APP_LIGHTING, 27, "kitchen downlights");
    add_group_label(CBUS_APP_LIGHTING, 28, "bedroom 1 left pendant");
    add_group_label(CBUS_APP_LIGHTING, 29, "bedroom 1 right pendant");
    add_group_label(CBUS_APP_LIGHTING, 30, "bedroom 2 left pendant");
    add_group_label(CBUS_APP_LIGHTING, 31, "bedroom 2 right pendant");
    add_group_label(CBUS_APP_LIGHTING, 32, "kitchen pendant");
    add_group_label(CBUS_APP_LIGHTING, 33, "dining room");
    add_group_label(CBUS_APP_LIGHTING, 34, "bedroom 1 ceiling");
    add_group_label(CBUS_APP_LIGHTING, 35, "bedroom 2 ceiling");
    add_group_label(CBUS_APP_LIGHTING, 36, "bedroom 3 ceiling");
    add_group_label(CBUS_APP_LIGHTING, 37, "bedroom 4 ceiling");
    add_group_label(CBUS_APP_LIGHTING, 38, "staircase ceiling");
    add_group_label(CBUS_APP_LIGHTING, 39, "hallway upstairs");
    add_group_label(CBUS_APP_LIGHTING, 40, "ensuite all");
    add_group_label(CBUS_APP_LIGHTING, 41, "bathroom all");
    add_group_label(CBUS_APP_LIGHTING, 42, "Dummy Group 1");
    add_group_label(202, 0, "Trigger Group 1");
}

// ---- Command throttle queue ----
#define CMD_QUEUE_SIZE 32
static struct {
    uint8_t data[64];
    size_t len;
} cmd_queue[CMD_QUEUE_SIZE];
static uint8_t cmd_queue_head = 0;
static uint8_t cmd_queue_tail = 0;

static bool cmd_queue_empty() { return cmd_queue_head == cmd_queue_tail; }
static bool cmd_queue_full() { return ((cmd_queue_tail + 1) % CMD_QUEUE_SIZE) == cmd_queue_head; }

// ---- Forward declarations ----
static void load_config();
static void save_config();
static void setup_wifi();
static void connect_cni();
static void connect_mqtt();
static void cni_send(const char* data, size_t len);
static void cni_send_str(const char* cmd);
static void pci_reset();
static void process_cni_data();
static void handle_cni_packet(const uint8_t* hex_data, size_t hex_len);
static void publish_ha_discovery(uint8_t app, uint8_t ga);
static void publish_light_state(uint8_t app, uint8_t ga, uint8_t level);
static void mqtt_callback(char* topic, byte* payload, unsigned int length);
static void send_lighting_on(uint8_t app, uint8_t ga);
static void send_lighting_off(uint8_t app, uint8_t ga);
static void send_lighting_ramp(uint8_t app, uint8_t ga, uint8_t level, uint8_t rate);
static void send_timesync();
static void request_all_status();
static void handle_serial_console();
static void start_web_server();
static void setup_mdns();
static uint8_t next_conf_code();
static void send_cbus_command(const uint8_t* packet, size_t pkt_len);
static void process_cmd_queue();
static void enqueue_cbus_command(const uint8_t* packet, size_t pkt_len);

// ---- Helpers for multi-app MQTT topic naming ----
// Default app is 0x38 (56 decimal). For default app, topic uses "cbus_<ga>".
// For other apps, topic uses "cbus_<app_dec>_<ga>" matching cmqttd format.
static void make_topic_id(char* buf, size_t bufsize, uint8_t app, uint8_t ga) {
    if (app == CBUS_APP_LIGHTING) {
        snprintf(buf, bufsize, "cbus_%d", ga);
    } else {
        snprintf(buf, bufsize, "cbus_%d_%d", app, ga);
    }
}

// ============================================================
void setup() {
    Serial.begin(115200);
    while (!Serial) delay(10);
    delay(500);
    Serial.println("\n=== C-Bus ESP32 MQTT Bridge ===");
    Serial.println("Type 'help' for commands.");

    bridge_init(&bridge);
    memset(published, 0, sizeof(published));
    load_default_group_labels();

    load_config();
    setup_wifi();

    // If CNI or MQTT not configured, force AP mode for setup
    if (!ap_mode && (cni_host.length() == 0 || mqtt_host.length() == 0)) {
        Serial.println("CNI or MQTT host not configured. Please configure via web portal.");
        ap_mode = true;
        WiFi.softAP("CBus-Bridge", "cbusbridge");
        Serial.printf("AP IP: %s\n", WiFi.softAPIP().toString().c_str());
        start_web_server();
    }

    if (!ap_mode) {
        // Configure NTP
        configTime(0, 0, "pool.ntp.org");
        setenv("TZ", tz_str.c_str(), 1);
        tzset();
        Serial.printf("NTP configured, TZ=%s\n", tz_str.c_str());

        mqtt.setServer(mqtt_host.c_str(), mqtt_port);
        mqtt.setCallback(mqtt_callback);
        mqtt.setBufferSize(2048);
        connect_cni();
        connect_mqtt();
        setup_mdns();
        start_web_server();
    }

    Serial.println("Bridge ready.");
}

void loop() {
#ifdef CBUS_QEMU_TEST_MODE
    // QEMU test mode unchanged
#else
    handle_serial_console();

    if (web_server) web_server->handleClient();
    if (dns_server) dns_server->processNextRequest();

    if (ap_mode) {
        delay(10);
        return;
    }

    // Maintain CNI connection with backoff
    if (!cni_client.connected()) {
        if (cni_connected) {
            Serial.println("CNI disconnected.");
            cni_connected = false;
            cni_initialized = false;
        }
        if (millis() - last_cni_attempt >= 5000) {
            Serial.println("Attempting CNI reconnect...");
            connect_cni();
        }
    }

    // Maintain MQTT connection with backoff
    if (!mqtt.connected()) {
        if (millis() - last_mqtt_attempt >= 5000) {
            Serial.println("Attempting MQTT reconnect...");
            connect_mqtt();
        }
    }
    mqtt.loop();

    // Process command throttle queue
    process_cmd_queue();

    // Process incoming CNI data
    process_cni_data();

    // Periodic time sync (every 5 minutes)
    if (cni_initialized && millis() - last_timesync > 300000) {
        send_timesync();
        last_timesync = millis();
    }

    // Periodic status request (every 5 minutes)
    if (cni_initialized && millis() - last_status_req > 300000) {
        request_all_status();
        last_status_req = millis();
    }

    delay(1);
#endif
}

// ============================================================
// Configuration
// ============================================================

static void load_config() {
    prefs.begin("cbus", true);
    wifi_ssid = prefs.getString("ssid", "");
    wifi_pass = prefs.getString("pass", "");
    cni_host = prefs.getString("cni_host", "");
    cni_port = prefs.getUShort("cni_port", 10001);
    mqtt_host = prefs.getString("mqtt_host", "");
    mqtt_port = prefs.getUShort("mqtt_port", 1883);
    mqtt_user = prefs.getString("mqtt_user", "");
    mqtt_pass = prefs.getString("mqtt_pass", "");
    tz_str = prefs.getString("tz", "UTC0");
    prefs.end();
    Serial.printf("Config: WiFi='%s' CNI=%s:%d MQTT=%s:%d TZ=%s\n",
        wifi_ssid.c_str(), cni_host.c_str(), cni_port,
        mqtt_host.c_str(), mqtt_port, tz_str.c_str());
}

static void save_config() {
    prefs.begin("cbus", false);
    prefs.putString("ssid", wifi_ssid);
    prefs.putString("pass", wifi_pass);
    prefs.putString("cni_host", cni_host);
    prefs.putUShort("cni_port", cni_port);
    prefs.putString("mqtt_host", mqtt_host);
    prefs.putUShort("mqtt_port", mqtt_port);
    prefs.putString("mqtt_user", mqtt_user);
    prefs.putString("mqtt_pass", mqtt_pass);
    prefs.putString("tz", tz_str);
    prefs.end();
    Serial.println("Config saved.");
}

// ============================================================
// WiFi
// ============================================================

static void setup_wifi() {
    if (wifi_ssid.length() == 0) {
        Serial.println("No WiFi. AP mode: CBus-Bridge / cbusbridge");
        WiFi.softAP("CBus-Bridge", "cbusbridge");
        ap_mode = true;
        start_web_server();
        return;
    }
    Serial.printf("Connecting to %s", wifi_ssid.c_str());
    wifi_pass.length() > 0 ? WiFi.begin(wifi_ssid.c_str(), wifi_pass.c_str())
                           : WiFi.begin(wifi_ssid.c_str());
    for (int i = 0; i < 30 && WiFi.status() != WL_CONNECTED; i++) {
        delay(500); Serial.print(".");
    }
    if (WiFi.status() == WL_CONNECTED) {
        Serial.printf("\nWiFi OK. IP: %s\n", WiFi.localIP().toString().c_str());
        ap_mode = false;
    } else {
        Serial.println("\nWiFi failed. AP mode.");
        WiFi.softAP("CBus-Bridge", "cbusbridge");
        ap_mode = true;
        start_web_server();
    }
}

static void setup_mdns() {
    if (MDNS.begin("cbus-bridge")) {
        MDNS.addService("_cbus", "_tcp", cni_port);
        Serial.println("mDNS: cbus-bridge");
    }
}

// ============================================================
// CNI Connection (TCP client to C-Bus network)
// ============================================================

static void connect_cni() {
    last_cni_attempt = millis();
    Serial.printf("Connecting to CNI %s:%d...", cni_host.c_str(), cni_port);
    if (cni_client.connect(cni_host.c_str(), cni_port)) {
        Serial.println(" OK");
        cni_connected = true;
        cni_buf_len = 0;
        delay(500);
        pci_reset();
    } else {
        Serial.println(" FAILED");
        cni_connected = false;
    }
}

static uint8_t next_conf_code() {
    uint8_t code = CBUS_CONFIRMATION_CODES[conf_idx];
    conf_idx = (conf_idx + 1) % CBUS_CONF_CODE_COUNT;
    return code;
}

static void cni_send(const char* data, size_t len) {
    if (!cni_client.connected()) return;
    cni_client.write((const uint8_t*)data, len);
    cni_client.write('\r');
    delay(100);  // CNI needs pacing
}

static void cni_send_str(const char* cmd) {
    cni_send(cmd, strlen(cmd));
}

static void pci_reset() {
    Serial.println("PCI reset...");
    cni_send_str("~~~"); delay(100);
    cni_send_str("~~~"); delay(100);
    cni_send_str("~~~"); delay(100);
    cni_send_str("|");   delay(100);
    cni_send_str("A32100FF"); delay(100);
    cni_send_str("A32200FF"); delay(100);
    cni_send_str("A342000E"); delay(100);
    cni_send_str("A3300079"); delay(300);

    // Drain any responses
    while (cni_client.available()) cni_client.read();
    cni_initialized = true;
    last_timesync = millis();
    last_status_req = millis();

    // Request initial status
    request_all_status();
    Serial.println("PCI reset complete.");
}

// ============================================================
// CNI Data Processing (C-Bus events from the network)
// ============================================================

static void process_cni_data() {
    while (cni_client.available()) {
        uint8_t b = cni_client.read();
        if (cni_buf_len < sizeof(cni_buf)) {
            cni_buf[cni_buf_len++] = b;
        }
        if (b == 0x0A || b == 0x0D) {
            // Strip CR/LF
            size_t len = cni_buf_len;
            while (len > 0 && (cni_buf[len-1] == 0x0D || cni_buf[len-1] == 0x0A)) len--;
            if (len > 0) {
                handle_cni_packet(cni_buf, len);
            }
            cni_buf_len = 0;
        }
    }
}

static void handle_cni_packet(const uint8_t* data, size_t len) {
    cbus_parsed_packet_t pkt;
    if (!cbus_parse_pci_response(data, len, &pkt)) return;

    switch (pkt.type) {
        case CBUS_PKT_LIGHTING_ON:
            bridge.levels[pkt.group_addr] = 255;
            publish_light_state(pkt.application, pkt.group_addr, 255);
            break;

        case CBUS_PKT_LIGHTING_OFF:
            bridge.levels[pkt.group_addr] = 0;
            publish_light_state(pkt.application, pkt.group_addr, 0);
            break;

        case CBUS_PKT_LIGHTING_RAMP:
            bridge.levels[pkt.group_addr] = pkt.level;
            publish_light_state(pkt.application, pkt.group_addr, pkt.level);
            break;

        case CBUS_PKT_LIGHTING_TERMINATE:
            publish_light_state(pkt.application, pkt.group_addr, bridge.levels[pkt.group_addr]);
            break;

        case CBUS_PKT_STATUS_REQUEST:
            // Level status report - levels are Manchester-decoded by the protocol library
            for (int i = 0; i < pkt.level_count; i++) {
                uint8_t ga = pkt.block_start + i;
                uint8_t level = pkt.level_data[i];
                if (bridge.levels[ga] != level) {
                    bridge.levels[ga] = level;
                    publish_light_state(pkt.child_app, ga, level);
                }
            }
            break;

        default:
            break;
    }
}

// ============================================================
// MQTT
// ============================================================

static void connect_mqtt() {
    if (mqtt.connected()) return;
    last_mqtt_attempt = millis();
    Serial.printf("Connecting to MQTT %s:%d...", mqtt_host.c_str(), mqtt_port);

    bool connected;
    if (mqtt_user.length() > 0) {
        connected = mqtt.connect("cbus-esp32", mqtt_user.c_str(), mqtt_pass.c_str());
    } else {
        connected = mqtt.connect("cbus-esp32");
    }

    if (connected) {
        Serial.println(" OK");

        // Clear published state so discovery is re-sent on reconnect
        memset(published, 0, sizeof(published));

        // Publish discovery only for configured groups (not all 256)
        for (uint8_t i = 0; i < num_configured_groups; i++) {
            publish_ha_discovery(group_labels[i].app, group_labels[i].ga);
        }

        // Publish bridge device
        JsonDocument doc;
        doc["~"] = "homeassistant/binary_sensor/cbus_cmqttd";
        doc["name"] = "cmqttd";
        doc["unique_id"] = "cmqttd";
        doc["stat_t"] = "~/state";
        JsonObject dev = doc["device"].to<JsonObject>();
        dev["identifiers"][0] = "cmqttd";
        dev["sw_version"] = "cbus-esp32 1.0.0";
        dev["name"] = "cmqttd";
        dev["manufacturer"] = "Clipsal";
        dev["model"] = "ESP32 C-Bus Bridge";
        char buf[512];
        serializeJson(doc, buf, sizeof(buf));
        mqtt.publish("homeassistant/binary_sensor/cbus_cmqttd/config", buf, true);
    } else {
        Serial.printf(" FAILED (rc=%d)\n", mqtt.state());
    }
}

static void publish_ha_discovery(uint8_t app, uint8_t ga) {
    if (published[ga]) return;

    // Only publish discovery for configured groups (prevents generic spam)
    const char* label = get_group_label(app, ga);
    if (!label) return;

    published[ga] = true;

    char topic_id[32];
    make_topic_id(topic_id, sizeof(topic_id), app, ga);

    // Canonical unique_id: cbus_light_<ga> (matching old cmqttd format)
    char uid[40], cmd_t[80], stat_t[80], conf_t[80];
    if (app == CBUS_APP_LIGHTING) {
        snprintf(uid, sizeof(uid), "cbus_light_%d", ga);
    } else {
        snprintf(uid, sizeof(uid), "cbus_light_%d_%03d", app, ga);
    }
    snprintf(cmd_t, sizeof(cmd_t), "homeassistant/light/%s/set", topic_id);
    snprintf(stat_t, sizeof(stat_t), "homeassistant/light/%s/state", topic_id);
    snprintf(conf_t, sizeof(conf_t), "homeassistant/light/%s/config", topic_id);

    JsonDocument doc;
    doc["name"] = label;
    doc["unique_id"] = uid;
    doc["cmd_t"] = cmd_t;
    doc["stat_t"] = stat_t;
    doc["schema"] = "json";
    doc["brightness"] = true;
    JsonObject dev = doc["device"].to<JsonObject>();
    dev["identifiers"][0] = uid;
    dev["connections"][0][0] = "cbus_group_address";
    dev["connections"][0][1] = String(ga);
    dev["connections"][1][0] = "cbus_application_address";
    char app_str[8];
    snprintf(app_str, sizeof(app_str), "%d", app);
    dev["connections"][1][1] = app_str;
    dev["sw_version"] = "cbus-esp32 https://github.com/mitchell-johnson/cbus";
    char dev_name[32];
    snprintf(dev_name, sizeof(dev_name), "C-Bus Light %03d", ga);
    dev["name"] = dev_name;
    dev["manufacturer"] = "Clipsal";
    dev["model"] = "C-Bus Lighting Application";
    dev["via_device"] = "cmqttd";

    char buf[768];
    serializeJson(doc, buf, sizeof(buf));
    mqtt.publish(conf_t, buf, true);

    // Subscribe to set topic for this group
    mqtt.subscribe(cmd_t);

    // Also publish binary sensor config with canonical uid
    char bs_conf[80], bs_stat[80], bs_uid[48];
    snprintf(bs_conf, sizeof(bs_conf), "homeassistant/binary_sensor/%s/config", topic_id);
    snprintf(bs_stat, sizeof(bs_stat), "homeassistant/binary_sensor/%s/state", topic_id);
    if (app == CBUS_APP_LIGHTING) {
        snprintf(bs_uid, sizeof(bs_uid), "cbus_bin_sensor_%d", ga);
    } else {
        snprintf(bs_uid, sizeof(bs_uid), "cbus_bin_sensor_%d_%03d", app, ga);
    }

    JsonDocument bs_doc;
    char bs_name[64];
    snprintf(bs_name, sizeof(bs_name), "%s (as binary sensor)", label);
    bs_doc["name"] = bs_name;
    bs_doc["unique_id"] = bs_uid;
    bs_doc["stat_t"] = bs_stat;
    JsonObject bs_dev = bs_doc["device"].to<JsonObject>();
    bs_dev["identifiers"][0] = bs_uid;
    bs_dev["sw_version"] = "cbus-esp32";
    bs_dev["name"] = dev_name;
    bs_dev["manufacturer"] = "Clipsal";
    bs_dev["model"] = "C-Bus Lighting Application";
    bs_dev["via_device"] = "cmqttd";
    serializeJson(bs_doc, buf, sizeof(buf));
    mqtt.publish(bs_conf, buf, true);
}

static void publish_light_state(uint8_t app, uint8_t ga, uint8_t level) {
    if (!mqtt.connected()) return;
    if (!published[ga]) publish_ha_discovery(app, ga);

    char topic_id[32];
    make_topic_id(topic_id, sizeof(topic_id), app, ga);

    char topic[80], bs_topic[80];
    snprintf(topic, sizeof(topic), "homeassistant/light/%s/state", topic_id);
    snprintf(bs_topic, sizeof(bs_topic), "homeassistant/binary_sensor/%s/state", topic_id);

    JsonDocument doc;
    doc["state"] = level > 0 ? "ON" : "OFF";
    doc["brightness"] = level;
    doc["transition"] = 0;
    doc["cbus_source_addr"] = (char*)NULL;

    char buf[128];
    serializeJson(doc, buf, sizeof(buf));
    mqtt.publish(topic, buf, true);

    // Binary sensor
    mqtt.publish(bs_topic, level > 0 ? "ON" : "OFF", true);
}

static void mqtt_callback(char* topic, byte* payload, unsigned int length) {
    // Parse topic: homeassistant/light/cbus_[<app>_]<GA>/set
    // For default app: cbus_<GA>
    // For other apps: cbus_<app>_<GA>
    char* cbus_str = strstr(topic, "cbus_");
    if (!cbus_str) return;
    cbus_str += 5;  // skip "cbus_"
    char* slash = strchr(cbus_str, '/');
    if (!slash) return;

    char id_buf[16];
    size_t id_len = slash - cbus_str;
    if (id_len >= sizeof(id_buf)) return;
    memcpy(id_buf, cbus_str, id_len);
    id_buf[id_len] = '\0';

    // Determine app and GA from the topic ID
    uint8_t app = CBUS_APP_LIGHTING;
    uint8_t ga;
    char* underscore = strchr(id_buf, '_');
    if (underscore) {
        // Format: <app>_<ga>
        *underscore = '\0';
        app = (uint8_t)atoi(id_buf);
        ga = (uint8_t)atoi(underscore + 1);
    } else {
        // Format: <ga> (default app 0x38)
        ga = (uint8_t)atoi(id_buf);
    }

    // Parse JSON payload
    JsonDocument doc;
    DeserializationError err = deserializeJson(doc, payload, length);
    if (err) return;

    const char* state = doc["state"];
    int brightness = doc["brightness"] | 255;
    int transition = doc["transition"] | 0;

    if (!state) return;

    bool light_on = (strcmp(state, "ON") == 0);
    if (light_on) {
        if (brightness == 255 && transition == 0) {
            send_lighting_on(app, ga);
        } else {
            send_lighting_ramp(app, ga, brightness, 0x02);  // instant ramp
        }
        publish_light_state(app, ga, brightness);
    } else {
        send_lighting_off(app, ga);
        publish_light_state(app, ga, 0);
    }
}

// ============================================================
// C-Bus Command Sending (to CNI) with throttling
// ============================================================

static void send_cbus_command(const uint8_t* packet, size_t pkt_len) {
    if (!cni_client.connected()) return;

    // Bounds check to prevent overflow into with_cs[64]
    if (pkt_len > 60) return;

    // Add checksum
    uint8_t with_cs[64];
    memcpy(with_cs, packet, pkt_len);
    with_cs[pkt_len] = cbus_checksum(packet, pkt_len);
    pkt_len++;

    // Hex encode
    char hex[140];
    hex[0] = '\\';
    cbus_hex_encode(with_cs, pkt_len, hex + 1, sizeof(hex) - 3);

    // Add confirmation code
    size_t hex_len = strlen(hex);
    hex[hex_len] = next_conf_code();
    hex[hex_len + 1] = '\0';

    cni_send(hex, strlen(hex));
    last_cni_send = millis();
}

static void enqueue_cbus_command(const uint8_t* packet, size_t pkt_len) {
    if (pkt_len > 60) return;  // Same bounds check
    if (cmd_queue_full()) {
        Serial.println("CMD queue full, dropping command");
        return;
    }
    memcpy(cmd_queue[cmd_queue_tail].data, packet, pkt_len);
    cmd_queue[cmd_queue_tail].len = pkt_len;
    cmd_queue_tail = (cmd_queue_tail + 1) % CMD_QUEUE_SIZE;
}

static void process_cmd_queue() {
    if (cmd_queue_empty()) return;
    if (millis() - last_cni_send < 200) return;  // Throttle: 1 command per 200ms

    send_cbus_command(cmd_queue[cmd_queue_head].data, cmd_queue[cmd_queue_head].len);
    cmd_queue_head = (cmd_queue_head + 1) % CMD_QUEUE_SIZE;
}

static void send_lighting_on(uint8_t app, uint8_t ga) {
    uint8_t pkt[] = {0x05, app, 0x00, 0x79, ga};
    enqueue_cbus_command(pkt, sizeof(pkt));
    bridge.levels[ga] = 255;
}

static void send_lighting_off(uint8_t app, uint8_t ga) {
    uint8_t pkt[] = {0x05, app, 0x00, 0x01, ga};
    enqueue_cbus_command(pkt, sizeof(pkt));
    bridge.levels[ga] = 0;
}

static void send_lighting_ramp(uint8_t app, uint8_t ga, uint8_t level, uint8_t rate) {
    uint8_t pkt[] = {0x05, app, 0x00, rate, ga, level};
    enqueue_cbus_command(pkt, sizeof(pkt));
    bridge.levels[ga] = level;
}

static void send_timesync() {
    // Send current time to C-Bus network (date AND time, matching cmqttd)
    struct tm timeinfo;
    if (!getLocalTime(&timeinfo)) return;

    // Date SAL: 05 DF 00 0D 02 DD MM YY DOW
    // DOW: 0=Sunday per C-Bus spec
    uint8_t date_pkt[] = {
        0x05, 0xDF, 0x00,
        0x0D, CBUS_CLOCK_ATTR_DATE,
        (uint8_t)timeinfo.tm_mday,
        (uint8_t)(timeinfo.tm_mon + 1),
        (uint8_t)(timeinfo.tm_year % 100),
        (uint8_t)timeinfo.tm_wday
    };
    send_cbus_command(date_pkt, sizeof(date_pkt));

    // Time SAL: 05 DF 00 0D 01 HH MM SS FF
    uint8_t time_pkt[] = {
        0x05, 0xDF, 0x00,
        0x0D, CBUS_CLOCK_ATTR_TIME,
        (uint8_t)timeinfo.tm_hour,
        (uint8_t)timeinfo.tm_min,
        (uint8_t)timeinfo.tm_sec,
        0xFF  // DST auto
    };
    send_cbus_command(time_pkt, sizeof(time_pkt));
}

static void request_all_status() {
    // Request level status for all groups in blocks of 32
    for (int block = 0; block < 256; block += 32) {
        uint8_t pkt[] = {0x05, 0xFF, 0x00, 0x73, 0x07, 0x38, (uint8_t)block};
        enqueue_cbus_command(pkt, sizeof(pkt));
    }
}

// ============================================================
// Serial Console
// ============================================================

static String serial_line;

static void handle_serial_console() {
    while (Serial.available()) {
        char c = Serial.read();
        if (c == '\n' || c == '\r') {
            serial_line.trim();
            if (serial_line.length() == 0) { serial_line = ""; continue; }

            if (serial_line.startsWith("wifi ")) {
                String args = serial_line.substring(5);
                int sp = args.indexOf(' ');
                wifi_ssid = sp > 0 ? args.substring(0, sp) : args;
                wifi_pass = sp > 0 ? args.substring(sp + 1) : "";
                save_config();
                Serial.printf("WiFi='%s'. Rebooting...\n", wifi_ssid.c_str());
                delay(1000); ESP.restart();
            }
            else if (serial_line.startsWith("cni ")) {
                String args = serial_line.substring(4);
                int sp = args.indexOf(' ');
                cni_host = sp > 0 ? args.substring(0, sp) : args;
                cni_port = sp > 0 ? args.substring(sp + 1).toInt() : 10001;
                save_config();
                Serial.printf("CNI=%s:%d. Reboot to apply.\n", cni_host.c_str(), cni_port);
            }
            else if (serial_line.startsWith("mqtt ")) {
                String args = serial_line.substring(5);
                int sp = args.indexOf(' ');
                mqtt_host = sp > 0 ? args.substring(0, sp) : args;
                mqtt_port = sp > 0 ? args.substring(sp + 1).toInt() : 1883;
                save_config();
                Serial.printf("MQTT=%s:%d. Reboot to apply.\n", mqtt_host.c_str(), mqtt_port);
            }
            else if (serial_line.startsWith("mqttauth ")) {
                String args = serial_line.substring(9);
                int sp = args.indexOf(' ');
                mqtt_user = sp > 0 ? args.substring(0, sp) : args;
                mqtt_pass = sp > 0 ? args.substring(sp + 1) : "";
                save_config();
                Serial.printf("MQTT auth user='%s'. Reboot to apply.\n", mqtt_user.c_str());
            }
            else if (serial_line.startsWith("tz ")) {
                tz_str = serial_line.substring(3);
                save_config();
                setenv("TZ", tz_str.c_str(), 1);
                tzset();
                Serial.printf("TZ=%s. Applied.\n", tz_str.c_str());
            }
            else if (serial_line == "scan") {
                Serial.println("Scanning...");
                WiFi.scanDelete();
                WiFi.scanNetworks(true, true);
                delay(5000);
                int n = WiFi.scanComplete();
                for (int i = 0; i < n; i++)
                    Serial.printf("  %s (ch%d rssi%d)\n", WiFi.SSID(i).c_str(), WiFi.channel(i), WiFi.RSSI(i));
                Serial.printf("%d networks\n", n > 0 ? n : 0);
                WiFi.scanDelete();
            }
            else if (serial_line == "status") {
                Serial.printf("WiFi: %s IP: %s\n", WiFi.status() == WL_CONNECTED ? "OK" : "DOWN",
                    WiFi.localIP().toString().c_str());
                Serial.printf("CNI: %s:%d %s\n", cni_host.c_str(), cni_port,
                    cni_client.connected() ? "CONNECTED" : "DISCONNECTED");
                Serial.printf("MQTT: %s:%d %s\n", mqtt_host.c_str(), mqtt_port,
                    mqtt.connected() ? "CONNECTED" : "DISCONNECTED");
                Serial.printf("TZ: %s\n", tz_str.c_str());
                Serial.printf("Free heap: %d\n", ESP.getFreeHeap());
                int active = 0;
                for (int i = 0; i < 256; i++) if (bridge.levels[i] > 0) active++;
                Serial.printf("Active groups: %d\n", active);
                int queued = (cmd_queue_tail - cmd_queue_head + CMD_QUEUE_SIZE) % CMD_QUEUE_SIZE;
                Serial.printf("Command queue: %d\n", queued);
            }
            else if (serial_line == "reset") { delay(500); ESP.restart(); }
            else if (serial_line == "factory") {
                prefs.begin("cbus", false); prefs.clear(); prefs.end();
                Serial.println("Factory reset."); delay(500); ESP.restart();
            }
            else if (serial_line == "help") {
                Serial.println("  wifi <ssid> <pass>    - Set WiFi");
                Serial.println("  cni <host> <port>     - Set CNI address");
                Serial.println("  mqtt <host> <port>    - Set MQTT broker");
                Serial.println("  mqttauth <user> <pw>  - Set MQTT credentials");
                Serial.println("  tz <posix_tz>         - Set timezone");
                Serial.println("  scan                  - Scan WiFi");
                Serial.println("  status                - Show status");
                Serial.println("  reset / factory       - Reboot / erase");
            }
            else Serial.printf("Unknown: '%s'\n", serial_line.c_str());
            serial_line = "";
        } else serial_line += c;
    }
}

// ============================================================
// Web Server (both AP mode and normal mode)
// ============================================================

static void handle_web_root();
static void handle_web_config();
static void handle_web_config_save();
static void handle_web_api_status();

static void start_web_server() {
    if (web_server) return;  // Already running
    web_server = new WebServer(80);
    web_server->on("/", HTTP_GET, handle_web_root);
    web_server->on("/config", HTTP_GET, handle_web_config);
    web_server->on("/config", HTTP_POST, handle_web_config_save);
    web_server->on("/api/status", HTTP_GET, handle_web_api_status);

    if (ap_mode) {
        // Captive portal: redirect all unknown URLs to config page
        // This handles the OS captive portal detection probes:
        //   iOS:     /hotspot-detect.html
        //   Android: /generate_204, /connecttest.txt
        //   Windows: /ncsi.txt, /connecttest.txt
        //   macOS:   /hotspot-detect.html
        web_server->onNotFound([]() {
            web_server->sendHeader("Location", "http://192.168.4.1/config", true);
            web_server->send(302, "text/plain", "");
        });

        // Start DNS server to redirect ALL domains to our AP IP
        // This is what makes the captive portal popup appear automatically
        dns_server = new DNSServer();
        dns_server->start(53, "*", WiFi.softAPIP());
        Serial.println("Captive portal DNS started");
    }

    web_server->begin();
    Serial.printf("Web server started on port 80\n");
}

static void handle_web_root() {
    int active = 0;
    for (int i = 0; i < 256; i++) if (bridge.levels[i] > 0) active++;
    int queued = (cmd_queue_tail - cmd_queue_head + CMD_QUEUE_SIZE) % CMD_QUEUE_SIZE;

    struct tm timeinfo;
    char time_buf[32] = "N/A";
    if (getLocalTime(&timeinfo)) {
        strftime(time_buf, sizeof(time_buf), "%Y-%m-%d %H:%M:%S", &timeinfo);
    }

    String html = F(
        "<!DOCTYPE html><html><head>"
        "<meta name='viewport' content='width=device-width,initial-scale=1'>"
        "<title>C-Bus Bridge</title>"
        "<style>"
        "*{box-sizing:border-box;margin:0;padding:0}"
        "body{font-family:-apple-system,system-ui,sans-serif;background:#0f1117;color:#c9d1d9;padding:16px;max-width:600px;margin:0 auto}"
        "h1{color:#58a6ff;margin-bottom:16px;font-size:1.4em}"
        "h2{color:#8b949e;font-size:1em;margin:16px 0 8px;text-transform:uppercase;letter-spacing:1px}"
        ".card{background:#161b22;border:1px solid #30363d;border-radius:8px;padding:16px;margin-bottom:12px}"
        ".row{display:flex;justify-content:space-between;padding:6px 0;border-bottom:1px solid #21262d}"
        ".row:last-child{border-bottom:none}"
        ".label{color:#8b949e}"
        ".val{font-family:monospace}"
        ".ok{color:#3fb950}.err{color:#f85149}"
        "a.btn{display:inline-block;margin-top:16px;padding:10px 20px;background:#1f6feb;color:#fff;text-decoration:none;border-radius:6px;font-weight:600}"
        "a.btn:hover{background:#388bfd}"
        "</style></head><body>"
        "<h1>C-Bus ESP32 Bridge</h1>"
    );

    // Status card
    html += F("<div class='card'><h2>Status</h2>");

    html += F("<div class='row'><span class='label'>WiFi</span><span class='val ");
    html += (WiFi.status() == WL_CONNECTED) ? "ok'>Connected" : "err'>Disconnected";
    html += F("</span></div>");

    html += F("<div class='row'><span class='label'>IP</span><span class='val'>");
    html += WiFi.localIP().toString();
    html += F("</span></div>");

    html += F("<div class='row'><span class='label'>CNI</span><span class='val ");
    html += cni_client.connected() ? "ok'>Connected" : "err'>Disconnected";
    html += F("</span></div>");

    html += F("<div class='row'><span class='label'>CNI Address</span><span class='val'>");
    html += cni_host + ":" + String(cni_port);
    html += F("</span></div>");

    html += F("<div class='row'><span class='label'>MQTT</span><span class='val ");
    html += mqtt.connected() ? "ok'>Connected" : "err'>Disconnected";
    html += F("</span></div>");

    html += F("<div class='row'><span class='label'>MQTT Address</span><span class='val'>");
    html += mqtt_host + ":" + String(mqtt_port);
    html += F("</span></div>");

    html += F("<div class='row'><span class='label'>Active Groups</span><span class='val'>");
    html += String(active);
    html += F("</span></div>");

    html += F("<div class='row'><span class='label'>Command Queue</span><span class='val'>");
    html += String(queued);
    html += F("</span></div>");

    html += F("<div class='row'><span class='label'>Free Heap</span><span class='val'>");
    html += String(ESP.getFreeHeap());
    html += F(" bytes</span></div>");

    html += F("<div class='row'><span class='label'>Time</span><span class='val'>");
    html += time_buf;
    html += F("</span></div>");

    html += F("<div class='row'><span class='label'>Timezone</span><span class='val'>");
    html += tz_str;
    html += F("</span></div>");

    html += F("<div class='row'><span class='label'>Uptime</span><span class='val'>");
    unsigned long uptime_s = millis() / 1000;
    html += String(uptime_s / 3600) + "h " + String((uptime_s % 3600) / 60) + "m " + String(uptime_s % 60) + "s";
    html += F("</span></div>");

    html += F("</div>");

    // Active lights
    html += F("<div class='card'><h2>Active Lights</h2>");
    bool any_active = false;
    for (int i = 0; i < 256; i++) {
        if (bridge.levels[i] > 0) {
            any_active = true;
            html += F("<div class='row'><span class='label'>Group ");
            html += String(i);
            html += F("</span><span class='val'>");
            html += String((bridge.levels[i] * 100) / 255);
            html += F("%</span></div>");
        }
    }
    if (!any_active) {
        html += F("<div class='row'><span class='label'>No active lights</span></div>");
    }
    html += F("</div>");

    html += F("<a class='btn' href='/config'>Configuration</a>");
    html += F("</body></html>");
    web_server->send(200, "text/html", html);
}

static void handle_web_config() {
    // Build the config form populated with current NVS values
    String html = F(
        "<!DOCTYPE html><html><head>"
        "<meta name='viewport' content='width=device-width,initial-scale=1'>"
        "<title>C-Bus Bridge Config</title>"
        "<style>"
        "*{box-sizing:border-box;margin:0;padding:0}"
        "body{font-family:-apple-system,system-ui,sans-serif;background:#0f1117;color:#c9d1d9;padding:16px;max-width:600px;margin:0 auto}"
        "h1{color:#58a6ff;margin-bottom:16px;font-size:1.4em}"
        "h2{color:#8b949e;font-size:1em;margin:16px 0 8px;text-transform:uppercase;letter-spacing:1px}"
        ".card{background:#161b22;border:1px solid #30363d;border-radius:8px;padding:16px;margin-bottom:12px}"
        "label{display:block;margin:12px 0 4px;color:#8b949e;font-size:0.9em}"
        "input[type=text],input[type=password],input[type=number]{"
        "width:100%;padding:10px;background:#0d1117;color:#c9d1d9;border:1px solid #30363d;border-radius:6px;font-size:1em;font-family:monospace}"
        "input:focus{border-color:#58a6ff;outline:none}"
        "button{margin-top:20px;padding:12px 24px;background:#238636;color:#fff;border:none;border-radius:6px;font-weight:600;font-size:1em;cursor:pointer;width:100%}"
        "button:hover{background:#2ea043}"
        "a.back{color:#58a6ff;text-decoration:none;display:inline-block;margin-bottom:12px}"
        ".hint{color:#484f58;font-size:0.8em;margin-top:2px}"
        "</style></head><body>"
        "<a class='back' href='/'>&larr; Back to Status</a>"
        "<h1>Configuration</h1>"
        "<form action='/config' method='POST'>"
    );

    // WiFi section
    html += F("<div class='card'><h2>WiFi</h2>");
    html += F("<label>SSID</label><input type='text' name='ssid' value='");
    html += wifi_ssid;
    html += F("' required>");
    html += F("<label>Password</label><input type='password' name='pass' value='");
    html += wifi_pass;
    html += F("'>");
    html += F("</div>");

    // CNI section
    html += F("<div class='card'><h2>C-Bus CNI</h2>");
    html += F("<label>Host</label><input type='text' name='cni_host' value='");
    html += cni_host;
    html += F("'>");
    html += F("<label>Port</label><input type='number' name='cni_port' value='");
    html += String(cni_port);
    html += F("'>");
    html += F("</div>");

    // MQTT section
    html += F("<div class='card'><h2>MQTT Broker</h2>");
    html += F("<label>Host</label><input type='text' name='mqtt_host' value='");
    html += mqtt_host;
    html += F("'>");
    html += F("<label>Port</label><input type='number' name='mqtt_port' value='");
    html += String(mqtt_port);
    html += F("'>");
    html += F("<label>Username (optional)</label><input type='text' name='mqtt_user' value='");
    html += mqtt_user;
    html += F("'>");
    html += F("<label>Password (optional)</label><input type='password' name='mqtt_pass' value='");
    html += mqtt_pass;
    html += F("'>");
    html += F("</div>");

    // Timezone section
    html += F("<div class='card'><h2>Timezone</h2>");
    html += F("<label>POSIX TZ String</label><input type='text' name='tz' value='");
    html += tz_str;
    html += F("'>");
    html += F("<div class='hint'>e.g. NZST-12NZDT,M9.5.0,M4.1.0/3</div>");
    html += F("</div>");

    html += F("<button type='submit'>Save &amp; Reboot</button>");
    html += F("</form></body></html>");
    web_server->send(200, "text/html", html);
}

static void handle_web_config_save() {
    wifi_ssid = web_server->arg("ssid");
    wifi_pass = web_server->arg("pass");
    cni_host = web_server->arg("cni_host");
    cni_port = web_server->arg("cni_port").toInt();
    mqtt_host = web_server->arg("mqtt_host");
    mqtt_port = web_server->arg("mqtt_port").toInt();
    mqtt_user = web_server->arg("mqtt_user");
    mqtt_pass = web_server->arg("mqtt_pass");
    tz_str = web_server->arg("tz");
    save_config();

    String html = F(
        "<!DOCTYPE html><html><head>"
        "<meta name='viewport' content='width=device-width,initial-scale=1'>"
        "<style>body{font-family:sans-serif;background:#0f1117;color:#c9d1d9;display:flex;justify-content:center;align-items:center;min-height:100vh}"
        "h1{color:#3fb950}</style></head><body>"
        "<h1>Saved! Rebooting...</h1>"
        "</body></html>"
    );
    web_server->send(200, "text/html", html);
    delay(2000);
    ESP.restart();
}

static void handle_web_api_status() {
    int active = 0;
    for (int i = 0; i < 256; i++) if (bridge.levels[i] > 0) active++;
    int queued = (cmd_queue_tail - cmd_queue_head + CMD_QUEUE_SIZE) % CMD_QUEUE_SIZE;

    struct tm timeinfo;
    char time_buf[32] = "";
    if (getLocalTime(&timeinfo)) {
        strftime(time_buf, sizeof(time_buf), "%Y-%m-%dT%H:%M:%S", &timeinfo);
    }

    JsonDocument doc;
    doc["wifi"] = (WiFi.status() == WL_CONNECTED);
    doc["ip"] = WiFi.localIP().toString();
    doc["cni_connected"] = cni_client.connected();
    doc["cni_host"] = cni_host;
    doc["cni_port"] = cni_port;
    doc["mqtt_connected"] = mqtt.connected();
    doc["mqtt_host"] = mqtt_host;
    doc["mqtt_port"] = mqtt_port;
    doc["active_groups"] = active;
    doc["cmd_queue"] = queued;
    doc["free_heap"] = ESP.getFreeHeap();
    doc["uptime_ms"] = millis();
    doc["time"] = time_buf;
    doc["timezone"] = tz_str;

    // Active group levels
    JsonObject levels = doc["levels"].to<JsonObject>();
    for (int i = 0; i < 256; i++) {
        if (bridge.levels[i] > 0) {
            levels[String(i)] = bridge.levels[i];
        }
    }

    char buf[1024];
    serializeJson(doc, buf, sizeof(buf));
    web_server->send(200, "application/json", buf);
}

#endif // PLATFORM_ESP32
