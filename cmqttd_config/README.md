# Optional cmqttd files

Files in this directory are copied to `/etc/cmqttd` by the Docker image. Sensitive and site-specific files are ignored by Git.

- `project.cbz`: optional C-Bus project backup used for network, application, and group labels.
- `auth`: optional MQTT username on the first line and password on the second line.
- `certificates/`: optional PEM CA certificates for the MQTT broker.
- `client.pem` and `client.key`: optional MQTT client certificate and private key.

Without a project file, `cmqttd` generates labels from C-Bus addresses. Without custom CA files, TLS uses the operating system trust store.
