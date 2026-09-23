00f28f80: 55                       push ebp
00f28f81: 8bec                     mov ebp, esp
00f28f83: 83c4f8                   add esp, -8
00f28f86: 8945fc                   mov dword ptr [ebp - 4], eax
00f28f89: 33c9                     xor ecx, ecx
00f28f8b: baff000000               mov edx, 0xff
00f28f90: 8b45fc                   mov eax, dword ptr [ebp - 4]
00f28f93: e8c0ffffff               call 0xf28f58 ; CIS_TCommonCBus.TCBusGroupManager.FindGroupByAddress
00f28f98: 85c0                     test eax, eax
00f28f9a: 740e                     je 0xf28faa
00f28f9c: 8b45fc                   mov eax, dword ptr [ebp - 4]
00f28f9f: 8b10                     mov edx, dword ptr [eax]
00f28fa1: ff5258                   call dword ptr [edx + 0x58]
00f28fa4: 48                       dec eax
00f28fa5: 8945f8                   mov dword ptr [ebp - 8], eax
00f28fa8: eb0b                     jmp 0xf28fb5
00f28faa: 8b45fc                   mov eax, dword ptr [ebp - 4]
00f28fad: 8b10                     mov edx, dword ptr [eax]
00f28faf: ff5258                   call dword ptr [edx + 0x58]
00f28fb2: 8945f8                   mov dword ptr [ebp - 8], eax
00f28fb5: 8b45f8                   mov eax, dword ptr [ebp - 8]
00f28fb8: 59                       pop ecx
00f28fb9: 59                       pop ecx
00f28fba: 5d                       pop ebp
00f28fbb: c3                       ret 
