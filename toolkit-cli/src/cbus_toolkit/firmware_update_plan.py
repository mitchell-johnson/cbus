"""Original eDLT FirmwareUpdater step plan, private package reader and simulator run.

The plan reproduces ``FirmwareUpdater.UpgradeFirmware`` and the argument set-up
in ``FirmwareUpgrader_DoWork`` of the updater bundled with Toolkit 1.18
(assembly 1.16.3.0). It is derived from ZIP directory metadata only.

Vendor archives are encrypted with a constant embedded in the updater. This
module never contains, stores or reports that value: a caller supplies it at
runtime through a file. Decrypted entries stay in memory and only hashes,
sizes and DFU/vector-table metadata are reported. The archives carry no
signature, so a successful read establishes integrity against the archive's
own CRC/HMAC, not vendor authenticity.

The simulator run is development evidence. It drives the independent memory
DFU peer through the existing strict client and does not model the mode
switch, target reset, bootloader auto-erase, re-enumeration or NCC serial path.
"""
from __future__ import annotations

import hashlib
import os
from pathlib import Path
import struct
import zipfile
import zlib

from .dfu import MAX_IMAGE_SIZE, inspect_image
from .firmware_diagnostics import classify_hardware, inspect_package

PASSWORD_FILE_ENV = 'CBUS_EDLT_PACKAGE_PASSWORD_FILE'
# EDLTCommon.EdltFirmware.FontData1Versions (Toolkit 1.18 EDLTCommon.dll).
FONT_DATA1_VERSIONS = ('1.0.0', '1.1.0', '1.2.0', '1.3.0', '1.4.0', '1.5.0', '1.6.0', '1.7.0')
# UpgradeFirmware passes these literal -a texts to dfuprog.
MAIN_ADDRESS_TEXT = {'StellarisPCI': '0x2000', 'TivaPCI': '0x4000', 'TivaNCC': '0x4000'}
VARIANT_HARDWARE = {'StellarisPCI': '1.0 (Stellaris + PCI)', 'TivaPCI': '2.0 (Tiva + PCI)',
                    'TivaNCC': '3.0 (Tiva + NCC)'}
MODE_SWITCH_FAILURE = 'Unable to prepare unit for firmware upgrade (exit code {exit_code}).'
NATIVE_QUIRKS = (
    'Every dfuprog step aborts the update only when Process.ExitCode > 0; a negative Windows exit code proceeds.',
    'The font write adds -r only when the main image path is empty, which the preceding File.Exists check excludes.',
    'The font erase length is literally (font_bytes / 65537 + 1) * 65536 with integer division; the -a address is omitted.',
    'Font installation is skipped whenever the package filename version is in FontData1Versions unless forced.',
    'No step compares the package version with the unit firmware before writing: downgrades and reinstalls proceed.',
    'dfuprog is called without -s, so its download path forwards verify=0; the updater performs no readback.',
    'Every selected entry is extracted to the temporary directory, including images for other variants.',
    'PCI variants report success after dfuprog exits without reading the unit version again.',
    'The NCC check constructs System.Version from both NCC versions before its empty-value test, so empty or invalid versions fail.',
)


class FirmwarePackageError(ValueError):
    """A package could not be read; the message never contains the password."""


