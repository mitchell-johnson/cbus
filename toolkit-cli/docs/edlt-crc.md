# eDLT configuration CRC

`cbus_toolkit.edlt.configuration_crc(data)` calculates the original Toolkit
configuration CRC: initial value `0xFA50`, polynomial `0x1021`, most significant
bit first, and no final XOR. Existing eDLT planning uses this function for the
global, widget, static text, scene and overall configuration regions.

Exact `bytes` inputs use the standard library's `binascii.crc_hqx`. Previously
accepted `bytes` subclasses keep the existing Python iterator calculation,
including overridden iteration and exceptions. Non-byte inputs retain their
existing rejection. This changes the calculation's implementation without
changing the configuration format or its results.

## Independent verification

The unchanged original `CBusLogicModel.Crc16Ccitt.checkCrc16` was executed for
all 65,536 two-byte inputs and 52 buffers of up to 65,536 bytes. These include
empty input, fixed literals, seeded random data and boundaries around every
configuration CRC region. The original outputs are retained as literal
[vectors](../research/fixtures/edlt-crc-original-vectors.json), with original
DLL, executed probe and actually loaded runtime hashes.

The [focused acceptance](../research/fixtures/edlt-crc-acceptance.json) passed
21 tests on Python 3.13 and 3.10 with no failures, errors or skips. Each run
executes the original 65,588-case comparison afresh and includes the existing
11 pure eDLT widget regressions. Exact source and test inputs were archived
before either run and verified unchanged afterward. Exception tests preserve
the first operation or report-writing interruption when evidence collection
or file closing also fails.

The original method uses integer arithmetic and runs under a pinned, owned
Mono runtime with networking denied. It constructs no model or controls and
does not contact the Windows VM or C-Gate service. This checkpoint is newer
than the frozen 1,725-test wheel. It does not claim exhaustive coverage of all
possible buffers, physical-device validation or a full-application speedup.
