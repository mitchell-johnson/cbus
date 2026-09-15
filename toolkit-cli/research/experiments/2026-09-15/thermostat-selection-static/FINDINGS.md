# Original remote schedule selection

Static inspection only, against Toolkit EXE SHA256 `9d01721abab3beb4724511e7d65e39328c0518e0721caa53f4601cded20655ab` and matching MAP. No original instructions or UI calls executed. The primary 12-method report is SHA256 `32cf4aeccf3b53cad6443c82c1283c08ed03fd46e7d94da48a95b4be0cf6157f`; three further dependency disassemblies are linked by `dependent-methods.json`.

`HandleCreateLevelsClick` first calls `RemoteScheduleLevelsRequired`; it invokes `CreateRemoteScheduleLevels` only when that returns true. The required check first reads remote schedule enable. Disabled means false without any group lookup. When enabled, it considers On, Off, then Override. A non-null group whose address is not 255 requires creation when `ZoneLevelsExist` is false. It stops evaluating later groups after the first such result.

`ZoneLevelsExist` checks level addresses 1 through 31 in order, by calling `FindLevelByAddress` with create=false and its fourth argument zero. It stops at the first absent address. It examines address membership; it does not compare level values or labels. `IsUnused` is exactly the integer group address equality with 255.

`RemoteScheduleGroupsSelected` is a separate predicate. It returns true at the first non-null, non-unused On/Off/Override group, without reading remote enable or checking levels. These predicates cannot be substituted for each other.

`CreateRemoteScheduleLevels` itself does not read the enable flag or call the required predicate. It establishes cursor and delay UI state, then visits On, Off, Override in order. Every present, non-unused group receives its matching action wrapper. Each group getter is called once for the null test, again for IsUnused when present, and again by its action wrapper when selected. The wrapper passes the exact action literal Enable, Disable, or Overrd into CreateLevels. Repeated group identities therefore reach CreateLevels repeatedly in this fixed order, preserving the first-created labels through CreateLevels' existing-address behavior.

The outer method's normal finally path calls DelayFinished and resets the cursor, then clears temporary strings. Original UI providers and exception dispatch remain separate work. A supplied-context or native database command that invokes the inner CreateLevels operation directly must describe that scope; merely adding an enable flag does not establish the original button-handler path.

The proposed next original check should execute the two eligibility predicates plus ZoneLevelsExist and IsUnused with explicit stable group/level providers. Cover all four group states (null, unused255, selected with missing levels, selected with all31 addresses), the two enable values, and lazy lookup ordering. Keep any full UI wrapper execution as a separate finite probe.
