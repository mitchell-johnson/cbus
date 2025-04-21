#!/usr/bin/env python3
import socket
import time
import logging
import binascii

# Configure logging
logging.basicConfig(
    level=logging.DEBUG,
    format='%(asctime)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger('cbus-client-test')

# Test configuration
HOST = 'localhost'
PORT = 10002  # Updated port for local testing
TEST_COMMANDS = [
    # Initialization command
    b'\x05\xDF\x00\x0E\x02\x07\xE9\x04\x15\x00\x0D\x01\x0F\x37\x20\xFF\x90',
    # Lighting commands for different groups
    b'\x05\xFF\x00\x73\x07\x38\x00\x4A\x69',
    b'\x05\xFF\x00\x73\x07\x38\x20\x2A\x6A',
    b'\x05\xFF\x00\x73\x07\x38\x40\x0A\x6B',
    # Text commands
    b'group 1 level 75',
    b'group 2 level 100'
]

def send_command(sock, command):
    """Send a command to the simulator and get response"""
    # For binary commands, we need to encode with backslashes for C-Bus protocol
    if command[0] == 0x05:  # Binary command starts with 0x05
        # Convert to hex string with backslashes
        if command[1] == 0xDF:  # Initialization command format
            hex_command = '\\05' + ''.join(f'{b:02X}' for b in command[1:]) + 'h\r'
            send_data = hex_command.encode('ascii')
            logger.info(f"Sending initialization command: {binascii.hexlify(command).decode()}")
        else:  # Lighting command format
            hex_command = '\\05' + ''.join(f'{b:02X}' for b in command[1:]) + 'i\r'
            send_data = hex_command.encode('ascii')
            logger.info(f"Sending lighting command: {binascii.hexlify(command).decode()}")
        logger.info(f"Encoded as: {send_data}")
    else:
        # Text command
        send_data = command
        logger.info(f"Sending text command: {send_data}")
    
    sock.sendall(send_data)
    
    # Get response
    response = sock.recv(1024)
    
    # Try to decode as text, otherwise show as hex
    try:
        decoded = response.decode('utf-8')
        logger.info(f"Response (text): {decoded}")
    except UnicodeDecodeError:
        logger.info(f"Response (binary): {binascii.hexlify(response).decode()}")
    
    return response

def run_test():
    """Run all test commands against local simulator"""
    try:
        # Connect to simulator
        sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        sock.connect((HOST, PORT))
        logger.info(f"Connected to simulator at {HOST}:{PORT}")
        
        # Run each test command
        for i, command in enumerate(TEST_COMMANDS):
            logger.info(f"==== Test {i+1} ====")
            response = send_command(sock, command)
            time.sleep(0.5)  # Small delay between commands
        
        sock.close()
        logger.info("Test completed successfully")
        
    except ConnectionRefusedError:
        logger.error(f"Could not connect to simulator at {HOST}:{PORT}. Is it running?")
    except Exception as e:
        logger.error(f"Error during testing: {e}")

if __name__ == "__main__":
    run_test() 