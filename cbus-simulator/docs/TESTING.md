# Testing the C-Bus Simulator

This document provides guidance on how to test the C-Bus simulator to ensure it correctly implements the C-Bus protocol and behaves like a real C-Bus PCI.

## Manual Testing

### Prerequisites

- Docker and Docker Compose installed
- The simulator running (`docker-compose up -d`)
- A telnet client (e.g., `netcat` or `telnet`)

### Basic Connection Testing

1. Connect to the simulator using a telnet client:
   ```bash
   nc localhost 10001
   ```

2. You should see a `+` prompt, indicating the simulator is in smart mode.

3. Try switching to basic mode:
   ```
   X
   ```

4. You should receive an `OK` response followed by a `>` prompt.

5. Try sending a reset command:
   ```
   ~~~
   ```

6. You should receive an `OK` response followed by the prompt.

### Testing Lighting Commands

1. Turn on a light:
   ```
   3//254A56N1
   ```

2. Request the status of the light:
   ```
   3//254A56G1
   ```

3. You should receive a response indicating the light is on:
   ```
   5//254A56N1
   ```

4. Turn off the light:
   ```
   3//254A56F1
   ```

5. Request the status again:
   ```
   3//254A56G1
   ```

6. You should receive a response indicating the light is off:
   ```
   5//254A56F1
   ```

### Testing Command Confirmation

1. Send a lighting command with confirmation requested:
   ```
   #3//254A56N1
   ```

2. You should receive a confirmation response like:
   ```
   .
   80+
   ```

3. The confirmation code (80 in this example) may vary.

### Testing Identify Commands

1. Send an identify command to get the interface type:
   ```
   #3//254I0A0
   ```

2. You should receive a response like:
   ```
   .
   80+
   5//254IC0A0="5500CN"
   ```

## Testing with libcbus

You can also test the simulator with the actual libcbus library to verify compatibility.

### Prerequisites

- Python 3.7 or later
- libcbus installed
- The simulator running

### Configuration

1. Create a test script `test_simulator.py`:
   ```python
   #!/usr/bin/env python3
   import asyncio
   from cbus.protocol.pciprotocol import PCIProtocol
   
   async def main():
       # Connect to the simulator
       loop = asyncio.get_running_loop()
       _, protocol = await loop.create_connection(
           lambda: PCIProtocol(),
           'localhost', 10001
       )
       
       # Wait for connection to establish
       await asyncio.sleep(1)
       
       # Turn on group 1
       print("Turning on group 1...")
       await protocol.lighting_group_on(1, 56)
       
       # Wait for command to process
       await asyncio.sleep(1)
       
       # Turn off group 1
       print("Turning off group 1...")
       await protocol.lighting_group_off(1, 56)
       
       # Wait for command to process
       await asyncio.sleep(1)
       
       # Close the connection
       transport = protocol._transport
       transport.close()
   
   if __name__ == "__main__":
       asyncio.run(main())
   ```

2. Run the test script:
   ```bash
   python test_simulator.py
   ```

3. You should see output indicating the commands were sent and processed.

## Automated Testing

The simulator includes automated tests to verify functionality. Run them as follows:

1. Make sure the simulator is not already running.

2. Run the automated tests:
   ```bash
   cd cbus-simulator
   docker-compose run --rm cbus-simulator python -m unittest discover -s tests
   ```

3. The tests will validate various aspects of the simulator:
   - Protocol parsing
   - Command handling
   - State management
   - Response generation

## Testing with External Tools

You can also use third-party tools to test the simulator:

### Using MQTT Bridge

1. Configure the MQTT bridge (`cmqttd`) to connect to the simulator:
   ```
   CNI_ADDR=localhost:10001
   ```

2. Start the MQTT bridge and observe the logs for connection and command processing.

### Using Home Assistant

1. Configure Home Assistant to use the MQTT bridge with the simulator.

2. Test controlling lights through the Home Assistant interface.

## Performance Testing

To test the simulator's performance under load:

1. Create a script that sends a high volume of commands:
   ```python
   #!/usr/bin/env python3
   import asyncio
   import time
   
   async def send_commands(host, port, count):
       reader, writer = await asyncio.open_connection(host, port)
       
       start_time = time.time()
       for i in range(count):
           cmd = f"3//254A56N{i % 10 + 1}\r\n"
           writer.write(cmd.encode())
           await writer.drain()
           
           # Read response
           _ = await reader.readuntil(b'+\r\n')
       
       elapsed = time.time() - start_time
       writer.close()
       await writer.wait_closed()
       
       return elapsed
   
   async def main():
       host = 'localhost'
       port = 10001
       command_count = 1000
       
       print(f"Sending {command_count} commands...")
       elapsed = await send_commands(host, port, command_count)
       
       print(f"Sent {command_count} commands in {elapsed:.2f} seconds")
       print(f"Average: {command_count / elapsed:.2f} commands per second")
   
   if __name__ == "__main__":
       asyncio.run(main())
   ```

2. Run the performance test:
   ```bash
   python performance_test.py
   ```

3. Analyze the results to ensure the simulator can handle the expected load.

## Troubleshooting

If you encounter issues during testing:

1. Check the simulator logs:
   ```bash
   docker-compose logs
   ```

2. Verify your command syntax against the C-Bus protocol documentation.

3. Ensure the simulator is properly configured.

4. Try resetting the simulator:
   ```
   ~~~
   ```

5. Restart the simulator container:
   ```bash
   docker-compose restart
   ```

## Next Steps

After testing, you might want to:

1. Customize the simulator configuration for your specific needs.
2. Extend the simulator with additional application support.
3. Integrate the simulator into your CI/CD pipeline for automated testing of C-Bus applications. 