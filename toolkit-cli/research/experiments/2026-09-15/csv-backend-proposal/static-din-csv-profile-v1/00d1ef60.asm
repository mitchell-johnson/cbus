00d1ef60: 55                       push ebp
00d1ef61: 8bec                     mov ebp, esp
00d1ef63: 83c4ec                   add esp, -0x14
00d1ef66: 53                       push ebx
00d1ef67: 8945fc                   mov dword ptr [ebp - 4], eax
00d1ef6a: b8e8efd100               mov eax, 0xd1efe8
00d1ef6f: 8945ec                   mov dword ptr [ebp - 0x14], eax
00d1ef72: b808f0d100               mov eax, 0xd1f008
00d1ef77: 8945f0                   mov dword ptr [ebp - 0x10], eax
00d1ef7a: 8d55ec                   lea edx, [ebp - 0x14]
00d1ef7d: b901000000               mov ecx, 1
00d1ef82: 8b45fc                   mov eax, dword ptr [ebp - 4]
00d1ef85: 8b18                     mov ebx, dword ptr [eax]
00d1ef87: ff9388000000             call dword ptr [ebx + 0x88]
00d1ef8d: baff000000               mov edx, 0xff
00d1ef92: 8b45fc                   mov eax, dword ptr [ebp - 4]
00d1ef95: 8b8060010000             mov eax, dword ptr [eax + 0x160]
00d1ef9b: e80cac8fff               call 0x619bac ; SysUtils.StrToIntDef
00d1efa0: 8945f4                   mov dword ptr [ebp - 0xc], eax
00d1efa3: 8b45fc                   mov eax, dword ptr [ebp - 4]
00d1efa6: 8b10                     mov edx, dword ptr [eax]
00d1efa8: ff92b0000000             call dword ptr [edx + 0xb0]
00d1efae: 8b80b4000000             mov eax, dword ptr [eax + 0xb4]
00d1efb4: b101                     mov cl, 1
00d1efb6: 8b55f4                   mov edx, dword ptr [ebp - 0xc]
00d1efb9: e8aa9b2000               call 0xf28b68 ; CIS_TCommonCBus.TCBusGroupManager.GroupByAddress
00d1efbe: 8bd0                     mov edx, eax
00d1efc0: 8b45fc                   mov eax, dword ptr [ebp - 4]
00d1efc3: e830fdffff               call 0xd1ecf8 ; CIS_TCBusDINRailOutputUnit.TCBusDINRailOutputUnit.SetAreaAddress
00d1efc8: 8b45fc                   mov eax, dword ptr [ebp - 4]
00d1efcb: e844f9ffff               call 0xd1e914 ; CIS_TCBusDINRailOutputUnit.TCBusDINRailOutputUnit.GetAreaAddress
00d1efd0: 8945f8                   mov dword ptr [ebp - 8], eax
00d1efd3: 8b45f8                   mov eax, dword ptr [ebp - 8]
00d1efd6: 5b                       pop ebx
00d1efd7: 8be5                     mov esp, ebp
00d1efd9: 5d                       pop ebp
00d1efda: c3                       ret 
00d1efdb: 00b0040200ff             add byte ptr [eax - 0xfffdfc], dh
