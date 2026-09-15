# Native UNRAVEL fallback audit

The exact C-Gate 3.4 operation `NET UNRAVELUNIT <network> 255 MATCHDB` can move a unit to another free address if its internal serial scan becomes unknown. Successful external preflight and `Retries=0` do not prevent this logical fallback. The typed `SerialCommissioning` helper now performs database serial matching in Python and uses the fixed-destination scalar `SET <source> Address <target>` operation instead.

The frozen 606-test checkpoint `c73ea5f3cc00` predates this discovery and mitigation. Its passing native happy-path tests did not cover a failed internal serial scan. Historical MATCHDB acceptance records remain available and are explicitly separate from current scalar acceptance.

## Exact source and bytecode evidence

The source is the vendor `cgate.jar` distributed with Toolkit 1.18.0.2754/C-Gate 3.4.0.2001, plus its case-preserved decompilation in `research/vendor/cgate-decompiled.tar`.

- `kY.java` implements the explicit-address-subset command. It creates a `CBusNetworkUnraveller`, passes the selected source addresses and MATCHDB flag, then can report 200 after the managed workflow completes.
- `CBusNetworkUnraveller` marks address 255 for clearing and reserves 0/1 from ordinary free-address selection. `bQ.java` loads the database serial/address mapping. Healthy singletons at ordinary addresses are normally left alone.
- In `CBusNetworkUnraveller.a(UnitUnravelStack,bP,boolean,boolean,boolean)`, bytecode offsets 436–476 recognize the all-ones serial and set local 12, the fallback-required flag. The later fallback calls `a(bP,boolean,boolean,boolean)`.
- That fallback calls `bQ.a(boolean)` to choose a free address; bytecode offset 94 of the latter `a` method performs this lookup and offset 136 invokes the legacy address move. This selection is independent of the caller's desired database target when the serial cannot be matched.
- The ordinary single-unit move calls `dc.a(old,new,!clear,true,false,0)`: ignore negative acknowledgements, do not independently verify an absent response in this path, and no outer `dc` retry. `dc` bytecode 401–550 handles ignored negative ACKs;632–818 selects either absence verification or a presumed-success path. The resulting runtime model update and native 200 are not proof of the physical result.
- Both `cu` protected STORE and `co` broadcast set the underlying command retry field `aW.q=0`. This does not disable higher-level UNRAVEL control flow.
- A potentially misleading decompilation placed the `co` logical attempt decrement under the Wireless condition. The original bytecode at offset 415 of `CBusNetworkUnraveller.b(cn,int,int)` unconditionally decrements local 4 before checking Wireless. The wired branch starts with one logical broadcast attempt; wireless starts with three. This audit found no evidence for an infinite wired broadcast loop.

The bounded bytecode reader and decoded listings are in ignored `research/runtime/inspect_unravel_bytecode.py` and `unravel-retry-bytecode.txt`. They inspect the original class files without executing or modifying vendor classes.

## Isolated fault observations

All probes used fresh synthetic KEYE1 firmware 2.5.00 fixtures, unique disposable projects, a database counterpart at 6, a complete healthy preflight inventory, explicit Retries=0 and no physical hardware. No Python commissioning command was replayed.

| Fault during raw native UNRAVEL | Protected STOREs | Actual result | Independent observation |
|---|---:|---|---|
| Valid negative ACK, no physical mutation | 1 to 6 | Unit remains 255; native returns 200 | Not moved; typed wrapper at that checkpoint reported uncertainty |
| PCI confirmation but no CAL response, no mutation | 1 to 6 | Unit remains 255; native returns 200 | Not moved; wrapper reported uncertainty |
| Physical move, CAL response dropped | 1 to 6 | Unit at 6; native returns 200 | Confirmed at 6 |
| Positive ACK from source 7 without mutation | 1 to 6 | Unit remains 255; native returns 200 | Not moved; wrapper reported uncertainty |
| One valid all-ones serial response during the internal scan | 1 to 2 | Actual known-serial unit moves 255→2; native returns 200 | Target 6 absent; expected serial independently located at 2 |

The last case is retained as a deterministic native regression in `tests/test_serial_commissioning.py`. Its [durable report](native-matchdb-internal-scan-fallback.json) records the explicit raw command, full wire trace, unchanged database XML, physical state persistence, one injected internal serial response, no unsupported frames and successful cleanup. The simulator's real serial was never changed; only one valid IDENTIFY4 response was faulted after helper preflight. Explicitly empty slots 2/6 allowed the actual vendor fallback and its subsequent absence probes to complete.

These five cases do not establish a universal bound on all UNRAVEL actions. Source control flow also has repeated known-serial processing and recursive address clearing. Ambiguous/multiple responses, address cycles and changing database mappings remain outside the verified subset.

## Mitigation and remaining options

The scalar alternative was independently probed from source 255 under the same serial/database/empty-target guards. It moved to 6 with one protected STORE and no internal UNRAVEL serial scan. A negative ACK without mutation returned an error. A lost CAL after an actual move was resolved by native destination checking and independent serial observation. The current typed helper reuses `PhysicalAddressing.apply` for this operation and preserves its zero-retry and no-reconnect/no-reverse-write behavior.

Recovery now reports the full observed identity inventory and every observed address matching the expected serial. It can explain an unexpected location without automatically moving that unit again. There is no invented transaction lock or claim that preflight prevents every concurrent physical change. Raw NET UNRAVEL/MATCHDB remains a broader vendor operation with the documented fallback behavior.

The smallest useful next broadcast extension is an explicit fixture with two distinct, known serials sharing unprogrammed address 255 and two independently empty database targets. Native source selects `co` for multiple serials at one address. The simulator must represent physical identity separately from its address before that test is credible: its current one-unit-per-address dictionary cannot represent a collision. A fixture would need independent per-serial memory, two correlated IDENTIFY4 replies, per-serial broadcast movement, persistence of the remaining duplicate, and post-split serial verification. Occupied destinations, cycles and local PCI/bridge relocation should remain excluded. This is an identified next test scope, not implemented functionality.
