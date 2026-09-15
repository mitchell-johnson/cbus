# Bounded eDLT USB DFU protocol and simulator

The CLI can inspect DFU status records, decode idle-state vendor command headers, inspect a DFU image container and produce an offline binary transfer plan. The independent memory simulator accepts synthetic internal-flash program/read/erase/check operations and external-flash operations at address zero. The original x86 vendor DLL successfully programs, verifies and erases synthetic bytes against this simulator. There is no USB adapter or firmware installation command, and no physical device or vendor firmware payload was accessed in these tests.

This is a bounded part of firmware tooling, not accepted Toolkit firmware-update parity. [Firmware diagnostics](firmware-diagnostics.md) covers the separately tested serial identification and package directory metadata. [Earlier updater research](firmware-research.md) records the original .NET process workflow. The compact results and source hashes are in [dfu-acceptance-summary.json](dfu-acceptance-summary.json).

## Exact source and evidence boundary

Toolkit 1.18 supplies `Firmware/eDLTFirmware/dfuprog.exe`, `usb_drivers/i386/lmdfu_edlt.dll`, its amd64 equivalent, `lmusbdll.dll` and `edlt_dfu.inf`. Their original hashes are retained in the compact report. The research harness executes unmodified x86 instructions using Unicorn 2.1.4 and pefile 2024.8.26, with fake process memory and explicit Endpoint0/runtime services. It never loads a Windows USB driver. The native image tests use a four-byte synthetic payload, not an extracted archive image.

The INF explicitly explains that the eDLT interface GUID changed because its DFU protocol changes are incompatible with the Stellaris tools. It selects VID`166A`, PID`0501`, interface`00`, with interface GUID`8EADE805-42A0-4801-8D10-B6863476C146`. Both vendor DLLs contain that GUID. x86 `LMDFUDeviceOpen` at`0x1000FB80` supplies this identity to `InitializeDeviceByIndex`, searches for interface class`FE`/subclass`01`, distinguishes protocol2 as DFU mode, and reads the functional descriptor. That enumeration path has been inspected, not run against a USB device.

