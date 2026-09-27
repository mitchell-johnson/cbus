# Original Toolkit and C-Gate artifact provenance

Issue [#18](https://github.com/mitchell-johnson/cbus/issues/18) tracks the native input pin for the Toolkit 1.18.0.2754 / C-Gate 3.4.0.2001 parity program. The [hash-only manifest](../research/original-artifact-provenance.json) records 18 artifact groups from one privately extracted installer and one private decoded-unit-specification directory. No executable, unit specification, updater package, certificate, site project, secret, or absolute local path is committed by this inventory.

The manifest includes the Toolkit installer, its EXE and MAP, all 27 top-level EXE/DLL files, its CHM and extracted help, the nested C-Gate installer, launcher, JAR, 31 library files, bundled 332-file JRE, encrypted specifications and DALI catalogue, the separate 280 decoded XML specifications, FirmwareUpdater, eDLT firmware packages and drivers, and the SESU installer and Toolkit update configuration. It reads version provenance without execution: the Toolkit and FirmwareUpdater PE fixed FileVersion resources, C-Gate JAR manifest Implementation-Version/Build-Number, and bundled JRE `release` metadata. SESU 3.0.7 is only a filename claim; its bytes are pinned, but this checker does not establish an embedded version.

Install the Toolkit `research` extra (including `pefile`) and provide the two private roots. The decoded directory should be the exact vendor catalogue, not a site project:

```sh
cd toolkit-cli
python -m pip install -e '.[research]'
python research/pin_original_artifacts.py verify \
  --installer-root "$CBUS_ORIGINAL_INSTALLER_AUDIT" \
  --decoded-spec-dir "$CBUS_UNITSPEC_DIR"
```

`verify` exits nonzero if a required file/tree is missing, changed, symlinked, or has unexpected file membership, or if an embedded version is different. The tree digest is SHA-256 over sorted relative UTF-8 filenames, decimal byte sizes, and each file's SHA-256, prefixed by `cbus-original-artifact-tree-v1\n`. This binds file membership and contents without publishing the files or their individual names; empty directories are not part of the digest. The script also requires the 280 decoded `.xml` basenames to match the encrypted `.xml.es` basenames. To deliberately repin a reviewed replacement installer, run `create` with the same arguments and review the manifest diff; the fixed recipe and target-version checks remain enforced.

This is **input provenance**, not native or physical acceptance. The directory-name match does not prove that every decoded XML was obtained from the matching encrypted file. The current audit also does not independently verify the extraction chain or publisher signature of each nested installer. Native acceptance still needs an owned, disposable C-Gate service; a Java compiler and executable pinned on that runner; isolated Windows profiles/projects; and case-level original comparison receipts. `CBUS_DFU_DLL`, required by a separate firmware oracle path, has not been located in this extracted set and remains unpinned. The manifest therefore does not satisfy all of #18's acceptance criteria and must not be used to infer Toolkit feature parity.
