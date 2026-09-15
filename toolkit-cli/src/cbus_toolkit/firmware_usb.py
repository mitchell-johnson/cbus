"""One explicit USB acquisition, DFU operation, and unconditional release.

Only raw bytes are accepted for programming. No erase/reset/retry is inferred.
Physical USB evidence remains distinct from tests using an injected backend.
"""
from __future__ import annotations

from .dfu_transport import DFUClient
from .usb_dfu import ClaimedUSBSession, USBAcquisitionError


def _message(error):
    return str(error) or type(error).__name__


def run_usb_dfu(operation, *, bus, address, expected_serial, descriptor,
                release_policy, flash_size, application_start, external=False,
                timeout=30, inspection_timeout=5, poll_limit=256, data=None,
                address_offset=None, length=None, backend=None):
    """Run one operation and retain acquisition, transfer and release evidence.

    Pure argument validation precedes USB acquisition. Ordinary lifecycle or
    operation failures return complete=False. KeyboardInterrupt/SystemExit and
    other BaseException interruptions propagate with ``usb_dfu_evidence``;
    an earlier error remains in that evidence if cleanup also fails.

    The release policy is explicit because release may reset the interface to
    its first alternate. Acquisition and release are not deadline bounded.
    A successful backend test is never physical-device acceptance evidence.
    """
    preflight = DFUClient.preflight(descriptor, operation=operation,
        flash_size=flash_size, application_start=application_start,
        external=external, timeout=timeout, poll_limit=poll_limit,
        data=data, address=address_offset, length=length)
    session = client = acquisition = transfer = release = lease = None
    primary = cleanup_error = None
    primary_stage = None
    stage = 'acquisition'
    invoked = False
    try:
        session = ClaimedUSBSession.acquire(bus=bus, address=address,
            expected_serial=expected_serial, descriptor=descriptor,
            release_policy=release_policy, inspection_timeout=inspection_timeout,
            backend=backend)
        acquisition = session.acquisition
        stage = 'endpoint'
        lease = session.endpoint()
        stage = 'client'
        client = DFUClient(lease, descriptor, flash_size=flash_size,
            application_start=application_start, external=external,
            timeout=timeout, poll_limit=poll_limit)
        stage = 'transfer'
        invoked = True
        if operation == 'inspect':
            transfer = client.inspect()
        elif operation == 'program':
            transfer = client.program(data, address=address_offset)
        else:
            transfer = client.erase(address=address_offset, length=length)
    except BaseException as error:
        primary, primary_stage = error, stage
        if isinstance(error, USBAcquisitionError):
            # acquire already cleaned up; release() is idempotent and returns
            # its recorded outcome without replaying the lifecycle.
            session = error.session
            acquisition, release = error.acquisition, error.release
        else:
            acquisition = getattr(error, 'usb_acquisition', acquisition)
            release = getattr(error, 'usb_release', release)
        if client is not None:
            transfer = client.last_outcome
    finally:
        if session is not None:
            try:
                release = session.release()
            except BaseException as error:
                cleanup_error = error
                release = session.last_release
    # Serialization follows physical cleanup, so reporting never owns a live
    # claim and never replaces operation evidence with only a cleanup error.
    errors = []
    for failed_stage, outcome in (('acquisition', acquisition), ('transfer', transfer)):
        if outcome is not None and not outcome.complete and outcome.error:
            errors.append({'stage': failed_stage,
                'type': type(primary).__name__ if primary is not None and _message(primary) == outcome.error else 'USBOperationFailure',
                'error': outcome.error})
    if primary is not None and not any(row['error'] == _message(primary) for row in errors):
        errors.append({'stage': primary_stage, 'type': type(primary).__name__, 'error': _message(primary)})
    if cleanup_error is not None:
        errors.append({'stage': 'release', 'type': type(cleanup_error).__name__, 'error': _message(cleanup_error)})
    if release is not None:
        for name in ('release_error', 'close_error', 'timing_error'):
            value = getattr(release, name)
            if value:
                errors.append({'stage': name.removesuffix('_error'), 'type': 'USBReleaseFailure', 'error': value})
    complete = (primary is None and cleanup_error is None and acquisition is not None
                and acquisition.complete and transfer is not None and transfer.complete
                and release is not None and release.complete)
    transfer_data = transfer.as_dict() if transfer is not None else None
    if transfer_data is not None:
        transfer_data['scope'] = 'One DFU operation over a claimed USB Endpoint0 lease; hardware acceptance is not established'
    result = {'format': 'cbus-usb-dfu-result-v1', 'operation': operation,
        'complete': bool(complete), 'preflight': preflight,
        'acquisition': acquisition.as_dict() if acquisition is not None else None,
        'transfer': transfer_data,
        'release': release.as_dict() if release is not None else None,
        'operation_invoked': invoked,
        'endpoint_trace': [dict(row) for row in lease.trace] if lease is not None else [],
        'error': errors[0]['error'] if errors else None, 'errors': errors,
        'physical_device_verified': False,
        'scope': 'One explicitly claimed USB DFU operation; no automatic erase, reset or retry',
        'timeout_scope': 'DFU operation deadline and per-inspection-transfer timeout; acquisition and release are not deadline bounded'}
    interruption = (primary if primary is not None and not isinstance(primary, Exception)
                    else cleanup_error if cleanup_error is not None and not isinstance(cleanup_error, Exception)
                    else None)
    if interruption is not None:
        interruption.usb_dfu_evidence = result
        raise interruption.with_traceback(interruption.__traceback__)
    return result
