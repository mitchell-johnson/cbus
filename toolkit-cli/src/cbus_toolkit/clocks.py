"""Native network clock outcomes, including per-unit failures before final200.

Clock summaries are IDENTIFY16 observations reported by C-Gate's dz/bJ code.
Recovery enables the gateway; it does not request a network-wide count of1.
No command is retried, and transport failures prevent further I/O.
"""
from dataclasses import dataclass
import re

from .cgate import CGateError, CGateResponse
from .native import _token
from .networks import NativeNetworks


MAX_LINES = 2048
MAX_RESPONSE_BYTES = 1024 * 1024
MAX_LINE_BYTES = 8192
_PREFIX = re.compile(r'^([1-6][0-9]{2})[- ](.*)$')
_FIELD = re.compile(r'([a-z_]+)=([0-9]{1,3})')
_FAIL_SUMMARY = re.compile(r'^Failed to obtain output unit summary from address ([0-9]{1,3})\.$')
_FAIL_CHANGE = re.compile(r'^(?:First clock|Clock|Master clock) at address ([0-9]{1,3}) could NOT be (enabled|disabled): (.*)$')
_GATEWAY = re.compile(r'^Gateway clock at address ([0-9]{1,3}) is now enabled\.$')


class ClockParseError(RuntimeError):
    def __init__(self, message, response, rows=(), messages=()):
        self.response = response
        self.rows = tuple(rows)
        self.messages = tuple(messages)
        super().__init__(message)


@dataclass(frozen=True)
class ClockUnit:
    address: int
    output_units: int
    clocks_enabled: int | None = None
    clocks_active: int | None = None
    burdens_enabled: int | None = None


@dataclass(frozen=True)
class ClockFailure:
    kind: str
    message: str
    line: str
    address: int | None = None
    operation: str | None = None


@dataclass(frozen=True)
class ClockReport:
    rows: tuple[ClockUnit, ...]
    messages: tuple[str, ...]
    failures: tuple[ClockFailure, ...]
    response: CGateResponse

    @property
    def clocks_enabled(self):
        return sum(row.clocks_enabled or 0 for row in self.rows) if self.rows else None

    @property
    def clocks_active(self):
        return sum(row.clocks_active or 0 for row in self.rows) if self.rows else None

    @property
    def burdens_enabled(self):
        return sum(row.burdens_enabled or 0 for row in self.rows) if self.rows else None

    @property
    def complete(self):
        """An inspection needs summaries and no reported failures."""
        return bool(self.rows) and self.response.code == 200 and not self.failures

    def as_dict(self):
        return {'rows': [vars(row) for row in self.rows], 'messages': list(self.messages),
                'failures': [vars(failure) for failure in self.failures],
                'clocks_enabled': self.clocks_enabled, 'clocks_active': self.clocks_active,
                'burdens_enabled': self.burdens_enabled, 'complete': self.complete,
                'response': self.response}


def parse_clock_report(response):
    """Parse exact native summary fields; preserve all other messages.

    Counts omitted on an output_units=0 row remain None. Their contribution
    to totals is zero. Duplicate addresses/fields, incomplete rows, impossible
    per-row counts, or exceeded resource bounds raise with partial parsed data.
    Native per-unit failures are data and force incomplete outcomes even when
    the server's final response is200.
    """
    if not isinstance(response, CGateResponse):
        raise TypeError('Use a CGateResponse')
    rows, messages, failures = [], [], []
    def invalid(message):
        raise ClockParseError(message, response, rows, messages)
    if not response.lines or len(response.lines) > MAX_LINES:
        invalid('Clock response has no lines or exceeds the line limit')
    if response.final != response.lines[-1] or not response.final.startswith(str(response.code) + ' '):
        invalid('Clock response final status is inconsistent')
    size, addresses = 0, set()
    for line in response.lines:
        if not isinstance(line, str) or '\n' in line or '\r' in line or '\0' in line:
            invalid('Invalid clock response line')
        try:
            length = len(line.encode('utf-8'))
        except UnicodeError:
            invalid('Clock response contains invalid Unicode text')
        size += length
        if length > MAX_LINE_BYTES or size > MAX_RESPONSE_BYTES:
            invalid('Clock response exceeds the byte limit')
        match = _PREFIX.fullmatch(line)
        if match is None:
            invalid('Clock response line is missing its native status prefix')
        code, text = int(match[1]), match[2]
        if text.startswith('address='):
            if code != 120:
                invalid('Clock summary must use native status120')
            fields = {}
            for token in text.split(' '):
                field = _FIELD.fullmatch(token)
                if field is None or field[1] in fields:
                    invalid('Malformed or duplicate clock summary field')
                fields[field[1]] = int(field[2])
            required = {'address', 'output_units'}
            if not required <= fields.keys():
                invalid('Clock summary is missing address or output_units')
            if fields['output_units'] > 0:
                required |= {'clocks_enabled', 'clocks_active', 'burdens_enabled'}
            if fields.keys() != required or any(value > 255 for value in fields.values()):
                invalid('Clock summary has unexpected, missing or out-of-range fields')
            if any(fields[name] > fields['output_units'] for name in required - {'address', 'output_units'}):
                invalid('Clock counts exceed the observed output-unit replies')
            if fields['address'] in addresses:
                invalid('Duplicate unit address in clock summary')
            addresses.add(fields['address'])
            rows.append(ClockUnit(**fields))
            continue
        messages.append(line)
        summary_failure = _FAIL_SUMMARY.fullmatch(text)
        change_failure = _FAIL_CHANGE.fullmatch(text)
        if summary_failure:
            address = int(summary_failure[1])
            if address > 255:
                invalid('Clock failure address is outside0..255')
            failures.append(ClockFailure('summary_unavailable', text, line, address))
        elif change_failure:
            address = int(change_failure[1])
            if address > 255:
                invalid('Clock failure address is outside0..255')
            failures.append(ClockFailure('unit_change_failed', text, line, address, change_failure[2]))
        elif text.startswith('FAILED - ') or 'could NOT be' in text or text.startswith('Failed to obtain output unit summary'):
            failures.append(ClockFailure('native_operation_failed', text, line))
        elif code >= 400:
            failures.append(ClockFailure('native_status_failed', text, line))
    return ClockReport(tuple(rows), tuple(messages), tuple(failures), response)


