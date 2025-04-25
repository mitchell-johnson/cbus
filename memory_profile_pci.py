#!/usr/bin/env python
"""
Memory profiling script for PCIProtocol
This script patches the PCIProtocol methods to track memory usage,
helping identify potential memory leaks.
"""

import tracemalloc
import asyncio
import logging
import sys
import gc
import time
from datetime import datetime
from functools import wraps
import socket

from cbus.protocol.pciprotocol import PCIProtocol

# Configure logging - increase to DEBUG level
logging.basicConfig(level=logging.DEBUG, 
                   format='%(asctime)s %(levelname)s %(name)s - %(message)s')
logger = logging.getLogger("memory_profiler")

# Dictionary to track object counts by type
object_counts = {}
memory_snapshots = []

def profile_memory(func):
    """Decorator to profile memory before and after function calls"""
    @wraps(func)
    async def wrapper(*args, **kwargs):
        # Collect garbage to get accurate memory readings
        gc.collect()
        
        # Record memory before
        before = tracemalloc.get_traced_memory()[0]
        
        # Call the original function
        result = await func(*args, **kwargs)
        
        # Collect garbage again
        gc.collect()
        
        # Record memory after
        after = tracemalloc.get_traced_memory()[0]
        diff = after - before
        
        if diff > 1024:  # Only log if memory increased by more than 1KB
            logger.info(f"Memory {func.__name__}: {diff/1024:.2f} KB")
            
            # Take snapshot if significant increase
            if diff > 10240:  # Over 10KB increase
                snapshot = tracemalloc.take_snapshot()
                timestamp = datetime.now().strftime("%H:%M:%S")
                memory_snapshots.append((timestamp, snapshot, func.__name__))
                logger.info(f"Saved memory snapshot after {func.__name__}")
        
        return result
    return wrapper

async def monitor_memory(interval=5):
    """Monitor memory usage periodically"""
    while True:
        gc.collect()  # Force garbage collection
        current, peak = tracemalloc.get_traced_memory()
        logger.info(f"Current memory usage: {current/1024/1024:.2f} MB; Peak: {peak/1024/1024:.2f} MB")
        
        # Track object counts for key types
        counts = {
            "dict": 0,
            "bytearray": 0,
            "list": 0,
            "PCIProtocol": 0,
            "Future": 0,
            "Lock": 0,
            "Task": 0,
        }
        
        # Count all objects in memory
        for obj in gc.get_objects():
            obj_type = type(obj).__name__
            if obj_type in counts:
                counts[obj_type] += 1
        
        # Log changes in object counts
        global object_counts
        if object_counts:
            for obj_type, count in counts.items():
                prev_count = object_counts.get(obj_type, 0)
                if count != prev_count:
                    logger.info(f"{obj_type} count: {count} (changed by {count - prev_count})")
        else:
            # First run, just log all counts
            for obj_type, count in counts.items():
                logger.info(f"{obj_type} count: {count}")
        
        # Update object counts
        object_counts = counts
        
        # Take and save a snapshot every 10 intervals
        if len(memory_snapshots) % 10 == 0:
            snapshot = tracemalloc.take_snapshot()
            timestamp = datetime.now().strftime("%H:%M:%S")
            memory_snapshots.append((timestamp, snapshot, "periodic"))
            
        await asyncio.sleep(interval)

def patch_pci_protocol():
    """Patch key methods of PCIProtocol with memory profiling"""
    # List of methods to patch
    methods_to_patch = [
        '_send',
        '_prepare_packet',
        '_send_packet',
        '_get_confirmation_code',
        'on_confirmation',
        '_release_confirmation_code',
        '_check_and_release_timed_out_codes',
        '_check_pending_confirmations',
        '_remove_from_pending_confirmations'
    ]
    
    # Apply patches
    for method_name in methods_to_patch:
        if hasattr(PCIProtocol, method_name) and callable(getattr(PCIProtocol, method_name)):
            original_method = getattr(PCIProtocol, method_name)
            patched_method = profile_memory(original_method)
            setattr(PCIProtocol, method_name, patched_method)
            logger.info(f"Patched {method_name} method with memory profiling")

async def save_memory_comparison(interval=60):
    """Periodically compare memory snapshots to identify leaks"""
    snapshot_dir = "memory_snapshots"
    import os
    
    # Create directory if it doesn't exist
    if not os.path.exists(snapshot_dir):
        os.makedirs(snapshot_dir)
    
    while True:
        await asyncio.sleep(interval)
        
        if len(memory_snapshots) >= 2:
            # Get oldest and newest snapshot
            oldest_time, oldest, oldest_func = memory_snapshots[0]
            newest_time, newest, newest_func = memory_snapshots[-1]
            
            # Compare snapshots
            logger.info(f"Comparing snapshots from {oldest_time} to {newest_time}")
            
            # Save top differences to file
            filename = f"{snapshot_dir}/memory_diff_{int(time.time())}.txt"
            with open(filename, 'w') as f:
                f.write(f"Memory comparison: {oldest_time} to {newest_time}\n")
                f.write(f"Oldest snapshot after: {oldest_func}\n")
                f.write(f"Newest snapshot after: {newest_func}\n\n")
                
                f.write("Top memory differences by line:\n")
                top_stats = newest.compare_to(oldest, 'lineno')
                for stat in top_stats[:20]:
                    f.write(f"{stat}\n")
                    
                f.write("\nTop memory differences by file:\n")
                file_stats = newest.compare_to(oldest, 'filename')
                for stat in file_stats[:10]:
                    f.write(f"{stat}\n")
                
            logger.info(f"Saved memory comparison to {filename}")