The generic TI protocol provides useful primary references for USB request numbers and the original seven commands. Its definitions do not establish eDLT compatibility. See [TI's USBDFU header](https://software-dl.ti.com/simplelink/esd/simplelink_msp432e4_sdk/4.20.00.12/docs/usblib/msp432e4/api-guide-html/html/usbdfu_8h_source.html) and [Tiva application update using USB DFU](https://www.ti.com/lit/an/spma054/spma054.pdf). The vendor binary controls all eDLT-specific claims below.

## Exports and native entry points

The original x86 library exports 15 functions. The amd64 DLL exports the same names; only x86 machine code is executed in the current acceptance harness.

| Export | x86 virtual address |
|---|---|
| LMDFUInit | 0x1000F2A0 |
| LMDFUDeviceOpen | 0x1000FB80 |
| LMDFUDeviceClose | 0x100103C0 |
| LMDFUDeviceStringGet | 0x1000EAA0 |
| LMDFUDeviceASCIIStringGet | 0x10010420 |
| LMDFUParamsGet | 0x1000F1F0 |
| LMDFUDownload | 0x10010280 |
| LMDFUDownloadBin | 0x10010050 |
| LMDFUErase | 0x1000F9C0 |
| LMDFUUpload | 0x1000F710 |
| LMDFUIsValidImage | 0x1000E940 |
| LMDFUStatusGet | 0x1000F180 |
| LMDFUErrorStringGet | 0x1000E3B0 |
| LMDFUBlankCheck | 0x1000F8C0 |
| LMDFUModeSwitch | 0x1000E350 |

The observed x86 stdcall signatures include:

```text
DownloadBin(handle, bytes, length, address, verify, notification_window, external)
Erase(handle, address, length, verify, notification_window, external)
BlankCheck(handle, address, length, external)
ParamsGet(handle, output, external)
```

`lmusbdll.Endpoint0Transfer`, imported at`0x10011110`, receives `(handle,bmRequestType,bRequest,wValue,wIndex,wLength,buffer,transferredLengthPointer)`. The harness substitutes only this transport and specified C/Windows runtime services; the command generation, splitting, polling, image checksum and verification loops execute from the original binary.

## Requests, commands and state

DNLOAD uses request type`21`, request1; UPLOAD uses`A1`, request2; GETSTATUS uses`A1`, request3. All numbers in this paragraph are hexadecimal. DNLOAD and UPLOAD share one 16-bit block counter in the vendor handle, incremented before each request. Status queries use value0. The extension query is`A1/42`, value`0023`, length4, requiring bytes`4D4C0100`. Its subsequent INFO response contains 22 bytes. USB functional-descriptor transfer size bounds each data block.

GETSTATUS must have exactly six bytes: status, a three-byte little-endian polling delay in milliseconds, state and string index. The Python parser rejects missing bytes and unknown status/state codes. It exposes native error mappings without claiming a successful status verifies flash contents.

| Operation | Internal opcode | External opcode | Observed header |
|---|---:|---:|---|
| Program | 1 | 8 | opcode, zero, address/1024 as uint16, byte length as uint32 |
| Read | 2 | 9 | same as program |
| Blank check | 3 | 10 | same eight-byte shape; external address units conflict between wrappers |
| Erase | 4 | 11 | opcode, zero, address/block size as uint16, block count as uint16, two zero bytes |
| Info | 5 | 12 | opcode followed by seven zero bytes |
| Binary mode | 6 | 13 | **eleven** bytes: opcode, uint32 boolean, six zero bytes |
| Reset | 7 | none | known TI command; eDLT device reset behavior remains unaccepted |

Internal erase blocks are1024 bytes; external erase blocks are65536 bytes. For external CHECK, `LMDFUBlankCheck` encodes `address/65536`, while the verification branch of `LMDFUErase` encodes `address/1024`. The decoder therefore reports any nonzero external CHECK address as unsupported and ambiguous. The independent simulator restricts all external operations to address zero. The decoder can still describe other external command headers, without asserting simulator or hardware support.

Literal original-DLL vectors include:

```text
0100080000050000       internal program: address8192, length1280
[1024 data bytes]      first program data block
[256 data bytes]       second program data block
[zero-byte DNLOAD]     termination
0601000000000000000000 enable binary readback
0200080000050000       internal readback: address8192, length1280
0600000000000000000000 disable binary readback
0B00000001000000       external erase: address0, length65536
```

The native send helper at`0x1000ED00` polls while state is3 or4, honoring the 24-bit delay. It has no overall deadline visible in that loop. The execution harness supplies a CPU/time budget; the Python offline API performs no polling. Any future transport must have bounded deadlines and preserve the last transfer outcome without replaying mutations.

The native idle preparation helper at`0x1000F2B0` handles states as follows:

| Initial state | Observed action/result |
|---|---|
| 0,1,8 | return unsupported(-5) |
| 2 | no action |
| 3,5,9 | ABORT |
| 4 | sleep, then ABORT |
| 6,7 | require a nonzero attributes byte, sleep, then ABORT |
| 10 | CLRSTATUS |
| 11 in an explicit malformed fixture | return success with no action |

The simulator's busy cycle is deliberately deterministic: one busy response then the final state. This is a test-device model, not a claim about physical flash timing. Its partial writes remain observable after interruption; only a complete-length stream followed by termination increments its completed-program count. It protects the explicitly configured application boundary, checks capacity, requires erase before changing programmed zero bits back to one, and rejects unsupported requests. Erase and program content are checked directly in independent peer memory, beyond the host return code.

## Container and payload inspection

The native suffix writer at`0x1000EF80` appends16 bytes: device BCD, PID, VID, DFU version`0100`, signature`UFD`, suffix length16 and a little-endian reflected CRC32. Its CRC uses initial`FFFFFFFF` with no final complement; the completed file has native remainder0. Equivalently, `zlib.crc32(complete_file)==0xFFFFFFFF`.

`LMDFUIsValidImage` at`0x1000E940` recognizes a TI prefix when byte0 is1 and its length at bytes4..7 equals file length minus suffix length minus8. It accepts a valid generic suffix without that prefix. Native VID/PID checks require exact equality: explicit `FFFF` wildcard values fail against the fixture IDs. The device BCD is not compared; `FFFF` and an arbitrary `1234` both pass the original reader. The Python inspector distinguishes suffix/CRC/optional VID/PID validity from its narrower supported container format:16-byte suffix, DFU1.0, native TI prefix, zero reserved byte and nonempty payload. Neither result validates machine instructions, the Cortex vector table, a hardware variant, image signatures, rollback compatibility or bootability. Raw main/font binary contents remain opaque.

Synthetic exact vector, produced by the original suffix writer and accepted by its original reader:

```text
0100080004000000 DEADBEEF 000101056A16000155464410 187FF0D3
```

## Original process arguments and important quirks

The `dfuprog` argument switch at`0x4011F0` selects the second character of `-` or `/` options. Source flags include`a,b,c,d,e,f,h,i,l,m,q,r,s,u,v,w,x,z,?`; address, length and index call a numeric conversion routine, and filename consumes the next argument. This is static argument research, not a full command-line parser acceptance harness.

The original .NET `UpgradeFirmware` selects main offset`0x2000` for Stellaris/PCI and`0x4000` for Tiva variants. It invokes mode switch, optional external-font erase/write, mode switch again, then main write/reset. Its font erase calculation is literally `(file_length /65537+1)*65536`. No encrypted package was extracted to test this workflow.

Several source quirks prevent treating native success as verified installation:

- `LMDFUModeSwitch` ignores a failed DETACH transfer, closes its handle and returns0. Re-enumeration must be separate evidence.
- Direct `GetStatus` at`0x1000EC00` accepts a successful short transfer, and even a failed transfer when reported length is6. The send-and-poll helper uses stricter checks. Python only accepts a complete status record.
- Idle preparation accepts any nonzero attributes byte in the manifest branch, not specifically the expected flag, and reconstructs the high polling byte with shift8 instead of16. Its malformed state11 fixture also returns0.
- Erase encodes block count as `length/(block_size-1)`, not `length/block_size`. An internal2MiB request yields2050 blocks rather than2048. The simulator checks the actual encoded range.
- The download dispatcher at`0x401B50` auto-detects DFU content. A valid TI-prefixed container uses `LMDFUDownload`; a valid suffix-only container has its suffix removed for binary download. CRC/signature failures can fall back to raw binary download. VID/PID mismatch is a separate stop unless`-d`. The Python container inspector never makes that fallback.
- Help describes`-s` as skipping verification, but the switch sets global`0x412B6C` to1 and the original wrapper at`0x402450` forwards it directly as `DownloadBin.verify=1`. The default forwards0. Four original wrapper executions confirm both values for both flash selections. The original GUI's normal calls omit`-s`, so those arguments alone do not request the readback loop tested here.
- The original DLL's verification cleanup sends binary-disable after a comparison failure; a cleanup return can be ignored. The independent corruption case retains native verification error`-14` and proves the final binary-mode state separately.

## Reproduction and acceptance

From the project root:

```sh
CBUS_DFU_DLL=research/vendor/toolkit/app/Firmware/eDLTFirmware/usb_drivers/i386/lmdfu_edlt.dll \
CBUS_DFU_REPORT=research/runtime/dfu-acceptance.json \
.venv/bin/python -m unittest discover -s tests -p test_dfu.py -v

.venv/bin/python research/native_dfu_probe.py \
  --dll research/vendor/toolkit/app/Firmware/eDLTFirmware/usb_drivers/i386/lmdfu_edlt.dll \
  --output research/runtime/native-dfu-probe.json
```

The focused suite passes 21 tests with no skips when the explicit native DLL gate is set. Evidence includes44 scripted original-control cases, twelve image-reader vectors and one original suffix-writer vector, four original process-wrapper argument vectors, two independent program/verify/erase/check workflows, and one deliberately corrupted readback. The binary bytes in transcripts are synthetic. The suite also covers literal independent headers, bounds, protected bootloader space, incomplete streams, invalid sequencing and erase requirements. Research dependencies are explicit in the package's research extra.

The bounded [injected Endpoint0 client](dfu-transport.md) now adds strict descriptor validation, original `DeviceOpen` fixtures, deadlines and independent readback outcomes. Remaining work includes physical enumeration, x64 behavior comparison, exact reset/re-enumeration and interrupted-transfer semantics. Nonzero external flash addressing requires device-side bootloader evidence. Actual package payload validation, USB hardware compatibility, automatic firmware installation, NCC firmware writes and a recovery workflow remain unimplemented or unaccepted.
