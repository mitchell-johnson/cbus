"""Bounded NumUpDownPercentage arithmetic, independent of WinForms or locale.

Only the original default 0..100 percentage / 0..255 byte domain is exposed.
The two original Decimal operations remain separate; converting a byte to a
percentage and back can therefore lose one, as in the original implementation.
"""
from fractions import Fraction
import re

_MAX_COEFFICIENT = (1 << 96) - 1
_TEXT = re.compile(r'[0-9]{1,3}(?:\.[0-9]{1,28})?\Z', re.ASCII)


def _percentage(text: str) -> Fraction:
    if type(text) is not str or not 1 <= len(text) <= 32 or _TEXT.fullmatch(text) is None:
        raise ValueError('Percentage must be ASCII fixed-point text with 1..3 integer digits and at most 28 fractional digits')
    integer, _, fraction = text.partition('.')
    fraction = fraction.rstrip('0')
    coefficient = int(integer + fraction)
    scale = len(fraction)
    if coefficient > _MAX_COEFFICIENT:
        raise ValueError('Percentage must be exactly representable by a .NET Decimal without rounding the input')
    value = Fraction(coefficient, 10 ** scale)
    if value > 100:
        raise ValueError('Percentage must be from 0 through 100')
    return value


def _rounded_decimal(value: Fraction) -> Fraction:
    # These callers only supply nonnegative values. Select the greatest scale
    # that fits Decimal's 96-bit coefficient, with ties rounded to even.
    for scale in range(28, -1, -1):
        coefficient, remainder = divmod(value.numerator * 10 ** scale, value.denominator)
        twice = remainder * 2
        if twice > value.denominator or (twice == value.denominator and coefficient % 2):
            coefficient += 1
        if coefficient <= _MAX_COEFFICIENT:
            return Fraction(coefficient, 10 ** scale)
    raise OverflowError('Arithmetic result is outside .NET Decimal')


def _text(value: Fraction) -> str:
    for scale in range(29):
        coefficient, remainder = divmod(value.numerator * 10 ** scale, value.denominator)
        if not remainder:
            if not scale:
                return str(coefficient)
            digits = str(coefficient).zfill(scale + 1)
            return digits[:-scale] + '.' + digits[-scale:]
    raise AssertionError('Decimal result has no exact fixed-point representation')


def byte_to_percentage(raw_byte: int) -> str:
    """Return the original setter's percentage as canonical exact decimal text.

    This exposes only raw integer bytes 0..255; it does not emulate configurable
    NumericUpDown bounds, displayed decimal places, bindings or events.
    """
    if type(raw_byte) is not int or not 0 <= raw_byte <= 255:
        raise ValueError('Raw byte must be an integer from 0 through 255')
    # Int32 -> Decimal and multiplication by 100 are exact in this domain.
    return _text(_rounded_decimal(Fraction(raw_byte * 100, 255)))


def percentage_to_byte(percent: str) -> int:
    """Return the original getter result for exact 0..100 decimal text.

    Leading zeros and value-preserving trailing zeros are accepted within the
    bounded grammar. Signs, whitespace, exponents, locale separators, floats,
    and values requiring decimal-input rounding are rejected.
    """
    value = _percentage(percent)
    multiplied = _rounded_decimal(value * 255)
    divided = _rounded_decimal(multiplied / 100)
    return int(divided)
