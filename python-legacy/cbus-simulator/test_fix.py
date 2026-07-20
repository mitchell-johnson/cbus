#!/usr/bin/env python3
import logging
import sys

# Set up logging
logging.basicConfig(level=logging.DEBUG, format='%(asctime)s - %(name)s - %(levelname)s - %(message)s')
logger = logging.getLogger('test-fix')

# Add the current directory to the path
sys.path.insert(0, '.')

# Import the functions
from simulator.protocol import preprocess_cbus_data
from simulator import parse_command, parse_binary_command

# Test data - the problematic message format
test_data = b'\\05380079024x'

# Test the preprocessing function
logger.info("Testing preprocess_cbus_data...")
result = preprocess_cbus_data(test_data)
if isinstance(result, bytearray):
    logger.info(f"Preprocessing successful: {' '.join(f'{b:02X}' for b in result)}")
else:
    logger.error(f"Preprocessing failed: {result}")

# Test the parsing function
logger.info("Testing parse_command...")
response = parse_command(test_data, {})
logger.info(f"Parse command response: {response}")

# Test with a modified version that might be missing the leading backslash
test_data2 = b'05380079024x'
logger.info("Testing with modified data (no leading backslash)...")
response2 = parse_command(test_data2, {})
logger.info(f"Parse command response: {response2}")

# Test with the original problematic string from the error message
test_data3 = bytes([0x5C, 0x30, 0x35, 0x33, 0x38, 0x30, 0x30, 0x37, 0x39, 0x30, 0x32, 0x34, 0x38, 0x78])
logger.info("Testing with original problematic bytes...")
logger.info(f"Original bytes: {' '.join(f'{b:02X}' for b in test_data3)}")
logger.info(f"Decoded as ASCII: {test_data3.decode('ascii')}")
response3 = parse_command(test_data3, {})
logger.info(f"Parse command response: {response3}")

logger.info("Tests completed.") 