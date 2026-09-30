"""Isolated original temperature report and decimal-format instructions.

Synthetic getters/string leaves; no PP loader, project, GUI or hardware runs.
Original FloatToText/FloatToDecimal and CelsiusToFahrenheit execute separately.
"""
from __future__ import annotations

import argparse
import hashlib
import json
from fractions import Fraction
from pathlib import Path
import struct

from unicorn import Uc, UC_ARCH_X86, UC_MODE_32, UC_HOOK_CODE
from unicorn.x86_const import UC_X86_REG_EAX, UC_X86_REG_ECX, UC_X86_REG_EDX, UC_X86_REG_EIP, UC_X86_REG_ESP, UC_X86_REG_FPCW
from project_documentor_static import _Toolkit, EXE_SHA256, MAP_SHA256

RETURN, UNIT, STRINGS, RESULT = 0x30000000, 0x20000100, 0x20001000, 0x20002000
COLLECTION, LIST_VMT, STR_VMT, ADD, COUNT, SHIM = 0x20003000, 0x20004000, 0x20005000, 0x20006000, 0x20006010, 0x20007000
BODIES = {kind: f'CIS_T{cls}Documentor.T{cls}Documentor.DocumentHTML' for kind, cls in (
    ('SENTEMP', 'SENTEMP'), ('SENTEMPB', 'SENTEMPPro'), ('SENTEMP4', 'DigitalTemperatureSensor'))}


def extended(value):
    value = Fraction(value)
    if not value:
        return bytes(10)
    magnitude = abs(value)
    exponent = magnitude.numerator.bit_length() - magnitude.denominator.bit_length()
    if magnitude < Fraction(2) ** exponent:
        exponent -= 1
    significand = round(magnitude / Fraction(2) ** (exponent - 63))
    return struct.pack('<QH', significand, exponent + 16383 + (32768 if value < 0 else 0))


