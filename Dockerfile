# Multi-stage build for the Rust cmqttd (C-Bus <-> MQTT bridge).
#
# The legacy Python image lives in Dockerfile.python until cutover.
#
# Example use:
#
# $ docker build -t cmqttd .
# $ docker run -e "MQTT_SERVER=192.2.0.1" -e "CNI_ADDR=192.2.0.2:10001" \
#     -e "TZ=Australia/Adelaide" -it cmqttd

FROM rust:1.92-alpine AS builder
RUN apk add --no-cache musl-dev pkgconfig
WORKDIR /build
COPY rust/ /build/
RUN cargo build --release --workspace

FROM alpine:3.20 AS cmqttd
# ca-certificates: system trust store for TLS without --broker-ca
RUN apk add --no-cache tzdata ca-certificates
COPY COPYING COPYING.LESSER README.md entrypoint-cmqttd.sh /
RUN sed -i 's/\r$//' /entrypoint-cmqttd.sh && chmod +x /entrypoint-cmqttd.sh
COPY --from=builder /build/target/release/cmqttd /usr/local/bin/cmqttd
COPY --from=builder /build/target/release/cbus-tools /usr/local/bin/cbus-tools
COPY --from=builder /build/target/release/cbus-simulator /usr/local/bin/cbus-simulator
COPY cmqttd_config/ /etc/cmqttd/

# Fix auth directory and project file issues (parity with the Python image)
RUN rm -rf /etc/cmqttd/auth && touch /etc/cmqttd/auth && \
    if [ -d /etc/cmqttd/project.cbz ]; then rm -rf /etc/cmqttd/project.cbz && touch /etc/cmqttd/project.cbz; fi
COPY cmqttd_config/project.cbz /etc/cmqttd/project.cbz

# The entrypoint invokes `cmqttd`; the Rust binary is CLI-compatible with
# the Python daemon, so the existing entrypoint script works unchanged.
ENV PATH="/usr/local/bin:${PATH}"
CMD ["/entrypoint-cmqttd.sh"]
