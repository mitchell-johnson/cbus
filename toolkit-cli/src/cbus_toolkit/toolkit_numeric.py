"""Bounded Toolkit 1.18 JCL integer conversion, independent of preference I/O.

The supported character classification is ASCII, with dot/comma locale pairs.
Arithmetic follows the executable's x87 extended precision instructions using
exact integer ratios. No Python binary float or host locale is involved.
"""

from dataclasses import asdict, dataclass
from fractions import Fraction


class ToolkitNumericConversionError(ValueError):
    """The original filtered text reaches StrToFloat's conversion error."""


class UnsupportedToolkitNumericInput(ValueError):
    """Input or arithmetic is outside the independently established domain."""


@dataclass(frozen=True)
class ToolkitIntegerConversion:
    value: int
    normalized_text: str
    negative: bool
    separators_swapped: bool
    truncated_integer: int
    int32_wrapped: bool
    extended80_hex: str

    def as_dict(self):
        return asdict(self)


def _exponent(value):
    """floor(log2(value)), for a strictly positive exact ratio."""
    exponent = value.numerator.bit_length() - value.denominator.bit_length()
    if exponent >= 0:
        if value.numerator < value.denominator << exponent:
            exponent -= 1
    elif value.numerator << -exponent < value.denominator:
        exponent -= 1
    return exponent


def _round_extended(value):
    """Round a nonnegative ratio to 64 significant bits, nearest/even."""
    if not value:
        return Fraction(0)
    shift = 63 - _exponent(value)
    scaled = value * (1 << shift) if shift >= 0 else value / (1 << -shift)
    quotient, remainder = divmod(scaled.numerator, scaled.denominator)
    doubled = remainder * 2
    if doubled > scaled.denominator or doubled == scaled.denominator and quotient & 1:
        quotient += 1
    return Fraction(quotient, 1 << shift) if shift >= 0 else Fraction(quotient << -shift)


def _extended_bytes(value, negative):
    if not value:
        significand, exponent = 0, 0
    else:
        power = _exponent(value)
        shift = 63 - power
        scaled = value * (1 << shift) if shift >= 0 else value / (1 << -shift)
        assert scaled.denominator == 1
        significand, exponent = scaled.numerator, power + 16383
    return significand.to_bytes(8, 'little') + (exponent | (int(negative) << 15)).to_bytes(2, 'little')


def parse_toolkit_integer(text, *, decimal_separator='.', thousands_separator=','):
    """Return the original JCL conversion for at most 64 ASCII characters.

    Prefix minus signs toggle the sign, locale punctuation may be exchanged,
    and nonnumeric characters are filtered, just as in StrToIntSafe. A rounded
    result whose truncated integer is outside signed 64 bits is unsupported:
    the executable's unmasked x87 exception delivery is not established here.
    The eventual low-32-bit return, including wrap, is preserved and reported.
    """
    if type(text) is not str:
        raise TypeError('text must be a string')
    if len(text) > 64 or not text.isascii() or '\0' in text:
        raise UnsupportedToolkitNumericInput('text must contain at most 64 ASCII characters without NUL')
    if type(decimal_separator) is not str or type(thousands_separator) is not str or (decimal_separator, thousands_separator) not in (('.', ','), (',', '.')):
        raise UnsupportedToolkitNumericInput('only distinct dot/comma locale separator pairs are supported')

    negative, significant, swapped = False, 0, False
    for position, char in enumerate(text, 1):
        if char == '-':
            negative = not negative
        elif char not in ' (+':
            significant, swapped = position, char == thousands_separator
            break
    if not swapped:
        decimal_position = text.find(decimal_separator) + 1
        swapped = decimal_position > significant and (
            text.count(decimal_separator) > 1 or text.find(thousands_separator) + 1 > decimal_position)
    transformed = text.translate(str.maketrans({decimal_separator: thousands_separator, thousands_separator: decimal_separator})) if swapped else text
    normalized = ''.join(char for char in transformed if '0' <= char <= '9' or char == decimal_separator)
    if normalized.startswith(decimal_separator):
        normalized = '0' + normalized
    if normalized.endswith(decimal_separator):
        normalized += '0'
    if normalized.count(decimal_separator) > 1:
        raise ToolkitNumericConversionError('filtered text contains more than one decimal separator')

    accumulator = Fraction(0)
    for char in normalized:
        if char != decimal_separator:
            accumulator = _round_extended(accumulator * 10)
            accumulator = _round_extended(accumulator + ord(char) - ord('0'))
    fractional_digits = len(normalized) - normalized.index(decimal_separator) - 1 if decimal_separator in normalized else 0
    if fractional_digits:
        accumulator = _round_extended(accumulator / _round_extended(Fraction(10 ** (fractional_digits & 31))))
        if fractional_digits >> 5:
            accumulator = _round_extended(accumulator / _round_extended(Fraction(10 ** (32 * (fractional_digits >> 5)))))
    # Empty filtering takes a separate original branch which returns positive0.
    floating_negative = negative and bool(normalized)
    magnitude = accumulator.numerator // accumulator.denominator
    integer = -magnitude if floating_negative else magnitude
    if not -(1 << 63) <= integer < (1 << 63):
        raise UnsupportedToolkitNumericInput('rounded conversion exceeds signed 64-bit truncation; original exception delivery is unverified')
    returned = ((integer + (1 << 31)) % (1 << 32)) - (1 << 31)
    return ToolkitIntegerConversion(returned, normalized, negative, swapped, integer,
                                    returned != integer, _extended_bytes(accumulator, floating_negative).hex())
