//! Command-line arguments for the C-Bus MQTT bridge.

use clap::{ArgGroup, Parser};

#[derive(Parser, Debug, Clone)]
#[command(name = "cmqttd", about = "MQTT connector for C-Bus")]
#[command(group(ArgGroup::new("conn").required(true).args(["tcp", "esp32_wifi", "esp32_serial", "esp32_discover"])))]
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

    /// Auto-discover an ESP32 C-Bus bridge via mDNS (_cbus._tcp)
    #[arg(long)]
    pub esp32_discover: bool,

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

    /// Request status updates every n seconds (0 to disable)
    #[arg(short = 'S', long, default_value_t = 300)]
    pub status_resync: u64,

    // Label options --------------------------------------------------------
    /// Path to a C-Bus project backup (.cbz or .xml)
    #[arg(short = 'P', long)]
    pub project_file: Option<String>,

    /// Name of the C-Bus network to use (may be multiple words)
    #[arg(short = 'N', long, num_args = 0..)]
    pub cbus_network: Vec<String>,

    /// Enable the embedded C-Gate TCP service at this bind address
    #[arg(long, requires = "project_file")]
    pub cgate_bind: Option<String>,

    /// Atomic C-Gate database; keep this on a persistent volume
    #[arg(long, default_value = "cmqttd-data/cgate.json")]
    pub cgate_state: std::path::PathBuf,

    /// Optional vendor unit specification directory for PP schemas
    #[arg(long)]
    pub cgate_unitspec: Option<std::path::PathBuf>,

    /// PEM certificate chain enabling TLS on the embedded C-Gate
    /// listener; requires --cgate-tls-key (no auth yet — keep the bind
    /// on loopback unless TLS termination is understood)
    #[arg(long, requires = "cgate_bind", requires = "cgate_tls_key")]
    pub cgate_tls_cert: Option<std::path::PathBuf>,

    /// PEM private key (PKCS#8/RSA/EC) enabling TLS on the embedded
    /// C-Gate listener; requires --cgate-tls-cert
    #[arg(long, requires = "cgate_bind", requires = "cgate_tls_cert")]
    pub cgate_tls_key: Option<std::path::PathBuf>,

    /// Optional file holding a high-entropy C-Gate LOGIN token (first
    /// line); arms the session-local LOGIN gate over programming verbs.
    /// Loopback-only first slice: NOT native access.txt parity. Fails
    /// closed at startup when missing/unreadable/too short, or (on unix)
    /// accessible by group/other — expect 0400 or 0600 permissions.
    #[arg(long, requires = "cgate_bind")]
    pub cgate_auth_file: Option<std::path::PathBuf>,
}

#[cfg(test)]
mod tests {
    use super::*;
    use clap::Parser;

    fn base_args() -> Vec<&'static str> {
        vec![
            "cmqttd",
            "-b",
            "127.0.0.1",
            "-t",
            "127.0.0.1:10001",
            "-P",
            "proj.cbz",
            "--cgate-bind",
            "127.0.0.1:0",
        ]
    }

    #[test]
    fn cgate_tls_flags_default_to_plaintext() {
        let opts = Options::try_parse_from(base_args()).expect("parse");
        assert!(opts.cgate_tls_cert.is_none());
        assert!(opts.cgate_tls_key.is_none());
        assert!(opts.cgate_auth_file.is_none());
    }

    #[test]
    fn cgate_tls_cert_requires_key() {
        let mut args = base_args();
        args.push("--cgate-tls-cert");
        args.push("cert.pem");
        assert!(Options::try_parse_from(args).is_err());
    }

    #[test]
    fn cgate_tls_key_requires_cert() {
        let mut args = base_args();
        args.push("--cgate-tls-key");
        args.push("key.pem");
        assert!(Options::try_parse_from(args).is_err());
    }

    #[test]
    fn cgate_tls_pair_parses() {
        let mut args = base_args();
        args.push("--cgate-tls-cert");
        args.push("cert.pem");
        args.push("--cgate-tls-key");
        args.push("key.pem");
        let opts = Options::try_parse_from(args).expect("parse");
        assert!(opts.cgate_tls_cert.is_some());
        assert!(opts.cgate_tls_key.is_some());
    }

    fn base_args_without_bind() -> Vec<&'static str> {
        vec![
            "cmqttd",
            "-b",
            "127.0.0.1",
            "-t",
            "127.0.0.1:10001",
            "-P",
            "proj.cbz",
        ]
    }

    #[test]
    fn cgate_tls_pair_without_bind_rejected() {
        let mut args = base_args_without_bind();
        args.push("--cgate-tls-cert");
        args.push("cert.pem");
        args.push("--cgate-tls-key");
        args.push("key.pem");
        assert!(Options::try_parse_from(args).is_err());
    }

    #[test]
    fn cgate_tls_cert_without_bind_rejected() {
        let mut args = base_args_without_bind();
        args.push("--cgate-tls-cert");
        args.push("cert.pem");
        assert!(Options::try_parse_from(args).is_err());
    }

    #[test]
    fn cgate_tls_key_without_bind_rejected() {
        let mut args = base_args_without_bind();
        args.push("--cgate-tls-key");
        args.push("key.pem");
        assert!(Options::try_parse_from(args).is_err());
    }

    #[test]
    fn cgate_auth_file_defaults_to_none_and_requires_bind() {
        let opts = Options::try_parse_from(base_args()).expect("parse");
        assert!(opts.cgate_auth_file.is_none());
        let mut args = base_args();
        args.push("--cgate-auth-file");
        args.push("cgate.token");
        let opts = Options::try_parse_from(args).expect("parse with bind");
        assert!(opts.cgate_auth_file.is_some());
        let mut args = base_args_without_bind();
        args.push("--cgate-auth-file");
        args.push("cgate.token");
        assert!(Options::try_parse_from(args).is_err());
    }
}
