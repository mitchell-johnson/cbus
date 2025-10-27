# libcbus Troubleshooting Guide

This guide helps diagnose and resolve common issues with libcbus.

---

## Table of Contents

1. [Connection Issues](#connection-issues)
2. [MQTT Problems](#mqtt-problems)
3. [Command Failures](#command-failures)
4. [Performance Issues](#performance-issues)
5. [Docker Issues](#docker-issues)
6. [Debugging Tools](#debugging-tools)

---

## Connection Issues

### Cannot Connect to CNI/PCI

**Symptoms:**
- "Connection refused" error
- "Connection timeout" error
- Application hangs on startup

**Possible Causes:**

#### 1. Wrong IP Address/Port

**Check:**
```bash
# Ping the CNI
ping 192.168.1.100

# Check if port is open
telnet 192.168.1.100 10001
# or
nc -zv 192.168.1.100 10001
```

**Solution:**
- Verify CNI IP address using C-Bus Toolkit
- Default port is usually 10001
- Check firewall rules on both client and CNI

#### 2. Serial Port Permission Issues

**Symptoms:**
- "Permission denied" when accessing /dev/ttyUSB0

**Check:**
```bash
ls -l /dev/ttyUSB0
# Should show: crw-rw---- 1 root dialout ...
```

**Solution:**
```bash
# Add your user to dialout group
sudo usermod -a -G dialout $USER

# Log out and back in, or:
newgrp dialout

# Verify:
groups | grep dialout
```

#### 3. Serial Port Already in Use

**Check:**
```bash
lsof /dev/ttyUSB0
```

**Solution:**
- Close other applications using the port
- Kill the process if needed:
  ```bash
  kill <PID>
  ```

#### 4. CNI Not Configured

**For Ethernet PCI (5500CN):**
- CNI must be configured with C-Bus Toolkit first
- Verify it has an IP address
- Ensure network settings allow TCP connections

### Connection Drops Frequently

**Symptoms:**
- "Connection lost" messages in logs
- Intermittent command failures

**Possible Causes:**

#### 1. Network Issues

**Check:**
```bash
# Monitor packet loss
ping -c 100 192.168.1.100 | grep loss

# Check network latency
ping 192.168.1.100
```

**Solution:**
- Fix network issues (bad cables, Wi-Fi interference)
- Use wired connection instead of Wi-Fi
- Check for network loops or broadcast storms

#### 2. CNI Overloaded

**Symptoms:**
- Slow responses
- Confirmation timeouts
- Connection resets

**Solution:**
- Reduce command rate (increase throttle period)
- Reduce status request frequency
- Check for other devices flooding the C-Bus network

#### 3. Power Issues

**Check:**
- CNI power supply is adequate
- C-Bus power supply voltage (15V DC nominal)

### Serial Connection Not Working

**Symptoms:**
- No response from PCI
- Garbled data

**Check:**
```bash
# Test serial port
screen /dev/ttyUSB0 9600

# or use minicom
minicom -D /dev/ttyUSB0 -b 9600
```

**Solution:**
- Verify baud rate is 9600
- Check cable is not damaged
- Ensure USB-serial adapter driver is loaded:
  ```bash
  lsmod | grep cp210x
  # If not loaded:
  sudo modprobe cp210x
  ```

---

## MQTT Problems

### Cannot Connect to MQTT Broker

**Symptoms:**
- "Connection refused" to MQTT broker
- cmqttd exits immediately

**Check:**
```bash
# Test MQTT connection
mosquitto_sub -h mqtt.example.com -p 8883 -t test/#
```

**Solution:**

#### 1. Wrong Broker Address

- Verify `MQTT_SERVER` in `.env`
- Check port (1883 for plain, 8883 for TLS)

#### 2. Authentication Issues

- Verify username/password if required
- Check broker logs for authentication failures

#### 3. TLS Issues

**Check Certificate:**
```bash
openssl s_client -connect mqtt.example.com:8883 -showcerts
```

**Solution:**
- Ensure CA certificate is valid
- Check certificate hostname matches broker hostname
- For self-signed certificates, provide CA file:
  ```bash
  cmqttd --broker-ca /path/to/ca.crt ...
  ```

### Messages Not Appearing in Home Assistant

**Symptoms:**
- cmqttd running but no devices in HA
- Commands don't control lights

**Check:**

#### 1. MQTT Integration Enabled

In Home Assistant:
- Configuration → Integrations → MQTT
- Should show "Connected"

#### 2. Auto-Discovery Enabled

Check MQTT integration configuration:
```yaml
mqtt:
  discovery: true
  discovery_prefix: homeassistant
```

#### 3. Topic Permissions

**Check broker ACL:**
```bash
# Subscribe to auto-discovery topic
mosquitto_sub -h broker -t 'homeassistant/#' -v

# Should see messages like:
# homeassistant/light/cbus_1/config {"name": "C-Bus Light 1", ...}
```

**Solution:**
- Ensure cmqttd has permission to publish to `homeassistant/*`
- Check broker ACL configuration

#### 4. Retained Messages

Old/stale messages might interfere:

```bash
# Clear retained messages
mosquitto_pub -h broker -t 'homeassistant/light/cbus_1/config' -r -n

# Restart cmqttd to republish
```

### MQTT Commands Not Reaching C-Bus

**Symptoms:**
- HA shows light state changes but C-Bus doesn't respond
- cmqttd logs show no incoming messages

**Check:**

#### 1. Subscription

Look for subscription confirmation in logs:
```
Subscribed to 'homeassistant/light/#'
```

#### 2. Topic Format

Commands should go to:
```
homeassistant/light/cbus_<GA>/set
```

Verify with:
```bash
mosquitto_sub -h broker -t 'homeassistant/light/+/set' -v
```

#### 3. Payload Format

Payload must be valid JSON:
```json
{"state": "ON", "brightness": 255}
```

Test manually:
```bash
mosquitto_pub -h broker -t 'homeassistant/light/cbus_1/set' \
  -m '{"state": "ON", "brightness": 255}'
```

---

## Command Failures

### Lights Don't Respond to Commands

**Symptoms:**
- Commands sent but lights don't change
- No error messages

**Check:**

#### 1. Confirmation Failures

Enable DEBUG logging:
```bash
export CMQTTD_VERBOSITY=DEBUG
cmqttd ...
```

Look for:
```
ERROR: Confirmation code 0x68 timed out
WARNING: Giving up on confirmation code 0x68 after 3 attempts
```

**Solution:**
- Check C-Bus network wiring
- Verify group addresses are correct
- Check if C-Bus network is overloaded

#### 2. Wrong Group Address

**Verify group addresses:**
```bash
# Use C-Bus Toolkit to scan network
# or check CBZ file:
cbz_dump_labels your-project.cbz
```

**Solution:**
- Update `.env` with correct project file
- Verify `CMQTTD_CBUS_NETWORK` setting

#### 3. Wrong Application Address

**Default is 0x38 (LIGHTING), but you might need a different one:**
- 0x30-0x5F are valid lighting applications
- Check with Toolkit which application your devices use

### Commands Work But State Not Updated

**Symptoms:**
- Can control lights
- Home Assistant shows wrong state
- Binary sensors not updating

**Check:**

#### 1. Status Requests

cmqttd sends status requests on startup. Check logs:
```
DEBUG: Sending status request for block 0
DEBUG: Sending status request for block 32
...
```

**Solution:**
- Ensure status requests are enabled
- Check devices support status queries
- Some C-Bus units don't respond to status requests

#### 2. Event Reception

Check if events are received:
```
DEBUG: recv: light on: from 10 to 1, application 56
```

**Solution:**
- Verify PCI is in MONITOR mode (should be set during init)
- Check interface options in logs

### "Too Many Pending Confirmations" Warning

**Symptoms:**
- Warning in logs: "High number of pending confirmations"
- Commands slow down or fail

**Cause:**
- Sending commands faster than CNI can process
- CNI not responding with confirmations

**Solution:**

#### 1. Increase Throttle Period

In code:
```python
throttler = Periodic(period=0.5)  # Increase from 0.2 to 0.5
```

Or reduce command rate in your application.

#### 2. Check CNI Health

- Restart CNI
- Check C-Bus network load
- Verify CNI firmware is up to date

---

## Performance Issues

### High Latency

**Symptoms:**
- Commands take several seconds to execute
- Slow response to button presses

**Check:**

#### 1. Network Latency

```bash
ping 192.168.1.100
# Should be <10ms for local network
```

**Solution:**
- Fix network issues
- Use wired connection
- Reduce network load

#### 2. Throttle Too Aggressive

```bash
# Check logs for:
DEBUG: Throttler delaying command by 0.5s
```

**Solution:**
- Reduce throttle period if network can handle it:
  ```python
  Periodic(period=0.1)  # Faster
  ```

#### 3. Too Many Status Requests

**Solution:**
- Reduce status request frequency
- Only request status for configured groups

### High Memory Usage

**Symptoms:**
- cmqttd memory usage grows over time
- System becomes sluggish

**Check:**
```bash
# Monitor memory usage
ps aux | grep cmqttd

# or use top/htop
```

**Possible Causes:**

#### 1. Memory Leak

Known issue: pending confirmations not cleaned up properly.

**Workaround:**
- Restart cmqttd periodically
- Monitor for confirmation timeout warnings

#### 2. Too Many Subscriptions

**Solution:**
- Limit which groups are published to MQTT
- Use labels file to only publish configured groups

### High CPU Usage

**Symptoms:**
- cmqttd using significant CPU
- System slow

**Check:**
```bash
top -p $(pgrep -f cmqttd)
```

**Possible Causes:**

#### 1. Busy Loop

Check logs for repeated errors or tight loops.

#### 2. Too Many Commands

Reduce command rate.

---

## Docker Issues

### Container Won't Start

**Check logs:**
```bash
docker logs cmqttd
```

**Common Issues:**

#### 1. Invalid Environment Variables

**Check `.env` file:**
```bash
cat .env
```

Ensure all required variables are set:
- `MQTT_SERVER`
- `CNI_ADDR`
- `TZ`

#### 2. Port Conflicts

**Check if port is in use:**
```bash
netstat -tlnp | grep 10001
```

#### 3. Permission Issues

**For serial devices:**
```bash
# Check device permissions
ls -l /dev/ttyUSB0

# Add to docker-compose.yml:
devices:
  - /dev/ttyUSB0:/dev/ttyUSB0
privileged: true  # or specific capabilities
```

### Can't Reach CNI from Container

**Check networking:**
```bash
# Enter container
docker exec -it cmqttd /bin/bash

# Test connectivity
ping 192.168.1.100
telnet 192.168.1.100 10001
```

**Solution:**

#### 1. Use Host Network

In `docker-compose.yml`:
```yaml
network_mode: host
```

#### 2. Check Bridge Configuration

Ensure container can reach host network:
```bash
docker network inspect bridge
```

### Changes to `.env` Not Taking Effect

**Solution:**
```bash
# Restart container
docker-compose down
docker-compose up -d

# Or rebuild
docker-compose up -d --build
```

---

## Debugging Tools

### Enable Debug Logging

**Environment variable:**
```bash
export CMQTTD_VERBOSITY=DEBUG
```

**Docker:**
```yaml
environment:
  - CMQTTD_VERBOSITY=DEBUG
```

**Python code:**
```python
import logging
logging.basicConfig(level=logging.DEBUG)
```

### Use the Protocol Proxy

Intercept and analyze all C-Bus communication:

```bash
cd cbus-proxy
python proxy.py \
  --listen-port 10002 \
  --target-host 192.168.1.100 \
  --target-port 10001
```

Then connect cmqttd to `localhost:10002`.

**Proxy shows:**
- Raw packet bytes
- Decoded packet structure
- Confirmation codes
- Timing information

### Monitor MQTT Traffic

```bash
# Subscribe to all topics
mosquitto_sub -h broker -t '#' -v

# Subscribe to C-Bus topics only
mosquitto_sub -h broker -t 'homeassistant/light/cbus_+/#' -v

# Monitor commands
mosquitto_sub -h broker -t 'homeassistant/light/+/set' -v
```

### Test with Simulator

No hardware needed:

```bash
# Terminal 1: Start simulator
cd cbus-simulator
python -m simulator.run_simulator --host 127.0.0.1 --port 10001

# Terminal 2: Test connection
export CMQTTD_VERBOSITY=DEBUG
python -m cbus.protocol.pciprotocol -t 127.0.0.1:10001
```

### Packet Decoder

Decode raw C-Bus packets:

```bash
cbus_decode_packet '\05380079640D'
```

### Python Debugger

Add breakpoint in code:
```python
import pdb; pdb.set_trace()
```

Or use remote debugger:
```python
import debugpy
debugpy.listen(5678)
debugpy.wait_for_client()
```

---

## Common Error Messages

### "PCI cannot accept data"

**Meaning:** PCI rejected the command

**Causes:**
- Checksum error
- PCI buffer full
- Invalid command

**Solution:**
- Reduce command rate
- Check for packet corruption
- Verify cable quality

### "All confirmation codes are in use"

**Meaning:** All 20 confirmation codes are pending

**Causes:**
- Commands sent too fast
- CNI not responding
- Confirmation timeout too long

**Solution:**
- Reduce command rate
- Check CNI connectivity
- Restart cmqttd

### "JSON parse error"

**Meaning:** Invalid MQTT payload received

**Cause:**
- Client sent malformed JSON

**Solution:**
- Check client code
- Validate JSON before sending:
  ```bash
  echo '{"state": "ON"}' | jq .
  ```

### "Connection lost: [Errno 104] Connection reset by peer"

**Meaning:** CNI closed the connection

**Causes:**
- CNI restart
- Network issue
- CNI overloaded

**Solution:**
- Check CNI health
- Enable auto-reconnect (built-in)
- Investigate CNI logs if available

---

## Getting More Help

If this guide doesn't resolve your issue:

1. **Collect Debugging Information:**
   ```bash
   # Get version info
   python --version
   pip show cbus

   # Get full debug log
   export CMQTTD_VERBOSITY=DEBUG
   cmqttd ... > debug.log 2>&1

   # System info
   uname -a
   ```

2. **Search Existing Issues:**
   - https://github.com/mitchell-johnson/cbus/issues

3. **Open New Issue:**
   - Include debug log
   - Describe expected vs actual behavior
   - List steps to reproduce
   - Specify hardware (PCI model, C-Bus devices)

4. **Contact Maintainers:**
   - mitchell@johnson.fyi

---

**End of Troubleshooting Guide**
