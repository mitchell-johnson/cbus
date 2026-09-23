# Offline network calculator

`cbus_toolkit.calculator` reproduces the database calculation performed by C-Gate 3.4.0 build 2001's `CALCULATOR TEST`. It loads a user-supplied `cbusunits.xml`; the catalogue is not distributed in this package. It computes supply and consumption in milliamps, parallel impedance, known and unknown catalogue counts, and the catalogue's pass/fail conditions. This is a catalogue calculation, without cable resistance or physical measurements.

```python
from cbus_toolkit.calculator import CalculatorCatalog, CalculatorUnit

catalog = CalculatorCatalog.load("/path/to/cbusunits.xml")
result = catalog.calculate([
    CalculatorUnit("5034N", "KEY4"),
    CalculatorUnit("5500BUR", "BURDEN"),
    CalculatorUnit("5500PS", "POWER"),
])
assert result.passed
assert result.current_supply_ma == 350
assert result.current_consumption_ma == 18
assert result.impedance_ohms == 944
```

`CalculatorUnit` also accepts `burden`, `switchable_supply_enabled`, and ordered `parameters` pairs. Mapping inputs use the same field names. A burden can be specified directly or through the first matching `Burden` / `HardwareBurdenMarker` parameter. Results retain the source catalogue SHA-256 and exact floating-point impedance, alongside native rounded impedance and explicit failure reasons. Zero total conductance raises `CalculatorError`; the native server returns internal error 500 for empty or unknown-only networks.

The implementation preserves native edge behavior:

- Catalogue numbers and switchable UnitType membership are case-sensitive. Exact names take precedence over the longest matching prefix followed by `*`. Alternative catalogue numbers are split on semicolons without trimming. Later duplicate entries overwrite earlier ones; a lone `*` is not a universal fallback.
- For a UnitType declared switchable anywhere in the final catalogue lookup map, an enabled supply contributes only its switchable supply current; a disabled supply contributes only its switchable demand. The normal current fields are not added in that branch.
- Only the exact burden text `"0"` disables burden. Values such as `"0x0"` and `"00"` enable it. KEYGL5 and SENTEMP4 skip burden, with case-insensitive matching for those two exceptions.
- Unknown catalogue entries contribute only to the unknown count. Catalogue impedance below 10 ohms is ignored. Each enabled burden contributes conductance of 0.001 siemens.
- Native pass/fail checks use unrounded impedance, demand no greater than supply, supply no greater than the catalogue maximum, impedance within both catalogue limits, and zero unknown entries. Missing or incomplete limits produce a failed result. Current additions retain Java signed 32-bit overflow behavior.

Inputs are limited to 10,000 units and catalogue XML to the existing unitspec reader's bounded, DTD-rejecting input policy. Invalid integer metadata is rejected. Native null UnitType and malformed database-object failures are represented as input validation errors; this module does not create database records or reproduce the native side effect of updating a unit's `BurdenEnabled` field.

The implementation was checked against the native `A.java`, `B.java`, and `cW.java` from the local decompilation archive documented in [catalogue acceptance](catalog-acceptance.md). Twelve independent fixture tests cover arithmetic, native edge behavior, and input validation. A separate opt-in test compares fourteen closed-network cases with the real vendor server, including two zero-conductance errors. It creates and removes a unique disposable project and never opens its network.

```sh
CBUS_CGATE_TEST_HOST=127.0.0.1 .venv/bin/python -m unittest discover -s tests -p test_calculator.py -v
```

Use `CBUS_CATALOG_PATH` when the matching server catalogue is located outside the local research directory. Passing these checks establishes the described calculator scope; it does not establish physical network correctness or all Toolkit functionality.