class Probe:
    def __init__(self, exe, map_file):
        raw, symbols = exe.read_bytes(), map_file.read_bytes()
        if hashlib.sha256(raw).hexdigest() != EXE_SHA256 or hashlib.sha256(symbols).hexdigest() != MAP_SHA256:
            raise ValueError('Original Toolkit EXE/MAP hash mismatch')
        self.t = _Toolkit(raw, symbols)
        self.image = self.t.pe.get_memory_mapped_image()

    def machine(self):
        u = Uc(UC_ARCH_X86, UC_MODE_32)
        u.mem_map(0, 4096)
        u.mem_map(self.t.base, (len(self.image) + 4095) & ~4095)
        u.mem_write(self.t.base, self.image)
        u.mem_map(0x20000000, 0x100000)
        u.mem_map(0x21000000, 0x10000)
        u.mem_map(RETURN, 4096)
        u.reg_write(UC_X86_REG_FPCW, 0x133f)
        return u

    def numeric(self, values):
        """Run original absolute/delta conversion and fixed two-decimal output."""
        u = self.machine()
        value_addr, out = 0x20008000, 0x20009000
        u.mem_write(0x13c9ecc, b'.\0')
        # Keep code immutable across runs: Unicorn caches translated blocks.
        code = b'\xff\x35' + struct.pack('<I', SHIM + 0x104)
        code += b'\xff\x35' + struct.pack('<I', SHIM + 0x100)
        code += b'\xe8' + struct.pack('<i', 0x7b6c38 - (SHIM + len(code)) - 5)
        code += b'\xd8\x25' + struct.pack('<I', SHIM + 0x108)
        code += b'\xdb\x3d' + struct.pack('<I', value_addr) + b'\xc3'
        u.mem_write(SHIM, code)
        records = []
        for value, fahrenheit, delta in values:
            u.mem_write(value_addr, extended(value))
            if fahrenheit:
                # Owned wrapper loads a double argument; native helper returns
                # double precision, exactly as the three DocumentHTML callers.
                u.mem_write(SHIM + 0x100, struct.pack('<df', float(value), 32.0 if delta else 0.0))
                u.mem_write(0x21008000, struct.pack('<I', RETURN))
                u.reg_write(UC_X86_REG_ESP, 0x21008000)
                u.emu_start(SHIM, RETURN, count=1000)
            u.mem_write(0x21008000, struct.pack('<IIII', RETURN, 2, 18, 2))
            for register, number in ((UC_X86_REG_EAX, out), (UC_X86_REG_EDX, value_addr), (UC_X86_REG_ECX, 0), (UC_X86_REG_ESP, 0x21008000)):
                u.reg_write(register, number)
            u.emu_start(0x61c33c, RETURN, count=10000)
            if u.reg_read(UC_X86_REG_EIP) != RETURN:
                raise AssertionError('Original FloatToText did not return')
            result = bytes(u.mem_read(out, u.reg_read(UC_X86_REG_EAX) * 2)).decode('utf-16le')
            records.append({'numerator': Fraction(value).numerator, 'denominator': Fraction(value).denominator,
                            'fahrenheit': fahrenheit, 'delta': delta, 'text': result})
        return records

    def averages(self):
        """Every possible byte high+low sum through the original Math.Ceil."""
        u = self.machine()
        rows = []
        for total in range(511):
            u.mem_write(0x21008000, struct.pack('<I', RETURN) + extended(Fraction(total, 2)) + b'\0\0')
            u.reg_write(UC_X86_REG_ESP, 0x21008000)
            u.emu_start(self.t.by_name['Math.Ceil'], RETURN, count=1000)
            if u.reg_read(UC_X86_REG_EIP) != RETURN:
                raise AssertionError('Original Math.Ceil did not return')
            rows.append([total, u.reg_read(UC_X86_REG_EAX)])
        return rows

    def body(self, case, units):
        t, u = self.t, self.machine()
        lines, hooks = [], {}
        next_string = 0x20080000
        methods = [t.method(BODIES[case['kind']]), t.method('CIS_TDocumentorCommon.DisplayZones'),
                   t.method('CIS_TDocumentorCommon.DisplaySENTEMPProInterval'), t.method('CIS_jcl.CelsiusToFahrenheit')]

        def put(address, value):
            u.mem_write(address, struct.pack('<I', value & 0xffffffff))

        def get(address):
            return struct.unpack('<I', u.mem_read(address, 4))[0]

        def text(pointer):
            return '' if not pointer else bytes(u.mem_read(pointer, get(pointer - 4) * 2)).decode('utf-16le')

        def write(destination, value):
            nonlocal next_string
            if not value:
                put(destination, 0)
                return
            encoded = value.encode('utf-16le')
            pointer = next_string + 12
            next_string += (len(encoded) + 31) & ~15
            u.mem_write(pointer - 12, struct.pack('<HHiI', 1200, 2, -1, len(encoded) // 2) + encoded + b'\0\0')
            put(destination, pointer)

        def finish(value=None, pop=0):
            if value is not None:
                u.reg_write(UC_X86_REG_EAX, value & 0xffffffff)
            stack = u.reg_read(UC_X86_REG_ESP)
            u.reg_write(UC_X86_REG_EIP, get(stack))
            u.reg_write(UC_X86_REG_ESP, stack + 4 + pop)

        def bind(suffix, callback):
            matches = [address for address, names in t.symbols.items() if any(name.endswith(suffix) for name in names)]
            if not matches:
                raise ValueError('Missing original symbol: ' + suffix)
            for address in matches:
                hooks[address] = callback

        def scalar(suffix, field):
            bind(suffix, lambda a, d, c: finish(case[field]))

        groups, reverse = {}, {}

        def group(application, address):
            key = application, address
            if key not in groups:
                groups[key] = 0x20010000 + len(groups) * 0x100
                reverse[groups[key]] = key
            return groups[key]

        app = case.get('application', 172)
        for prefix in ('TSENTEMP', 'TSENTEMPPro'):
            for getter, field in [('GetControlGroup' if prefix == 'TSENTEMP' else 'GetControlledGroup', 'control'), ('GetEnableGroup', 'enable'), ('GetEconomyGroup', 'economy')]:
                bind(prefix + '.' + getter, lambda a, d, c, field=field: finish(group(app, case[field])))
            scalar(prefix + '.GetModeHeating', 'heating')
        for getter, field in [('GetTargetTemperature', 'target'), ('GetMarginTemperature', 'margin'), ('GetEconomyOffset', 'offset')]:
            scalar('TSENTEMP.' + getter, field)
        for getter, field in [('GetSensorMode', 'mode'), ('GetTargetTemperatureHigh', 'high'), ('GetTargetTemperatureLow', 'low'), ('GetEconomyMargin', 'offset'), ('GetDeviceID', 'device_id')]:
            scalar('TSENTEMPPro.' + getter, field)
        bind('TSENTEMPPro.GetBroadcastGroup', lambda a, d, c: finish(group(app, case['broadcast_group'])))
        bind('TSENTEMPPro.GetBroadcastTriggerGroup', lambda a, d, c: finish(group(202, case['trigger'])))
        bind('TSENTEMPPro.GetBroadcastActionSelector', lambda a, d, c: finish(0x20030000))
        bind('TSENTEMPPro.GetZones', lambda a, d, c: finish(case['zones']))
        bind('TSENTEMPPro.GetIntervalEnabled', lambda a, d, c: finish(case['interval'] is not None))
        bind('TSENTEMPPro.GetBroadcastInterval', lambda a, d, c: finish(case['interval']))
        bind('TSENTEMPPro.GetThresholdEnabled', lambda a, d, c: finish(case['threshold'] is not None))
        bind('TSENTEMPPro.GetTemperatureThreshold', lambda a, d, c: finish(int(Fraction(case['threshold']) * 2)))
        scalar('TCBusDigitalTemperatureSensor.GetDeviceID', 'device_id')
        channels = {0x20040000 + n * 0x100: channel for n, channel in enumerate(case.get('channels', []))}
        bind('TDigitalTemperatureSensorChannelCollection.GetItem', lambda a, d, c: finish(list(channels)[d]))
        bind('TDigitalTemperatureSensorChannel.GetChannelName', lambda a, d, c: (write(d, channels[a]['name']), finish()))
        bind('TDigitalTemperatureSensorChannel.GetChannelMode', lambda a, d, c: finish(0 if channels[a]['hvac'] else 1))
        bind('TDigitalTemperatureSensorChannel.GetCommunicationGroup', lambda a, d, c: finish(group(172, channels[a]['group'])))
        bind('TDigitalTemperatureSensorChannel.GetZones', lambda a, d, c: finish(channels[a]['zones']))
        bind('TDigitalTemperatureSensorChannel.GetBroadcastInterval', lambda a, d, c: finish(channels[a]['interval']))

        def float_get(a, d, c):
            u.mem_write(SHIM + 0x100, struct.pack('<d', float(Fraction(channels[a]['threshold']))))
            u.mem_write(SHIM, b'\xdd\x05' + struct.pack('<I', SHIM + 0x100) + b'\xc3')
            u.reg_write(UC_X86_REG_EIP, SHIM)
        bind('TDigitalTemperatureSensorChannel.GetBroadcastThreshold', float_get)
        bind('TZones.GetZones', lambda a, d, c: finish(a))
        bind('TUnitTypeDocumentor.DocumentHTML', lambda a, d, c: finish())
        bind('System.@IsClass', lambda a, d, c: finish(1))
        bind('TCBusGroup.IsUnused', lambda a, d, c: finish(reverse[a][1] == 255))
        bind('TDocumentorCommon.DisplayHTMLGroup', lambda a, d, c: (write(d,
             '&#60;Unused&#62;' if reverse[a][1] == 255 else f'<a href="#254_{reverse[a][0]}_{reverse[a][1]}">Group <{reverse[a][1]}></a>'), finish()))
        bind('TDocumentorCommon.DisplayHTMLLevel', lambda a, d, c: (write(d, f'<a href="#254_202_{case["trigger"]}_{case["selector"]}">Action <{case["selector"]}></a>'), finish()))
        bind('SysUtils.IntToStr', lambda a, d, c: (write(d, str(a if a < 0x80000000 else a - 0x100000000)), finish()))
        hooks[0x619af0] = lambda a, d, c: (write(a, str(struct.unpack('<q', u.mem_read(u.reg_read(UC_X86_REG_ESP) + 4, 8))[0])), finish(pop=8))
        bind('System.LoadResString', lambda a, d, c: (write(d, t.resource(a)), finish()))
        bind('System.@UStrAsg', lambda a, d, c: (write(a, text(d)), finish()))
        bind('System.@UStrLAsg', lambda a, d, c: (write(a, text(d)), finish()))
        bind('System.@UStrCat', lambda a, d, c: (write(a, text(get(a)) + text(d)), finish()))
        bind('System.@UStrCat3', lambda a, d, c: (write(a, text(d) + text(c)), finish()))
        bind('System.@UStrClr', lambda a, d, c: finish())
        bind('System.@UStrArrayClr', lambda a, d, c: finish())

        def concatenate(a, count, c):
            stack = u.reg_read(UC_X86_REG_ESP)
            write(a, ''.join(reversed([text(get(stack + 4 + n * 4)) for n in range(count)])))
            finish(pop=count * 4)
        bind('System.@UStrCatN', concatenate)

        def format_leaf(a, d, c):
            fmt = text(a)
            if fmt.startswith('%.2f'):
                bits = bytes(u.mem_read(get(d), 10))
                significand, exponent = struct.unpack('<QH', bits)
                value = Fraction(significand) * Fraction(2) ** ((exponent & 32767) - 16383 - 63)
                if exponent & 32768:
                    value = -value
                scaled = abs(value) * 100 + Fraction(1, 2)
                number = scaled.numerator // scaled.denominator
                result = ('-' if value < 0 else '') + f'{number // 100}.{number % 100:02d}' + fmt[4:]
            else:
                result = fmt % get(d)
            write(get(u.reg_read(UC_X86_REG_ESP) + 4), result)
            finish(pop=4)
        bind('SysUtils.Format', format_leaf)
        put(STRINGS, STR_VMT)
        put(STR_VMT + 0x38, ADD)
        put(UNIT + 0x1d4, COLLECTION)
        put(COLLECTION, LIST_VMT)
        put(LIST_VMT + 0x58, COUNT)
        preference = get(0x13c3ac8)
        put(preference, 0x20050000)
        put(0x20050020, int(units == 'fahrenheit'))

        def intercept(_u, pc, _size, _data):
            a, d, c = (u.reg_read(r) for r in (UC_X86_REG_EAX, UC_X86_REG_EDX, UC_X86_REG_ECX))
            if pc in hooks:
                hooks[pc](a, d, c)
            elif pc == ADD:
                lines.append(text(d))
                finish(len(lines) - 1)
            elif pc == COUNT:
                finish(len(channels))
            elif pc == 0x604ed0:  # Execute the pinned System.@ROUND leaf.
                pass
            elif not (SHIM <= pc < SHIM + 16 or 0x604ed0 <= pc < 0x604f10 or any(m['start'] <= pc < m['end'] for m in methods)):
                raise AssertionError(f'Unexpected original execution at {pc:#x}')
        u.hook_add(UC_HOOK_CODE, intercept)
        put(0x21008000, RETURN)
        for register, number in ((UC_X86_REG_EAX, 0x20000600), (UC_X86_REG_EDX, STRINGS), (UC_X86_REG_ECX, UNIT), (UC_X86_REG_ESP, 0x21008000)):
            u.reg_write(register, number)
        u.emu_start(methods[0]['start'], RETURN, count=200000)
        if u.reg_read(UC_X86_REG_EIP) != RETURN:
            raise AssertionError('Original body did not return')
        return lines


def cases():
    return [dict(kind='SENTEMP', application=56, control=1, enable=2, economy=3, heating=True, target=21, margin=3, offset=5),
            dict(kind='SENTEMP', application=56, control=255, enable=255, economy=255, heating=False, target=10, margin=-3),
            dict(kind='SENTEMPB', application=56, mode=0, control=1, enable=2, economy=3, heating=False, high=50, low=0, offset=20),
            dict(kind='SENTEMPB', application=56, mode=0, control=255, enable=255, economy=255, heating=True, high=1, low=49),
            *[dict(kind='SENTEMPB', application=app, mode=mode, broadcast_group=1, zones=21, device_id=255,
                   trigger=8, selector=11, interval=7, threshold='3/2') for app, mode in ((25, 1), (172, 2), (228, 3))],
            dict(kind='SENTEMPB', application=172, mode=2, broadcast_group=255, zones=0, trigger=255, interval=None, threshold=None),
            dict(kind='SENTEMP4', device_id=255, channels=[
                dict(name='Raw <name>', hvac=True, group=1, zones=31, interval=60, threshold='1/8'),
                dict(name='Channel 2', hvac=False, group=255, zones=0, interval=2550, threshold='255/8'),
                dict(name='Channel 3', hvac=False, group=255, zones=0, interval=10, threshold='1/2'),
                dict(name='Fourth', hvac=True, group=2, zones=0, interval=70, threshold='3/8')])]


def capture(exe, map_file):
    probe = Probe(exe, map_file)
    numbers = [(Fraction(n, 8), fahrenheit, False) for fahrenheit in (False, True) for n in range(256)]
    numbers += [(Fraction(n, 2), fahrenheit, True) for fahrenheit in (False, True) for n in range(1, 33)]
    rows = [{**case, 'units': units, 'lines': probe.body(case, units)} for case in cases() for units in ('celsius', 'fahrenheit')]
    return {'format': 'cbus-project-documentor-temperature-original-v1', 'exe_sha256': EXE_SHA256, 'map_sha256': MAP_SHA256,
            'original_methods_executed': True, 'original_loader_executed': False, 'original_generated_page_compared': False,
            'boundary': 'Three original bodies, DisplayZones, DisplaySENTEMPProInterval, CelsiusToFahrenheit, ROUND; synthetic getters, common HTML and string/Format leaves. Independent original FloatToText/FloatToDecimal comparisons cover every bounded sensor threshold under period-decimal preference. No original PP loader, project, GUI, network or hardware.',
            'methods': {name: {key: hex(m[key]) if key in ('start', 'end') else m[key] for key in ('start', 'end', 'sha256')}
                        for name in (*BODIES.values(), 'CIS_TDocumentorCommon.DisplayZones', 'CIS_TDocumentorCommon.DisplaySENTEMPProInterval',
                                     'CIS_jcl.CelsiusToFahrenheit', 'SysUtils.FloatToText', 'SysUtils.FloatToDecimal', 'Math.Ceil')
                        for m in [probe.t.method(name)]},
            'cases': rows, 'numeric': probe.numeric(numbers), 'ceil_half_sums': probe.averages()}


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--exe', type=Path, required=True)
    parser.add_argument('--map', type=Path, required=True)
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    report = capture(args.exe, args.map)
    args.output.write_text(json.dumps(report, indent=2) + '\n')
    print(json.dumps({'body_calls': len(report['cases']), 'numeric_calls': len(report['numeric']), 'ceil_calls': len(report['ceil_half_sums'])}))