@dataclass(frozen=True)
class ClockOutcome:
    action: str
    address: str
    requested_enabled: int | None
    observed_enabled: int | None
    complete: bool
    action_response: CGateResponse | None
    action_report: ClockReport | None
    inspection: ClockReport | None
    issues: tuple[str, ...] = ()
    recovery_gateway: int | None = None
    recovery_semantics: str | None = None
    device_verified: bool = False
    inspection_response: CGateResponse | None = None

    def as_dict(self):
        return {**vars(self), 'action_report': self.action_report.as_dict() if self.action_report else None,
                'inspection': self.inspection.as_dict() if self.inspection else None}


class NativeClocks:
    def __init__(self, client):
        self.client = client
        self.networks = NativeNetworks(client)

    @staticmethod
    def _address(address):
        address = _token(address, 'network address')
        if any(char in address for char in ('*', '?', ',')):
            raise ValueError('Clock verification requires one network address')
        return address

    def inspect(self, address):
        address = self._address(address)
        try:
            response = self.networks.clocks(address)
        except CGateError as error:
            response = error.response
        return parse_clock_report(response)

    def configure(self, address, target):
        if isinstance(target, bool) or not isinstance(target, int) or not 1 <= target <= 10:
            raise ValueError('Clock target must be an integer in1..10')
        return self._operate(self._address(address), target, False)

    def recover(self, address):
        return self._operate(self._address(address), None, True)

    def _operate(self, address, target, recover):
        action = 'recover' if recover else 'configure'
        semantics = 'Enable the gateway clock if disabled; no network-wide target count is requested' if recover else None
        response, action_report, inspection, gateway, inspection_response = None, None, None, None, None
        issues = []
        def outcome():
            return ClockOutcome(action, address, target, inspection.clocks_enabled if inspection else None,
                                not issues, response, action_report, inspection, tuple(issues), gateway, semantics,
                                inspection_response=inspection_response)
        try:
            response = self.networks.clocks(address, target, recover=recover)
        except CGateError as error:
            response = error.response
        except (RuntimeError, OSError) as error:
            issues.append('Clock action transport failed; outcome is unknown and no further command was sent: ' + str(error))
            partial = getattr(error, 'response', None)
            if isinstance(partial, CGateResponse):
                response = partial
            return outcome()
        try:
            action_report = parse_clock_report(response)
        except ClockParseError as error:
            issues.append('Clock action response could not be parsed; no further command was sent: ' + str(error))
            return outcome()
        issues.extend(failure.message for failure in action_report.failures)
        if response.code != 200 and not action_report.failures:
            issues.append('Clock action did not return200: ' + response.final)
        if recover:
            # dz.b(true) returns the gateway's OLD summary even when it then
            # changes that clock. Already-enabled recovery emits no success
            # message, making this single summary the authoritative identity.
            reported = {row.address for row in action_report.rows}
            for line in action_report.messages:
                message = _PREFIX.fullmatch(line)
                enabled = _GATEWAY.fullmatch(message[2]) if message else None
                if enabled is not None:
                    reported.add(int(enabled[1]))
            if len(reported) == 1 and next(iter(reported)) <= 255:
                gateway = next(iter(reported))
            else:
                issues.append('Recovery response did not identify exactly one gateway address')
        # A complete native failure response leaves the command stream framed.
        # One fresh observation is useful; no write is retried or compensated.
        try:
            inspection = self.inspect(address)
            inspection_response = inspection.response
        except (RuntimeError, OSError) as error:
            partial = getattr(error, 'response', None)
            if isinstance(partial, CGateResponse):
                inspection_response = partial
            issues.append('Fresh clock inspection failed: ' + str(error))
            return outcome()
        if not inspection.complete:
            issues.extend(failure.message for failure in inspection.failures)
            if not inspection.failures:
                issues.append('Fresh clock inspection returned no complete address summaries')
        if recover:
            row = next((row for row in inspection.rows if row.address == gateway), None)
            if row is None or not row.clocks_enabled:
                issues.append('The reported gateway was not observed with an enabled clock')
        elif inspection.clocks_enabled != target:
            issues.append(f'Requested {target} enabled clocks; observed {inspection.clocks_enabled}')
        return outcome()
