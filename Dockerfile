# This Dockerfile sets up cmqttd, which bridges a C-Bus PCI to a MQTT server.
#
# This requires about 120 MiB of dependencies, and the
# The final image size is about 100 MiB.
#
# Example use:
#
# $ docker build -t cmqttd .
# $ docker run --device /dev/ttyUSB0 -e "SERIAL_PORT=/dev/ttyUSB0" \
#     -e "MQTT_SERVER=192.2.0.1" -e "TZ=Australia/Adelaide" -it cmqttd
FROM python:3.11.9-alpine3.19 as base
# python 3.10 required, at date this file is created only available in alpine:edge

# Install most Python deps here, because that way we don't need to include build tools in the
# final image.
RUN apk add --no-cache python3 py-pip py3-cffi py3-paho-mqtt py3-six tzdata python3-dev && \
    pip3 install --break-system-packages 'pyserial==3.5' 'pyserial_asyncio==0.6'

# Builds a distribution tarball
FROM base as builder
# See also .dockerignore
ADD . /cbus
WORKDIR /cbus
RUN pip3 install --break-system-packages 'parameterized' && \
    python3 setup.py bdist -p generic --format=gztar

# cmqttd runner image
FROM base as cmqttd
COPY COPYING COPYING.LESSER Dockerfile README.md entrypoint-cmqttd.sh /
RUN sed -i 's/\r$//' entrypoint-cmqttd.sh 
COPY --from=builder /cbus/dist/cbus-0.2.generic.tar.gz /
RUN tar zxf /cbus-0.2.generic.tar.gz && rm /cbus-0.2.generic.tar.gz
COPY cmqttd_config/ /etc/cmqttd/ 

# Fix auth directory and project file issues
RUN rm -rf /etc/cmqttd/auth && touch /etc/cmqttd/auth && \
    if [ -d /etc/cmqttd/project.cbz ]; then rm -rf /etc/cmqttd/project.cbz && touch /etc/cmqttd/project.cbz; fi

# Ensure project file exists
COPY cmqttd_config/project.cbz /etc/cmqttd/project.cbz

# Runs cmqttd itself
CMD ["/entrypoint-cmqttd.sh"]