def font_erase_length(font_bytes):
    """Exact original expression, including its 65537 divisor."""
    if isinstance(font_bytes, bool) or not isinstance(font_bytes, int) or font_bytes < 0:
        raise ValueError('Font size must be a nonnegative integer')
    return (font_bytes // 65537 + 1) * 65536


def resolve_variant(variant=None, hardware_version=None):
    if (variant is None) == (hardware_version is None):
        raise ValueError('Select exactly one of variant or hardware version')
    if variant is not None:
        if variant not in MAIN_ADDRESS_TEXT:
            raise ValueError('Variant must be StellarisPCI, TivaPCI or TivaNCC')
        return variant
    resolved = classify_hardware(hardware_version)
    if resolved == 'Unknown':
        # UpgradeFirmware: throw new Exception("Unit variant is unknown.")
        raise ValueError('Unit variant is unknown.')
    return resolved


def _extracted(name):
    return '<extracted:' + name + '>'


def _ncc_post_check(version):
    return [
        {'step': 'identify', 'delay_before_ms': 10000, 'serial_request': 'id\\r',
         'check': f'Reported firmware version must equal the package version {version!r} exactly',
         'failure_message': 'Version {firmware_version} returned by unit does not match the expected version ' + version + '.'},
        {'step': 'ncc-versions', 'delay_before_ms': 500, 'serial_request': 'nv\\r',
         'check': 'Update is required when System.Version(embedded) > System.Version(current)',
         'failure': 'A timeout, COMMAND NOT VALID (empty versions) or an invalid version fails the update'},
        {'step': 'ncc-update', 'when': 'update required', 'serial_request': 'nu\\r',
         'check': 'Wait up to 60 s for the lines Updating NCC Firmware.., Update Started and Update Complete'},
        {'step': 'ncc-versions-after-update', 'when': 'update required', 'serial_request': 'nv\\r',
         'check': 'Versions are logged but not compared'},
        {'step': 'restart', 'when': 'update required and current version is exactly 0.0.0', 'serial_request': 'rs\\r',
         'check': 'The write is not acknowledged and the port is left open'},
        {'step': 'identify-after-restart', 'when': 'restart sent', 'delay_before_ms': 10000, 'serial_request': 'id\\r',
         'check': 'A failed identification is reported as success with a manual C-Bus power-cycle instruction'},
    ]


def update_plan(package, *, variant=None, hardware_version=None, force_font=False):
    """Return the deterministic original updater plan for one package/variant."""
    if not isinstance(force_font, bool):
        raise ValueError('force_font must be boolean')
    variant = resolve_variant(variant, hardware_version)
    metadata = inspect_package(package)
    version = metadata['version']
    sizes = {entry['name']: entry['bytes'] for entry in metadata['entries']}
    images, fonts = metadata['image_candidates'], metadata['font_candidates']
    main = images[variant][-1] if images[variant] else None
    font = fonts[-1] if fonts else None
    selected = {name for names in images.values() for name in names} | set(fonts)
    issues = []
    if metadata['native_invalid_entries']:
        issues.append('Package contains a non-file entry; the original extraction clears every selection')
    if main is None or font is None:
        issues.append('The selected firmware archive is not compatible with the connected eDLT unit.')
    for name in sorted(selected):
        if '/' in name or '\\' in name or name in ('.', '..'):
            issues.append(f'Entry {name!r} is not a plain file name; original extraction depends on the host temporary directory')
    if len(images[variant]) > 1 or len(fonts) > 1:
        issues.append('Multiple candidates for one role; the original uses the last one')
    font_version_listed = version in FONT_DATA1_VERSIONS
    skip_font = font_version_listed and not force_font
    font_bytes = sizes.get(font) if font is not None else None
    erase = font_erase_length(font_bytes) if font_bytes is not None else None
    if not skip_font and erase is not None and erase < font_bytes:
        issues.append('The original font erase length is shorter than the font data')
    steps = []
    if main is not None and font is not None:
        steps.append({'step': 'mode-switch', 'delay_before_ms': 0, 'native_arguments': '-m', 'argv': ['-m'],
                      'failure_message': MODE_SWITCH_FAILURE})
        if not skip_font:
            steps += [
                {'step': 'font-erase', 'delay_before_ms': 8000, 'native_arguments': f'-z -c -l {erase}',
                 'argv': ['-z', '-c', '-l', str(erase)], 'flash': 'external', 'length': erase,
                 'failure_message': 'Unable to clear flash memory for font data installation (exit code {exit_code}).'},
                {'step': 'font-write', 'delay_before_ms': 0,
                 'native_arguments': f'-z -b  -a 0 -f "{_extracted(font)}"',
                 'argv': ['-z', '-b', '-a', '0', '-f', _extracted(font)], 'flash': 'external', 'address': 0,
                 'entry': font, 'bytes': font_bytes, 'reset': False,
                 'failure_message': 'Unable to write font data to unit (exit code {exit_code}).'},
                {'step': 'mode-switch', 'delay_before_ms': 0, 'native_arguments': '-m', 'argv': ['-m'],
                 'failure_message': MODE_SWITCH_FAILURE},
            ]
        address = MAIN_ADDRESS_TEXT[variant]
        steps.append({'step': 'main-write', 'delay_before_ms': 10000,
                      'native_arguments': f'-b -a {address} -r -f "{_extracted(main)}"',
                      'argv': ['-b', '-a', address, '-r', '-f', _extracted(main)], 'flash': 'internal',
                      'address': int(address, 16), 'entry': main, 'bytes': sizes[main], 'reset': True,
                      'failure_message': 'Unable to write firmware to unit (exit code {exit_code}).'})
    return {
        'format': 'cbus-edlt-firmware-update-plan-v1', 'supported': not issues, 'issues': issues,
        'package': {'name': metadata['name'], 'sha256': metadata['sha256'], 'version': version,
                    'entries': metadata['entries'], 'skipped_entries': metadata['unknown_entries'],
                    'extracted_entries': [entry['name'] for entry in metadata['entries']
                                          if entry['name'] in selected]},
        'variant': variant, 'hardware_version': hardware_version,
        'selected_main_entry': main, 'selected_font_entry': font,
        'main_address': MAIN_ADDRESS_TEXT[variant],
        'font_install': {'performed': not skip_font, 'forced': force_font,
                         'package_version_in_font_data1_versions': font_version_listed,
                         'font_data1_versions': list(FONT_DATA1_VERSIONS)},
        'font_erase': {'formula': '(font_bytes / 65537 + 1) * 65536', 'font_bytes': font_bytes,
                       'length': erase, 'covers_font': erase is not None and erase >= font_bytes},
        'dfuprog_program': 'Firmware\\eDLTFirmware\\dfuprog.exe under the updater directory',
        'abort_rule': 'exit_code > 0 stops the update; no later step or retry runs',
        'dfuprog_steps': steps,
        'post_check': ({'kind': 'ncc-serial', 'steps': _ncc_post_check(version)} if variant == 'TivaNCC' else
                       {'kind': 'none', 'note': 'PCI variants report success immediately after the main write'}),
        'version_gate': 'none',
        'native_quirks': list(NATIVE_QUIRKS),
        'source': 'Toolkit 1.18 FirmwareUpdater 1.16.3.0 UpgradeFirmware/UnzipFirmwarePackage/DoWork',
        'read_only': True, 'firmware_written': False, 'image_contents_verified': False,
    }


def read_password_file(path=None):
    """Read a runtime-supplied package password, or return None if not supplied."""
    if path is None:
        path = os.environ.get(PASSWORD_FILE_ENV) or None
        source = 'environment-file' if path else None
    else:
        source = 'file'
    if path is None:
        return None, None
    with open(path, 'rb') as stream:
        value = stream.read(4097)
    if len(value) > 4096:
        raise FirmwarePackageError('Package password file exceeds 4096 bytes')
    if value.endswith(b'\r\n'):
        value = value[:-2]
    elif value.endswith(b'\n'):
        value = value[:-1]
    if not value:
        raise FirmwarePackageError('Package password file is empty')
    return value, source


def _encryption(info):
    if info.compress_type == 99:
        return 'aes'
    return 'zipcrypto' if info.flag_bits & 1 else 'none'


def read_package_entries(package, password, *, names=None):
    """Return {entry name: bytes} decrypted in memory; never writes plaintext."""
    if not isinstance(password, bytes) or not password:
        raise FirmwarePackageError('A package password is required')
    try:
        import pyzipper
    except ImportError:
        pyzipper = None
    opener = pyzipper.AESZipFile if pyzipper is not None else zipfile.ZipFile
    result = {}
    try:
        with opener(package) as archive:
            infos = archive.infolist()
            if len(infos) > 1024:
                raise FirmwarePackageError('Firmware package exceeds 1024 directory entries')
            for info in infos:
                if info.is_dir() or names is not None and info.filename not in names:
                    continue
                if info.file_size > MAX_IMAGE_SIZE:
                    raise FirmwarePackageError(f'Entry {info.filename!r} exceeds the {MAX_IMAGE_SIZE}-byte image limit')
                if _encryption(info) == 'aes' and pyzipper is None:
                    raise FirmwarePackageError('AES-encrypted entries require the optional firmware extra (pyzipper)')
                with archive.open(info, pwd=password) as stream:
                    data = stream.read(MAX_IMAGE_SIZE + 1)
                if len(data) != info.file_size:
                    raise FirmwarePackageError(f'Entry {info.filename!r} size differs from its directory record')
                result[info.filename] = data
    except FirmwarePackageError:
        raise
    except RuntimeError as error:
        # zipfile/pyzipper: "Bad password for file ..." or unsupported methods.
        text = 'bad password' if 'password' in str(error).lower() else 'unsupported entry'
        raise FirmwarePackageError(f'Package entry could not be decrypted ({text})') from None
    except (zipfile.BadZipFile, zlib.error, NotImplementedError, OSError, ValueError, EOFError) as error:
        raise FirmwarePackageError(f'Package entry could not be read: {type(error).__name__}') from None
    return result


def _download_path(container):
    # dfuprog's download dispatcher: a valid TI-prefixed container uses its own
    # address, a valid suffix-only container is stripped, anything else is raw.
    if container['valid'] and container['has_ti_prefix']:
        return 'dfu-prefixed: the prefix address replaces -a'
    return 'dfu-suffix-stripped binary at -a' if container['valid'] else 'raw binary at -a'


def _vector_table(data, address):
    if address is None or len(data) < 8:
        return None
    stack, reset = struct.unpack_from('<II', data)
    handler = reset & ~1
    return {'initial_stack_pointer': f'0x{stack:08x}', 'reset_vector': f'0x{reset:08x}',
            'thumb': bool(reset & 1), 'load_address': f'0x{address:x}',
            'reset_handler_in_image': address <= handler < address + len(data)}


def inspect_package_images(package, password, *, password_source='file'):
    """Hash every entry and run the DFU container inspector over the plaintext."""
    metadata = inspect_package(package)
    role = {}
    for variant, names in metadata['image_candidates'].items():
        for name in names:
            role[name] = variant
    for name in metadata['font_candidates']:
        role[name] = 'Font'
    methods = {}
    with zipfile.ZipFile(package) as archive:
        for info in archive.infolist():
            methods[info.filename] = _encryption(info)
    data = read_package_entries(package, password)
    rows = []
    for entry in metadata['entries']:
        name = entry['name']
        if name not in data:
            continue
        content = data[name]
        variant = role.get(name)
        address = int(MAIN_ADDRESS_TEXT[variant], 16) if variant in MAIN_ADDRESS_TEXT else None
        container = inspect_image(content).as_dict()
        rows.append({'name': name, 'role': variant or 'skipped', 'encryption': methods.get(name),
                     'bytes': len(content), 'sha256': hashlib.sha256(content).hexdigest(),
                     'integrity_verified': True,
                     'dfu_container': {key: container[key] for key in (
                         'valid', 'supported', 'issues', 'has_ti_prefix', 'crc_valid', 'address', 'payload_length')},
                     'native_download_path': _download_path(container),
                     'cortex_m_vector_table': _vector_table(content, address)})
    return {'format': 'cbus-edlt-firmware-package-images-v1', 'name': metadata['name'],
            'sha256': metadata['sha256'], 'version': metadata['version'], 'images': rows,
            'password_source': password_source, 'password_reported': False,
            'authenticity_verified': False,
            'authenticity_scope': 'The archive has no signature; the shared updater password and ZIP CRC/AES HMAC establish integrity only',
            'plaintext_written': False, 'read_only': True, 'firmware_written': False,
            'image_contents_verified': False}


# Synthetic descriptors used only by the memory simulator run. They match the
# eDLT DFU-mode identity (166A:0501, class FE/01/02, 1024-byte transfers).
SIMULATOR_DEVICE_DESCRIPTOR = bytes.fromhex('12010002000000406a160105341201020301')
SIMULATOR_CONFIGURATION_DESCRIPTOR = bytes.fromhex('09021b0001010080320904000000fe010200092107e80300040001')


class _VirtualClock:
    def __init__(self):
        self.now = 0.0

    def __call__(self):
        return self.now

    def sleep(self, seconds):
        self.now += seconds


def _outcome(outcome):
    row = outcome.as_dict()
    return {key: row[key] for key in ('operation', 'complete', 'external', 'address', 'length',
            'payload_transferred', 'readback_bytes', 'first_mismatch', 'expected_sha256',
            'readback_sha256', 'stage', 'error', 'peer_verified')} | {'trace_rows': len(row['trace'])}


def simulate_plan(plan, images, *, flash_size=1024 * 1024, external_size=None):
    """Execute a supported plan's DFU steps against the independent memory peer.

    Each dfuprog step opens a fresh host session. Mode switches are no-ops
    because the peer is already in DFU mode, and the target reset is not sent.
    The first failed step stops execution, as the original ExitCode check does.
    """
    from .dfu_simulator import DFUSimulator
    from .dfu_transport import DFUClient, DFUOperationError, MemoryEndpoint0, parse_descriptors
    if not isinstance(plan, dict) or plan.get('format') != 'cbus-edlt-firmware-update-plan-v1':
        raise ValueError('A cbus-edlt-firmware-update-plan-v1 plan is required')
    if not plan['supported']:
        raise ValueError('Only a supported plan can be simulated')
    needed = {step['entry'] for step in plan['dfuprog_steps'] if 'entry' in step}
    if not needed <= images.keys():
        raise ValueError('Plan entries are missing from the supplied images')
    erase = plan['font_erase']['length'] or 0
    if external_size is None:
        external_size = max(131072, erase)
    descriptor = parse_descriptors(SIMULATOR_DEVICE_DESCRIPTOR, SIMULATOR_CONFIGURATION_DESCRIPTOR)
    address = int(plan['main_address'], 16)
    peer = DFUSimulator(flash_size=flash_size, application_start=address, external_size=external_size,
                        transfer_size=descriptor.transfer_size)
    results, complete = [], True
    for index, step in enumerate(plan['dfuprog_steps'], 1):
        row = {'index': index, 'step': step['step'], 'argv': step['argv']}
        results.append(row)
        if step['step'] == 'mode-switch':
            row.update(executed=False, simulated='no-op: the memory peer is already in DFU mode')
            continue
        external = step['flash'] == 'external'
        peer.new_host_session()
        clock = _VirtualClock()
        client = DFUClient(MemoryEndpoint0(peer, descriptor), descriptor,
                           flash_size=external_size if external else flash_size,
                           application_start=0 if external else address, external=external,
                           clock=clock, sleep=clock.sleep)
        try:
            if step['step'] == 'font-erase':
                outcome = client.erase(address=0, length=step['length'])
            else:
                outcome = client.program(images[step['entry']], address=step['address'])
        except DFUOperationError as error:
            outcome = error.outcome
        except ValueError as error:
            row.update(executed=False, error=str(error))
            complete = False
            break
        row.update(executed=True, outcome=_outcome(outcome))
        if step.get('reset'):
            row['reset'] = 'not sent: eDLT reset behavior is not modeled by the memory peer'
        if not outcome.complete:
            complete = False
            break
    regions = {}
    for step in plan['dfuprog_steps']:
        if 'entry' in step and complete:
            memory = peer.external if step['flash'] == 'external' else peer.internal
            data = images[step['entry']]
            actual = bytes(memory[step['address']:step['address'] + len(data)])
            regions[step['step']] = {'entry': step['entry'], 'sha256': hashlib.sha256(actual).hexdigest(),
                                     'matches_image': actual == data}
    return {'format': 'cbus-edlt-firmware-update-simulation-v1', 'complete': complete,
            'steps': results, 'regions': regions, 'peer': peer.snapshot(),
            'post_check': 'not executed: the NCC serial path and version reads are outside the memory peer',
            'flash_size': flash_size, 'external_size': external_size,
            'development_evidence_only': True, 'physical_device_verified': False,
            'scope': 'Memory-only DFU peer; mode switch, reset, bootloader auto-erase and re-enumeration are unmodeled'}


def load_selected_images(package, plan, password):
    needed = sorted({step['entry'] for step in plan['dfuprog_steps'] if 'entry' in step})
    return read_package_entries(Path(package), password, names=set(needed))


def attach_image_inspection(plan, inspection):
    """Add decrypted-image facts to a plan and refuse images the plan cannot describe."""
    plan['image_inspection'] = inspection
    rows = {row['name']: row for row in inspection['images']}
    main = rows.get(plan['selected_main_entry'])
    if main is not None:
        if main['native_download_path'].startswith('dfu-prefixed'):
            plan['issues'].append('The selected main image is DFU-prefixed; dfuprog would ignore the variant address')
        table = main['cortex_m_vector_table']
        if table is not None and not table['reset_handler_in_image']:
            plan['issues'].append('The selected main image reset vector lies outside the image at the variant address')
    plan['supported'] = not plan['issues']
    return plan
