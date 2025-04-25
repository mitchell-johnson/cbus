#!/usr/bin/env python3
import unittest
import sys
import logging
import sys
import os

# Add the parent directory to the path so we can import the simulator
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))
from simulator import preprocess_cbus_data, parse_binary_command, parse_command

# Set up logging to see what's happening during tests
logging.basicConfig(level=logging.DEBUG, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger('cbus-test')

class CBusSimulatorTest(unittest.TestCase):
    """Tests for the C-Bus Simulator protocol handling"""
    
    def setUp(self):
        # Mock config for tests
        self.mock_config = {
            "networks": [
                {
                    "network_id": 254,
                    "applications": [
                        {
                            "application_id": 56,
                            "type": "lighting",
                            "groups": [
                                {"group_id": 1, "name": "Living Room"},
                                {"group_id": 2, "name": "Kitchen"}
                            ]
                        }
                    ]
                }
            ]
        }
    
    def test_preprocess_cbus_data_hex_string(self):
        """Test preprocessing of C-Bus hex string data"""
        # Typical C-Bus initialization command
        input_data = b'\\05DF000E0207E90415000D010F3720FF90h\r'
        result = preprocess_cbus_data(input_data)
        
        # Check if it's a bytearray and has correct length
        self.assertIsInstance(result, bytearray)
        
        # Should have multiple bytes (not just one)
        self.assertGreater(len(result), 1)
        
        # First byte should be 0x05
        self.assertEqual(result[0], 0x05)
        
        # Second byte should be 0xDF (init command)
        self.assertEqual(result[1], 0xDF)
        
        # Log the complete result for inspection
        logger.info(f"Processed data: {' '.join(f'{b:02X}' for b in result)}")
    
    def test_preprocess_cbus_data_lighting_command(self):
        """Test preprocessing of C-Bus lighting command"""
        # Lighting command
        input_data = b'\\05FF00730738004Ai\r'
        result = preprocess_cbus_data(input_data)
        
        self.assertIsInstance(result, bytearray)
        self.assertGreater(len(result), 5)
        self.assertEqual(result[0], 0x05)  # Leading byte
        self.assertEqual(result[1], 0xFF)  # Command type
        
        # Log the complete result for inspection
        logger.info(f"Lighting command: {' '.join(f'{b:02X}' for b in result)}")
    
    def test_parse_binary_command_init(self):
        """Test parsing a binary initialization command"""
        input_data = b'\\05DF000E0207E90415000D010F3720FF90h\r'
        processed = preprocess_cbus_data(input_data)
        result = parse_binary_command(processed, self.mock_config)
        
        # Response should be a byte string
        self.assertIsInstance(result, bytes)
        
        # First byte should be 0x05
        self.assertEqual(result[0], 0x05)
        
        # For init command, second byte should be 0x86 (ACK)
        self.assertEqual(result[1], 0x86)
        
        logger.info(f"Init command response: {' '.join(f'{b:02X}' for b in result)}")
    
    def test_parse_binary_command_lighting(self):
        """Test parsing a binary lighting command"""
        input_data = b'\\05FF00730738004Ai\r'
        processed = preprocess_cbus_data(input_data)
        result = parse_binary_command(processed, self.mock_config)
        
        # Response should be a byte string
        self.assertIsInstance(result, bytes)
        
        # First byte should be 0x05
        self.assertEqual(result[0], 0x05)
        
        # For lighting command, check inclusion of confirmation code
        self.assertGreater(len(result), 8)
        
        logger.info(f"Lighting command response: {' '.join(f'{b:02X}' for b in result)}")
    
    def test_end_to_end_binary_command(self):
        """Test the full parse_command flow with binary data"""
        input_data = b'\\05DF000E0207E90415000D010F3720FF90h\r'
        result = parse_command(input_data, self.mock_config)
        
        # Response should be a byte string
        self.assertIsInstance(result, bytes)
        
        logger.info(f"End-to-end command response: {' '.join(f'{b:02X}' for b in result)}")
    
    def test_text_command(self):
        """Test parsing a text command"""
        input_data = b'group 1 level 75'
        result = parse_command(input_data, self.mock_config)
        
        # Response should be a byte string
        self.assertIsInstance(result, bytes)
        
        # Decode and check expected text response
        decoded = result.decode('utf-8')
        self.assertIn("OK", decoded)
        self.assertIn("group 1", decoded)
        self.assertIn("75", decoded)
        
        logger.info(f"Text command response: {decoded}")

if __name__ == '__main__':
    unittest.main() 