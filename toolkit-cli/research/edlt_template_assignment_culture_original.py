"""Reproduce the retained two-culture original PPAttribute setter observation."""
import argparse
import os
from pathlib import Path
import subprocess

from edlt_template_original import DLL_SHA256, PINS, digest


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    for option in ('logic-dll', 'mono-root', 'output'):
        parser.add_argument('--' + option, required=True)
    args = parser.parse_args()
    dll, mono, out = Path(args.logic_dll).resolve(), Path(args.mono_root).resolve(), Path(args.output).absolute()
    source = Path(__file__).with_name('edlt_template_assignment_culture_probe.cs')
    assert digest(dll) == DLL_SHA256, 'Unpinned original assembly'
    assert digest(source) == 'b1fb8bc08548be47d96a8e030d09cad1859f987ae2a4cff66b3a0f136176dc1c', 'Changed probe source'
    for name, expected in PINS.items():
        assert digest(mono / name) == expected, 'Unpinned owned runtime'
    out.mkdir()
    env = {k: v for k, v in os.environ.items() if not k.startswith(('CBUS_', 'MONO_', 'DYLD_'))}
    env.update(MONO_CFG_DIR=str(mono / 'etc'), MONO_PATH=str(dll.parent) + os.pathsep + str(mono / 'lib/mono/4.5'), DYLD_FALLBACK_LIBRARY_PATH=str(mono / 'lib'))
    base = ['/usr/bin/sandbox-exec', '-p', '(version 1)(allow default)(deny network*)', str(mono / 'bin/mono-sgen64')]
    commands = [('compile', [str(mono / 'lib/mono/4.5/mcs.exe'), '-r:' + str(dll), '-out:' + str(out / 'Review.exe'), str(source)]), ('run', [str(out / 'Review.exe')])]
    for name, command in commands:
        result = subprocess.run(base + command, env=env, capture_output=True, timeout=15)
        (out / (name + '.stdout')).write_bytes(result.stdout)
        (out / (name + '.stderr')).write_bytes(result.stderr)
        if result.returncode:
            raise RuntimeError('Culture probe failed: ' + name)
    assert result.stdout == 'en-US\t0xI\ntr-TR\t0x\u0130\n'.encode(), 'Original culture output changed'
    assert digest(dll) == DLL_SHA256, 'Original assembly changed'
    print('Verified two original culture cases; no form, service or device used.')


if __name__ == '__main__':
    main()
