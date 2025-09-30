# cmqttd Configuration Files

This folder contains optional configuration files for the C-Bus MQTT daemon (cmqttd).

## Configuration Files

### project.cbz
**Type:** File
**Purpose:** Provides C-Bus group labels and project metadata.

Create a backup of your C-Bus project using the C-Bus Toolkit software, then copy the backup file to this folder and rename it to `project.cbz`.

### auth
**Type:** File
**Purpose:** MQTT broker authentication credentials.

Contains username and password to connect to an MQTT broker, separated by a newline character:
```
username
password
```

If this file is not present, cmqttd will attempt to connect to the MQTT broker without authentication.

### certificates/
**Type:** Directory
**Purpose:** CA certificates for TLS connections.

Contains CA certificates to trust when connecting with TLS. If this directory is not present, the default Python CA store will be used.

### client.pem & client.key
**Type:** Files
**Purpose:** Client certificate authentication.

- `client.pem`: Client certificate for MQTT broker authentication
- `client.key`: Private key corresponding to the client certificate

Both files are required for certificate-based authentication.

