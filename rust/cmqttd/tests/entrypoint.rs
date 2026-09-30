//! The container entrypoint must preserve environment values literally and
//! select TLS consistently under POSIX /bin/sh. The executable is a stub: no
//! broker, serial device or C-Bus endpoint is contacted.
#![cfg(unix)]

use std::os::unix::fs::PermissionsExt;
use std::path::PathBuf;
use std::process::Command;

struct Fixture(PathBuf);

impl Fixture {
    fn new() -> Self {
        let path = cbus_test_support::proc::temp_path("entrypoint");
        std::fs::create_dir_all(&path).unwrap();
        let executable = path.join("cmqttd");
        std::fs::write(
            &executable,
            "#!/bin/sh\nprintf 'CMQTTD_ARGS_BEGIN\\000'\nprintf '%s\\000' \"$@\"\n",
        )
        .unwrap();
        std::fs::set_permissions(&executable, std::fs::Permissions::from_mode(0o700)).unwrap();
        // Make glob expansion detectable.
        std::fs::write(path.join("unexpected-expansion"), b"").unwrap();
        Self(path)
    }

    fn run(&self, env: &[(&str, &str)]) -> Vec<String> {
        let script = PathBuf::from(env!("CARGO_MANIFEST_DIR")).join("../../entrypoint-cmqttd.sh");
        let output = Command::new("/bin/sh")
            .arg(script)
            .current_dir(&self.0)
            .env_clear()
            .env("PATH", format!("{}:/usr/bin:/bin", self.0.display()))
            .env("MQTT_SERVER", "127.0.0.1")
            .env("CNI_ADDR", "127.0.0.1:10001")
            .envs(env.iter().copied())
            .output()
            .unwrap();
        assert!(output.status.success(), "{output:?}");
        let marker = b"CMQTTD_ARGS_BEGIN\0";
        let begin = output
            .stdout
            .windows(marker.len())
            .position(|window| window == marker)
            .expect("stub must run")
            + marker.len();
        output.stdout[begin..]
            .split(|byte| *byte == 0)
            .filter(|arg| !arg.is_empty())
            .map(|arg| String::from_utf8(arg.to_vec()).unwrap())
            .collect()
    }
}

impl Drop for Fixture {
    fn drop(&mut self) {
        std::fs::remove_dir_all(&self.0).ok();
    }
}

#[test]
fn environment_values_do_not_split_expand_or_inject_flags() {
    let fixture = Fixture::new();
    let args = fixture.run(&[
        ("MQTT_SERVER", "broker --broker-disable-tls"),
        ("SERIAL_PORT", "/dev/serial/by-id/C-Bus PCI *"),
        ("CMQTTD_CBUS_NETWORK", "Ground * Floor --no-clock"),
    ]);
    for (flag, value) in [
        ("--broker-address", "broker --broker-disable-tls"),
        ("--serial", "/dev/serial/by-id/C-Bus PCI *"),
    ] {
        let index = args.iter().position(|arg| arg == flag).unwrap();
        assert_eq!(args[index + 1], value);
    }
    assert!(!args.iter().any(|arg| arg == "--broker-disable-tls"));
    assert!(!args.iter().any(|arg| arg == "--no-clock"));
    assert!(args
        .iter()
        .any(|arg| arg == "--cbus-network=Ground * Floor --no-clock"));
    // --cbus-network accepts zero values, so a leading dash needs the = form
    // even when shell quoting already preserves the value as one argument.
    let args = fixture.run(&[("CMQTTD_CBUS_NETWORK", "--broker-disable-tls")]);
    assert!(args
        .iter()
        .any(|arg| arg == "--cbus-network=--broker-disable-tls"));
    assert!(!args.iter().any(|arg| arg == "--broker-disable-tls"));
}

#[test]
fn tls_defaults_on_and_is_disabled_only_when_requested() {
    let fixture = Fixture::new();
    let enabled = fixture.run(&[]);
    assert!(!enabled.iter().any(|arg| arg == "--broker-disable-tls"));
    let disabled = fixture.run(&[("MQTT_USE_TLS", "0")]);
    assert!(disabled.iter().any(|arg| arg == "--broker-disable-tls"));
}
