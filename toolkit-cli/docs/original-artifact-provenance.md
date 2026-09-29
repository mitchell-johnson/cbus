# Original Toolkit and C-Gate artifact provenance

Issue [#18](https://github.com/mitchell-johnson/cbus/issues/18) tracks the native input pin for the Toolkit 1.18.0.2754 / C-Gate 3.4.0.2001 parity program. The [hash-only manifest](../research/original-artifact-provenance.json) records 25 artifact groups from four private roots: one extracted installer audit, one decoded-unit-specification directory, the owned macOS JDK that runs native C-Gate, and the owned macOS Mono runtime that runs the original FirmwareUpdater oracle. No executable, unit specification, updater package, certificate, site project, secret, or absolute local path is committed by this inventory.

The installer groups are the Toolkit installer, its EXE and MAP, all 27 top-level EXE/DLL files, its CHM and extracted help, the nested C-Gate installer, launcher, JAR, 31 library files, bundled 332-file JRE, encrypted specifications and DALI catalogue, FirmwareUpdater, eDLT firmware packages and drivers, and the SESU installer and Toolkit update configuration. The separate groups are the 280 decoded XML specifications; the owned Temurin JDK's `bin/java`, `bin/javac`, `release` file and whole 510-file `Contents/Home` tree; and the owned Mono 6.12.0.206 `mono-sgen64`, `mcs.exe` and whole framework-version tree. Version provenance is read without execution: the Toolkit and FirmwareUpdater PE fixed FileVersion resources, the C-Gate JAR manifest Implementation-Version/Build-Number, the bundled JRE and owned JDK `release` metadata (the JDK must be `11.0.32.1+1`, `Temurin-11.0.32.1+1`, `aarch64`, image type `JDK`), and Mono's `VERSION` file. SESU 3.0.7 is only a filename claim; its bytes are pinned, but this checker does not establish an embedded version.

Install the Toolkit `research` extra (including `pefile` and `cryptography`) and provide the four private roots. The decoded directory should be the exact vendor catalogue, not a site project:

```sh
cd toolkit-cli
python -m pip install -e '.[research]'
python research/pin_original_artifacts.py verify \
  --installer-root "$CBUS_ORIGINAL_INSTALLER_AUDIT" \
  --decoded-spec-dir "$CBUS_UNITSPEC_DIR" \
  --native-jdk-home "$(dirname "$(dirname "$CBUS_CGATE_JAVA")")" \
  --native-mono-root "$CBUS_MONO_MACOS_ROOT"
```

`verify` exits nonzero if a required file/tree is missing, changed, symlinked, or has unexpected file membership, if an embedded version is different, or if the decoded specifications are not a fresh decode of the encrypted originals; the error names each mismatched group or section. The tree digest is SHA-256 over sorted relative UTF-8 filenames, decimal byte sizes, and each file's SHA-256, prefixed by `cbus-original-artifact-tree-v1\n`. This binds file membership and contents without publishing the files or their individual names; empty directories are not part of the digest. The Mono framework payload contains 310 relative and absolute symlinks, so its group uses the separate `cbus-original-artifact-tree-links-v1\n` domain, in which each link contributes its literal target instead of being followed; every other tree still rejects links. To deliberately repin a reviewed replacement, run `create` with the same arguments and review the manifest diff; the fixed recipe and target-version checks remain enforced.

## Native gate runtime pin

`research/release-gates/native.json` pins `CBUS_CGATE_JAVA` and `CBUS_CGATE_JAVAC` to the `native-jdk-java` and `native-jdk-javac` digests, and pins the JDK home two levels above each launcher to the `native-jdk-home` tree digest. `research/release_gate.py` fails before running pytest with `Required provision does not match its pinned SHA-256` for a substituted launcher (including `/usr/bin/java`), or `runtime home does not match its pin` when any JDK file is added, removed or changed. A unit test keeps those gate values equal to this manifest. The receipt records only digests and counts.

## Specification derivation

`verify` reruns the committed `research/decode_unitspec.py` over the 280 pinned encrypted `.xml.es` files into a temporary private directory. The decoder authenticates every AES-GCM input before writing, and the fresh output must be byte-identical, by tree digest, to the decoded directory. The public `specification_derivation` section records the decoder digest, the decoded count and `pairs_sha256`, a digest over each sorted encrypted-input/decoded-output SHA-256 pair; it contains no names or content. Changing the decoder invalidates this receipt until the derivation is rerun and repinned. On 30 September 2026 the derivation passed for all 280 files.

## Installer extraction chain

`research/reproduce_installer_extraction.py` rebuilds the installer audit from the pinned Toolkit `Setup.exe` without running it: innoextract unpacks the Toolkit Inno Setup installer into `extracted-20260926`, then the nested C-Gate installer into `cgate-extracted-20260926`, and 7-Zip unpacks `Toolkit Help.chm` into `help-20260926`. It refuses any other `Setup.exe`, then recomputes every installer-rooted record and prints tool versions, tool digests and counts.

```sh
python research/reproduce_installer_extraction.py \
  --setup /private/path/CBusToolkit-1.18.0.2754-CGate-3.4.0.2001-Setup.exe \
  --output /private/new-audit-root
```

On 30 September 2026, innoextract 1.9 and 7-Zip 26.03 (arm64) reproduced all 17 installer-rooted records (5,016 files) byte-identically, and a full `verify` over the rebuilt root passed. The installers report Inno Setup data version 6.1.0, newer than innoextract 1.9's documented 6.0.5 support; the byte-identical comparison is the evidence that this extraction is correct, and the tool digests identify the run. The other nested installers (`vcredist`, `ControlSystemsIPUtilitySetup` and the SESU self-extractor) are not unpacked or pinned beyond the SESU file.

## Publisher signatures

`osslsigncode` is not installed on the owned macOS runner, and the Homebrew `signtool` there is the NSS JAR signer, not Microsoft's. `research/authenticode_check.py` is an offline pure-Python (`cryptography` and the standard library) consistency check. It recomputes each PE's Authenticode image digest, compares it with the signed `SpcIndirectDataContent`, checks the PKCS#9 message digest and the signer's signature over the authenticated attributes, and verifies each certificate link to a root in the macOS system root keychain.

On 30 September 2026 it passed for the Toolkit `Setup.exe`, the nested C-Gate installer, `CBusToolkit.exe`, `cgate.exe` and the SESU self-extractor. Each is signed by `SCHNEIDER ELECTRIC USA, INC.` (Andover, Massachusetts) with an Extended Validation code-signing certificate that expires on 9 February 2027. `FirmwareUpdater.exe` has no embedded Authenticode signature. Targeted tampering of the image bytes or of the signed content made the check fail.

This check is not Windows trust policy. It does not evaluate revocation, the code-signing EKU/policy, certificate validity at the countersigned timestamp, or nested secondary signatures. Policy-grade publisher verification still needs Windows `signtool verify /pa /all` (or `Get-AuthenticodeSignature`) on an isolated Windows profile. The Windows bridge's 25-file manifest is recorded separately in [Windows provenance](windows-provenance.md).

## Limits

This is **input provenance**, not native or physical acceptance. Native acceptance still needs an owned, disposable C-Gate service; isolated Windows profiles/projects; and case-level original comparison receipts. The Windows-policy signature check above is still outstanding. `CBUS_DFU_DLL`, required by a separate firmware oracle path, has not been located in this extracted set and remains unpinned. `CBUS_MONO_MACOS_ROOT` is pinned here, but the firmware oracle does not yet check that pin itself. The manifest therefore does not satisfy all of #18's acceptance criteria and must not be used to infer Toolkit feature parity.
