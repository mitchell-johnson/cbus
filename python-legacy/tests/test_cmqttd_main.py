#!/usr/bin/env python
# tests/test_cmqttd_main.py - Tests for cmqttd _main function.
# Copyright 2025 The Gemini Project
#
# This library is free software: you can redistribute it and/or modify
# it under the terms of the GNU Lesser General Public License as published by
# the Free Software Foundation, either version 3 of the License, or
# (at your option) any later version.
#
# This library is distributed in the hope that it will be useful,
# but WITHOUT ANY WARRANTY; without even the implied warranty of
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
# GNU Lesser General Public License for more details.
#
# You should have received a copy of the GNU Lesser General Public License
# along with this library.  If not, see <http://www.gnu.org/licenses/>.

import asyncio
import unittest
from unittest.mock import patch, MagicMock, AsyncMock

from cbus.daemon import cmqttd

class TestCmqttdMain(unittest.TestCase):
    @patch('cbus.daemon.cmqttd.parse_cli_args')
    @patch('cbus.daemon.cmqttd.MqttClient')
    @patch('cbus.daemon.cmqttd.Periodic')
    @patch('cbus.daemon.cmqttd.logger')
    @patch('asyncio.get_event_loop')
    def test_main_exception_handling(self, mock_get_event_loop, mock_logger, mock_periodic, mock_mqtt_client, mock_parse_cli_args):
        # Arrange
        mock_parse_cli_args.return_value = MagicMock(
            tcp='localhost:10001',
            project_file=None,
            verbosity=None,
            log=None,
            cbus_network=None,
            broker_client_cert=None,
            broker_client_key=None,
            broker_disable_tls=False,
            broker_ca=None,
            timesync=300,
            no_clock=False,
        )

        test_exception = Exception("Test Exception")
        
        mock_loop = MagicMock()
        mock_loop.create_connection = AsyncMock(side_effect=test_exception)
        mock_get_event_loop.return_value = mock_loop
        
        mock_periodic_instance = MagicMock()
        mock_periodic_instance.cleanup = AsyncMock()
        mock_periodic.return_value = mock_periodic_instance

        # Act
        asyncio.run(cmqttd._main())

        # Assert
        mock_logger.critical.assert_called_once_with(
            "Unhandled exception: %s", test_exception, exc_info=True
        )
        
        # Ensure cleanup is called
        mock_periodic_instance.cleanup.assert_called_once()

if __name__ == '__main__':
    unittest.main()
