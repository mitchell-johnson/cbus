"""Toolkit 1.18 thermostat integer temperature conversions.

The explicit unit preference selects Celsius or Fahrenheit. These scalar
functions preserve original x87 rounding, double stores, Int32 wrapping and
method-specific clamps; they do not read preferences or edit a thermostat.
"""
from fractions import Fraction

METHODS = ('CGate16thDegreeToQuarterDegreeTempOffset', 'CGateTempToHalfDegreesTempOffset', 'CGateTempToTempOffset', 'CGateTempToTempOffsetWithShift', 'CGateTempToUnitTemp', 'CGateTempToWholeDegreesTemp', 'HalfDegreesTempOffsetToCGateTemp', 'QuarterDegreesTempOffsetToCGateTemp', 'SimpleCGateTempToUnitTemp', 'SimpleUnitTempToCGateTemp', 'TempOffsetToCGateTemp', 'TempOffsetWithShiftToCGateTemp', 'UnitTempToCGateTemp', 'WholeDegreesTempToCGateTemp')

_FACTOR = Fraction(8301034833169298227, 4611686018427387904)
_QUARTER_FACTOR = Fraction(9445655302942975905, 9223372036854775808)

def _i32(value):
    value &= 0xffffffff
    return value - 0x100000000 if value & 0x80000000 else value

def _binary_round(value, precision=64):
    """Finite normal binary round-to-nearest/even at the original precision."""
    value=Fraction(value)
    if not value:return value
    sign=-1 if value < 0 else 1
    magnitude=abs(value)
    exponent=magnitude.numerator.bit_length()-magnitude.denominator.bit_length()
    if magnitude < Fraction(2)**exponent:exponent-=1
    quantum=Fraction(2)**(exponent-precision+1)
    return sign*round(magnitude/quantum)*quantum

def _celsius_to_fahrenheit(value):
    # Parameter and original helper result use double storage; x87 operations64.
    value=_binary_round(value,53)
    return _binary_round(_binary_round(_binary_round(_FACTOR*value)+32),53)

def _fahrenheit_to_celsius(value):
    value=_binary_round(value,53)
    return _binary_round(_binary_round(_binary_round(value-32)/_FACTOR),53)

def convert_temperature(method: str, value: int, *, units: str) -> int:
    """Apply one named original conversion to a signed 32-bit integer.

    ``units`` must be exactly ``"celsius"`` or ``"fahrenheit"``. The fourteen
    case-sensitive method names in METHODS retain their original Toolkit names.
    Booleans, numeric/text subclasses and implicit unit defaults are rejected.
    """
    if type(method) is not str or method not in METHODS:
        raise ValueError('Unknown thermostat temperature conversion method')
    if type(value) is not int or not -(1 << 31) <= value < (1 << 31):
        raise ValueError('Temperature input must be a signed 32-bit integer')
    if type(units) is not str or units not in ('celsius', 'fahrenheit'):
        raise ValueError('Temperature units must be celsius or fahrenheit')
    fahrenheit = units == 'fahrenheit'
    if method=='SimpleCGateTempToUnitTemp':
        return _i32(round(_celsius_to_fahrenheit(value))) if fahrenheit else value
    if method=='SimpleUnitTempToCGateTemp':
        return _i32(round(_fahrenheit_to_celsius(value))) if fahrenheit else value
    if method in ('CGateTempToUnitTemp','CGateTempToWholeDegreesTemp'):
        source=_i32(value+80) if method=='CGateTempToUnitTemp' else value
        scaled=_binary_round(Fraction(source,4))
        return _i32(round(_celsius_to_fahrenheit(scaled) if fahrenheit else scaled))
    if method in ('UnitTempToCGateTemp','WholeDegreesTempToCGateTemp'):
        result=_i32(round(_binary_round(_fahrenheit_to_celsius(value)*4))) if fahrenheit else _i32(value<<2)
        if method=='UnitTempToCGateTemp':
            result=_i32(result-80)
            if result<=-128:result=-127
        return result
    if method in ('CGateTempToTempOffset','CGateTempToHalfDegreesTempOffset','CGateTempToTempOffsetWithShift'):
        source=_i32(value+80) if method=='CGateTempToTempOffsetWithShift' else value
        scaled=_binary_round(Fraction(source,4))
        return _i32(round(_binary_round(scaled*_FACTOR) if fahrenheit else scaled))
    if method in ('TempOffsetToCGateTemp','HalfDegreesTempOffsetToCGateTemp','TempOffsetWithShiftToCGateTemp'):
        result=_i32(round(_binary_round(_binary_round(Fraction(value)/_FACTOR)*4))) if fahrenheit else _i32(value<<2)
        return _i32(result-80) if method=='TempOffsetWithShiftToCGateTemp' else result
    if method=='CGate16thDegreeToQuarterDegreeTempOffset':
        if not fahrenheit:return _i32(round(Fraction(value,4)))
        return _i32(round(_binary_round(_binary_round(_binary_round(Fraction(value,8))/_QUARTER_FACTOR)*_FACTOR)))
    if method=='QuarterDegreesTempOffsetToCGateTemp':
        result=_i32(round(_binary_round(_binary_round(_binary_round(Fraction(value)/_FACTOR)*8)*_QUARTER_FACTOR))) if fahrenheit else _i32(value<<2)
        if result==128:result=127
        return min(255,max(-127,result))
    raise ValueError('Unknown original conversion method')
