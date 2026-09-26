# Multi-stage build for the Rust C-Bus tools.
FROM rust:1.92-alpine AS builder
RUN apk add --no-cache musl-dev pkgconfig
WORKDIR /build
COPY rust/ /build/
RUN cargo build --release -p cmqttd -p cbus-tools -p cbus-simulator -p cbus-cgate

FROM alpine:3.20 AS cmqttd
RUN apk add --no-cache tzdata ca-certificates sqlite-libs sqlite libxslt
COPY COPYING COPYING.LESSER README.md entrypoint-cmqttd.sh /
RUN sed -i 's/\r$//' /entrypoint-cmqttd.sh && chmod +x /entrypoint-cmqttd.sh
COPY --from=builder /build/target/release/cmqttd /usr/local/bin/cmqttd
COPY --from=builder /build/target/release/cbus-tools /usr/local/bin/cbus-tools
COPY --from=builder /build/target/release/cbus-simulator /usr/local/bin/cbus-simulator
COPY --from=builder /build/target/release/cgate-mock /usr/local/bin/cgate-mock
COPY cmqttd_config/ /etc/cmqttd/

ENV PATH="/usr/local/bin:${PATH}"
CMD ["/entrypoint-cmqttd.sh"]