async def test_connection(host, port, timeout=5):
    """Test if we can connect to the host and port"""
    logger.debug(f"Testing connection to {host}:{port}...")
    try:
        # Set a timeout to avoid hanging
        socket.setdefaulttimeout(timeout)
        sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        result = sock.connect_ex((host, port))
        if result == 0:
            logger.debug(f"Successfully connected to {host}:{port}")
            sock.close()
            return True
        else:
            logger.error(f"Could not connect to {host}:{port}, error code: {result}")
            sock.close()
            return False
    except Exception as e:
        logger.error(f"Error testing connection to {host}:{port}: {e}")
        return False

async def main():
    """Run the PCI protocol with memory tracking"""
    # Start tracking memory allocations
    tracemalloc.start(25)  # Track 25 frames
    logger.info("Memory tracking started")
    
    # Parse command line arguments first to validate connection
    if len(sys.argv) < 3:
        print("Usage: python memory_profile_pci.py [--tcp ADDRESS:PORT | --serial DEVICE]")
        return
        
    # Test connection for TCP mode
    if sys.argv[1] == "--tcp" or sys.argv[1] == "-t":
        try:
            addr_port = sys.argv[2]
            logger.debug(f"Parsing address and port from: {addr_port}")
            addr, port_str = addr_port.split(':', 2)
            port = int(port_str)
            
            # Test connection before proceeding
            connection_ok = await test_connection(addr, port)
            if not connection_ok:
                print(f"Connection test failed. Please check if {addr}:{port} is accessible.")
                print("You can try with a different address or use the simulator.")
                return
        except ValueError as e:
            logger.error(f"Invalid address format: {e}")
            print("Invalid format. Use ADDRESS:PORT format, e.g., 192.168.1.21:10001")
            return
    
    # Patch PCIProtocol methods
    patch_pci_protocol()
    
    # Start memory monitoring task
    monitor_task = asyncio.create_task(monitor_memory())
    
    # Start memory comparison task
    comparison_task = asyncio.create_task(save_memory_comparison())
    
    # Create connection lost future
    loop = asyncio.get_running_loop()
    connection_lost_future = loop.create_future()
    
    # Create the protocol
    protocol = PCIProtocol(connection_lost_future=connection_lost_future)
    
    try:
        if sys.argv[1] == "--tcp" or sys.argv[1] == "-t":
            addr, port = sys.argv[2].split(':', 2)
            port = int(port)
            logger.info(f"Connecting to TCP {addr}:{port}...")
            transport, proto = await loop.create_connection(
                lambda: protocol, addr, port)
            logger.info(f"Connected to TCP {addr}:{port}")
        elif sys.argv[1] == "--serial" or sys.argv[1] == "-s":
            from serial_asyncio import create_serial_connection
            logger.info(f"Connecting to serial {sys.argv[2]}...")
            transport, proto = await create_serial_connection(
                loop, lambda: protocol, sys.argv[2], baudrate=9600)
            logger.info(f"Connected to serial {sys.argv[2]}")
        else:
            print("Invalid option. Use --tcp or --serial")
            return
        
        logger.info("Connection established, waiting for events...")
        
        # Wait for the connection to be closed
        await connection_lost_future
        
    except ConnectionRefusedError:
        logger.error(f"Connection refused. Make sure the device is running and accessible.")
    except KeyboardInterrupt:
        logger.info("Interrupted by user")
    except Exception as e:
        logger.error(f"Error: {e}", exc_info=True)
    finally:
        # Cancel monitoring tasks
        logger.info("Cleaning up...")
        monitor_task.cancel()
        comparison_task.cancel()
        try:
            await asyncio.gather(monitor_task, comparison_task, return_exceptions=True)
        except asyncio.CancelledError:
            pass
            
        # Save final memory snapshot
        snapshot = tracemalloc.take_snapshot()
        timestamp = datetime.now().strftime("%H:%M:%S")
        memory_snapshots.append((timestamp, snapshot, "final"))
        
        # Save final comparison
        snapshot_dir = "memory_snapshots"
        import os
        if not os.path.exists(snapshot_dir):
            os.makedirs(snapshot_dir)
            
        filename = f"{snapshot_dir}/memory_final_{int(time.time())}.txt"
        if len(memory_snapshots) >= 2:
            oldest_time, oldest, oldest_func = memory_snapshots[0]
            with open(filename, 'w') as f:
                f.write(f"Final memory comparison: {oldest_time} to {timestamp}\n\n")
                f.write("Top memory differences by line:\n")
                top_stats = snapshot.compare_to(oldest, 'lineno')
                for stat in top_stats[:30]:
                    f.write(f"{stat}\n")
        
        logger.info("Memory profiling complete")

if __name__ == "__main__":
    asyncio.run(main()) 