import pytest
from cbus.daemon.cli import build_arg_parser, parse_cli_args


class TestESP32CLIArgs:
    def test_esp32_wifi_option(self):
        args = parse_cli_args([
            '-b', 'localhost',
            '--esp32-wifi', '192.168.1.50:10001',
        ])
        assert args.esp32_wifi == '192.168.1.50:10001'
        assert args.tcp is None

    def test_esp32_serial_option(self):
        args = parse_cli_args([
            '-b', 'localhost',
            '--esp32-serial', '/dev/ttyUSB0',
        ])
        assert args.esp32_serial == '/dev/ttyUSB0'

    def test_esp32_serial_baudrate(self):
        args = parse_cli_args([
            '-b', 'localhost',
            '--esp32-serial', '/dev/ttyUSB0',
            '--esp32-baudrate', '115200',
        ])
        assert args.esp32_baudrate == 115200

    def test_esp32_discover_flag(self):
        args = parse_cli_args([
            '-b', 'localhost',
            '--esp32-discover',
        ])
        assert args.esp32_discover is True

    def test_connection_mutually_exclusive(self):
        """Cannot specify both --tcp and --esp32-wifi."""
        with pytest.raises(SystemExit):
            parse_cli_args([
                '-b', 'localhost',
                '-t', '192.168.1.10:10001',
                '--esp32-wifi', '192.168.1.50',
            ])

    def test_no_connection_method_fails(self):
        """At least one connection method must be given."""
        with pytest.raises(SystemExit):
            parse_cli_args(['-b', 'localhost'])

    def test_tcp_still_works(self):
        args = parse_cli_args([
            '-b', 'localhost',
            '-t', '192.168.1.10:10001',
        ])
        assert args.tcp == '192.168.1.10:10001'

    def test_esp32_reconnect_options(self):
        args = parse_cli_args([
            '-b', 'localhost',
            '--esp32-wifi', '192.168.1.50',
            '--esp32-reconnect-interval', '10',
            '--esp32-max-reconnect', '5',
        ])
        assert args.esp32_reconnect_interval == 10
        assert args.esp32_max_reconnect == 5

    def test_help_shows_esp32_options(self):
        parser = build_arg_parser()
        help_text = parser.format_help()
        assert '--esp32-wifi' in help_text
        assert '--esp32-serial' in help_text
        assert '--esp32-discover' in help_text
        assert '--esp32-baudrate' in help_text
