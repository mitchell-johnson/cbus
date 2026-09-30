"""Source-pinned RELDN relay array transformations used by Toolkit conversion.

The original routines directly index Delphi int32 arrays.  This boundary admits
complete, well-formed PP images only; it does not emulate out-of-bounds reads or
StrToIntDef's malformed-token fallback.  Output literals and positions are from
Toolkit 1.18.0.2754, not C-Gate's independent CONVERTUNIT mapping table.
"""
from __future__ import annotations

import re


RELAY_FIELDS = ('GroupAddress', 'LogicGA13Associations', 'LogicGA14Associations',
                'LogicGA15Associations', 'LogicGA16Associations')
RELAY_TWEAKERS = ('TTweakerRELDN8_TO_X', 'TTweakerRELDNX_TO_8')
_TOKEN = re.compile(r'[+]?(?:0[xX][0-9a-fA-F]+|\$[0-9a-fA-F]+|[0-9]+)')


def relay_array(name, value):
    """Read one complete source PP field without silently padding/truncating it."""
    size, maximum = (16, 255) if name == 'GroupAddress' else (12, 1)
    if not isinstance(value, str):
        raise ValueError(f'{name} requires a complete numeric PP string')
    tokens = value.split()
    if len(tokens) != size or any(_TOKEN.fullmatch(token) is None for token in tokens):
        raise ValueError(f'{name} requires exactly {size} numeric PP elements')
    result = []
    for token in tokens:
        token = token.lstrip('+')
        number = int(token[1:], 16) if token.startswith('$') else int(token, 16 if token.lower().startswith('0x') else 10)
        if not 0 <= number <= maximum:
            raise ValueError(f'{name} elements must be in 0..{maximum}')
        result.append(number)
    return result


def relay_assignments(tweaker, values):
    """Return the original Group/13/14/15/16 setter sequence as decimal strings."""
    if tweaker not in RELAY_TWEAKERS:
        raise ValueError('Unknown RELDN conversion tweaker')
    # Validate the entire source before yielding any partial assignment sequence.
    arrays = {name: relay_array(name, values.get(name)) for name in RELAY_FIELDS}
    result = []
    for name in RELAY_FIELDS:
        source = arrays[name]
        group = name == 'GroupAddress'
        blank = 255 if group else 0
        if tweaker == 'TTweakerRELDN8_TO_X':
            output = source[1:5] + source[7:11] + [blank] * 4
        else:
            output = [blank] + source[0:4] + [blank] * 2 + source[4:8] + [blank]
        if group:
            output += source[12:16]
        result.append((name, ' '.join(str(number) for number in output), 'repacked from ' + name))
    return tuple(result)
