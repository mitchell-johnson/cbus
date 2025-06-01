#!/usr/bin/env python3
"""
Test script to monitor raw C-Bus events from CNI
This will help diagnose why physical switch presses aren't being reported
"""

import asyncio
import logging
from datetime import datetime
from cbus.protocol.pciprotocol import PCIProtocol

# Enable detailed logging
logging.basicConfig(
    level=logging.DEBUG,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)

class TestCBusMonitor(PCIProtocol):
    """Test monitor that logs all C-Bus events"""
    
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.event_count = 0
        self.start_time = datetime.now()
    
    def handle_cbus_packet(self, p):
        """Log all incoming packets"""
        self.event_count += 1
        print(f"\n{'='*60}")
        print(f"EVENT #{self.event_count} at {datetime.now().strftime('%H:%M:%S.%f')[:-3]}")
        print(f"Packet Type: {type(p).__name__}")
        print(f"Raw Packet: {p!r}")
        print(f"{'='*60}\n")
        
        # Call parent handler
        super().handle_cbus_packet(p)
    
    def on_lighting_group_on(self, source_addr, group_addr, app_addr):
        print(f">>> LIGHT ON: Source={source_addr}, Group={group_addr}, App={app_addr}")
        super().on_lighting_group_on(source_addr, group_addr, app_addr)
    
    def on_lighting_group_off(self, source_addr, group_addr, app_addr):
        print(f">>> LIGHT OFF: Source={source_addr}, Group={group_addr}, App={app_addr}")
        super().on_lighting_group_off(source_addr, group_addr, app_addr)
    
    def on_lighting_group_ramp(self, source_addr, group_addr, app_addr, duration, level):
        print(f">>> LIGHT RAMP: Source={source_addr}, Group={group_addr}, App={app_addr}, Duration={duration}, Level={level}")
        super().on_lighting_group_ramp(source_addr, group_addr, app_addr, duration, level)
    
    def on_mmi(self, application, data):
        print(f">>> MMI EVENT: Application={application}, Data={data!r}")
        super().on_mmi(application, data)
    
    def on_confirmation(self, code, success):
        print(f">>> CONFIRMATION: Code={ord(code)} (0x{ord(code):02X}), Success={success}")
        super().on_confirmation(code, success)
    
    def connection_made(self, transport):
        print(f"\n{'*'*60}")
        print(f"CONNECTED TO CNI at {datetime.now()}")
        print(f"{'*'*60}\n")
        print("Monitoring for C-Bus events...")
        print("Press physical switches to test if events are received.")
        print("Press Ctrl+C to stop.\n")
        super().connection_made(transport)
    
    def connection_lost(self, exc):
        print(f"\n{'*'*60}")
        print(f"CONNECTION LOST: {exc}")
        print(f"Total events received: {self.event_count}")
        print(f"Duration: {datetime.now() - self.start_time}")
        print(f"{'*'*60}\n")
        super().connection_lost(exc)

async def main():
    # Get CNI address from command line or use default
    import sys
    
    if len(sys.argv) > 1:
        cni_addr = sys.argv[1]
    else:
        cni_addr = "192.168.1.227:10001"
    
    print(f"Connecting to CNI at {cni_addr}")
    
    # Parse address and port
    if ':' in cni_addr:
        host, port = cni_addr.split(':', 1)
        port = int(port)
    else:
        host = cni_addr
        port = 10001
    
    # Create connection
    loop = asyncio.get_event_loop()
    connection_lost_future = loop.create_future()
    
    def factory():
        return TestCBusMonitor(connection_lost_future=connection_lost_future)
    
    try:
        transport, protocol = await loop.create_connection(factory, host, port)
        
        # Wait for connection to be lost
        await connection_lost_future
        
    except KeyboardInterrupt:
        print("\nStopped by user")
    except Exception as e:
        print(f"\nError: {e}")

if __name__ == '__main__':
    asyncio.run(main()) 