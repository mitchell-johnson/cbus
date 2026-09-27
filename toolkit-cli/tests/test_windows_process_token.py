"""Mocked Win32 ABI rejection tests; native acceptance is separate."""
import ctypes
from types import SimpleNamespace
from unittest.mock import Mock, patch
import pytest
from cbus_toolkit import _windows_process_token as token


def setup_api(mode=None):
    kernel, security = Mock(), Mock()
    kernel.GetProcessId.return_value = 1234
    kernel.WaitForSingleObject.return_value = 258
    kernel.CloseHandle.return_value = 1
    def opened(process, access, result):
        assert process == 123 and access == 8
        ctypes.cast(result, ctypes.POINTER(token.HANDLE))[0] = 456
        return 1
    def read(handle, kind, buffer, capacity, output):
        assert handle.value == 456 and kind == 1 and capacity == 256
        offset = ctypes.sizeof(token._TokenUser)
        raw = bytes([1, 1, 0, 0, 0, 0, 0, 5, 18, 0, 0, 0])
        address = ctypes.addressof(buffer)
        ctypes.memmove(address + offset, raw, len(raw))
        token._TokenUser.from_buffer(buffer).sid = address + offset
        length = offset + len(raw)
        if mode == 'null_pointer': token._TokenUser.from_buffer(buffer).sid = None
        if mode == 'before_buffer': token._TokenUser.from_buffer(buffer).sid = address - 1
        if mode == 'inside_header': token._TokenUser.from_buffer(buffer).sid = address
        if mode == 'past_buffer': token._TokenUser.from_buffer(buffer).sid = address + 256
        if mode == 'short_header': length = offset + 7
        if mode == 'short_sid': length -= 1
        if mode == 'huge_length': length = 257
        if mode == 'zero_length': length = 0
        if mode == 'revision': buffer[offset] = b'\x02'
        if mode == 'zero_count': buffer[offset + 1] = b'\x00'
        if mode == 'large_count': buffer[offset + 1] = b'\x10'
        ctypes.cast(output, ctypes.POINTER(token.DWORD))[0] = length
        return 1
    security.OpenProcessToken.side_effect = opened
    security.GetTokenInformation.side_effect = read
    return kernel, security


def call(kernel, security, process=None):
    with patch.object(token, '_apis', return_value=(kernel, security)):
        return token.process_token_user_sid(process or SimpleNamespace(pid=1234, _handle=123))


def test_uses_owned_handle_query_only_and_closes_only_token():
    kernel, security = setup_api()
    assert call(kernel, security) == 'S-1-5-18'
    assert kernel.GetProcessId.call_count == kernel.WaitForSingleObject.call_count == 2
    kernel.CloseHandle.assert_called_once()
    assert kernel.CloseHandle.call_args.args[0].value == 456


@pytest.mark.parametrize('mode', ['null_pointer', 'before_buffer', 'inside_header', 'past_buffer',
                                  'short_header', 'short_sid', 'huge_length', 'zero_length',
                                  'revision', 'zero_count', 'large_count'])
def test_malformed_token_result_fails_closed_and_closes(mode):
    kernel, security = setup_api(mode)
    with pytest.raises(ValueError): call(kernel, security)
    kernel.CloseHandle.assert_called_once()


@pytest.mark.parametrize('stage', ['before', 'after'])
@pytest.mark.parametrize('check,value', [('GetProcessId', 999), ('WaitForSingleObject', 0),
                                        ('WaitForSingleObject', 0xffffffff)])
def test_pid_or_liveness_failure_never_admits(stage, check, value):
    kernel, security = setup_api()
    getattr(kernel, check).side_effect = [value] if stage == 'before' else [1234 if check == 'GetProcessId' else 258, value]
    with pytest.raises(OSError): call(kernel, security)
    assert security.GetTokenInformation.call_count == (stage == 'after')
    assert kernel.CloseHandle.call_count == (stage == 'after')


def test_open_query_and_close_failures_are_not_replaced_by_identity_claims():
    kernel, security = setup_api()
    security.OpenProcessToken.side_effect = None
    security.OpenProcessToken.return_value = 0
    with pytest.raises(OSError, match='OpenProcessToken'): call(kernel, security)
    kernel.CloseHandle.assert_not_called()
    security.GetTokenInformation.assert_not_called()
    kernel, security = setup_api()
    security.GetTokenInformation.side_effect = None
    security.GetTokenInformation.return_value = 0
    kernel.CloseHandle.return_value = 0
    with pytest.raises(OSError, match='GetTokenInformation') as caught: call(kernel, security)
    assert caught.value.__notes__ == ['Owned worker token handle close also failed']
    kernel.CloseHandle.assert_called_once()
    kernel, security = setup_api()
    kernel.CloseHandle.return_value = 0
    with pytest.raises(OSError, match='close failed'): call(kernel, security)


@pytest.mark.parametrize('process', [SimpleNamespace(pid=1234), SimpleNamespace(pid=True,_handle=123),
                                     SimpleNamespace(pid=1234,_handle=0), SimpleNamespace(pid=0,_handle=123)])
def test_missing_or_invalid_original_handle_never_opens_by_pid(process):
    kernel, security = setup_api()
    with pytest.raises(OSError): call(kernel, security, process)
    security.OpenProcessToken.assert_not_called()
