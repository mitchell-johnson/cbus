//! CLI parity with `cbus/daemon/cli.py` (argparse-compatible subset).

use clap::{ArgGroup, Parser};

#[derive(Parser, Debug, Clone)]
#[command(name = "cmqttd", about = "MQTT connector for C-Bus (Rust port)")]
#[command(group(ArgGroup::new("conn").required(true).args(["tcp", "esp32_wifi", "esp32_serial"])))]
pub struct Options {
    /// Enable debug logging
    #[arg(short = 'd', long)]
    pub debug: bool,

    // Logging options ------------------------------------------------------
    /// Destination to write logs
    #[arg(short = 'l', long = "log-file")]
    pub log: Option<String>,

    /// Verbosity to emit
    #[arg(short = 'v', long, default_value = "INFO",
          value_parser = ["CRITICAL", "ERROR", "WARNING", "INFO", "DEBUG"])]
    pub verbosity: String,

    // MQTT options ---------------------------------------------------------
    /// Address of the MQTT broker
    #[arg(short = 'b', long)]
    pub broker_address: String,

    /// Port to use; 0 = auto (8883 TLS / 1883 plain)
    #[arg(short = 'p', long, default_value_t = 0)]
    pub broker_port: u16,

    /// MQTT keep-alive in seconds
    #[arg(long, default_value_t = 60)]
    pub broker_keepalive: u16,

    /// Disable TLS (insecure)
    #[arg(long)]
    pub broker_disable_tls: bool,

    /// File containing username and password (2 lines)
    #[arg(short = 'A', long)]
    pub broker_auth: Option<String>,

    /// CA certificate file (or directory of PEM files); default: system
    /// trust store
    #[arg(short = 'c', long)]
    pub broker_ca: Option<String>,

    /// PEM client certificate
    #[arg(short = 'k', long)]
    pub broker_client_cert: Option<String>,

    /// PEM client key (private)
    #[arg(short = 'K', long)]
    pub broker_client_key: Option<String>,

    // C-Bus connection (exactly one required) ------------------------------
    /// IP address and TCP port of CNI/PCI (eg 192.168.1.10:10001)
    #[arg(short = 't', long)]
    pub tcp: Option<String>,

    /// ESP32 C-Bus bridge WiFi address (eg 192.168.1.50[:10001])
    #[arg(long)]
    pub esp32_wifi: Option<String>,

    /// ESP32 C-Bus bridge serial port (eg /dev/ttyUSB0)
    /// (`--serial` accepted for Docker entrypoint compatibility)
    #[arg(long, alias = "serial")]
    pub esp32_serial: Option<String>,

    // ESP32 options --------------------------------------------------------
    /// Serial baud rate for ESP32 connection
    #[arg(long, default_value_t = 9600)]
    pub esp32_baudrate: u32,

    /// Seconds between reconnect attempts
    #[arg(long, default_value_t = 5)]
    pub esp32_reconnect_interval: u64,

    /// Max reconnect attempts (0 = unlimited)
    #[arg(long, default_value_t = 0)]
    pub esp32_max_reconnect: u32,

    // Time settings --------------------------------------------------------
    /// Send time synchronisation every n seconds (0 to disable)
    #[arg(short = 'T', long, default_value_t = 300)]
    pub timesync: u64,

    /// Do not respond to Clock Request SAL messages
    #[arg(short = 'C', long)]
    pub no_clock: bool,

    /// Request status updates every n seconds (parsed, unused — like Python)
    #[arg(short = 'S', long, default_value_t = 300)]
    pub status_resync: u64,

    // Label options --------------------------------------------------------
    /// Path to a C-Bus Toolkit project backup (.cbz or .xml)
    #[arg(short = 'P', long)]
    pub project_file: Option<String>,

    /// Name of the C-Bus network to use (may be multiple words)
    #[arg(short = 'N', long, num_args = 0..)]
    pub cbus_network: Vec<String>,
}
