00c9d34c: 55                       push ebp
00c9d34d: 8bec                     mov ebp, esp
00c9d34f: 83c4ec                   add esp, -0x14
00c9d352: 53                       push ebx
00c9d353: 8945fc                   mov dword ptr [ebp - 4], eax
00c9d356: b8d4d3c900               mov eax, 0xc9d3d4
00c9d35b: 8945ec                   mov dword ptr [ebp - 0x14], eax
00c9d35e: b8f4d3c900               mov eax, 0xc9d3f4
00c9d363: 8945f0                   mov dword ptr [ebp - 0x10], eax
00c9d366: 8d55ec                   lea edx, [ebp - 0x14]
00c9d369: b901000000               mov ecx, 1
00c9d36e: 8b45fc                   mov eax, dword ptr [ebp - 4]
00c9d371: 8b18                     mov ebx, dword ptr [eax]
00c9d373: ff9388000000             call dword ptr [ebx + 0x88]
00c9d379: baff000000               mov edx, 0xff
00c9d37e: 8b45fc                   mov eax, dword ptr [ebp - 4]
00c9d381: 8b8060010000             mov eax, dword ptr [eax + 0x160]
00c9d387: e820c897ff               call 0x619bac ; SysUtils.StrToIntDef
00c9d38c: 8945f4                   mov dword ptr [ebp - 0xc], eax
00c9d38f: 8b45fc                   mov eax, dword ptr [ebp - 4]
00c9d392: 8b10                     mov edx, dword ptr [eax]
00c9d394: ff92b0000000             call dword ptr [edx + 0xb0]
00c9d39a: 8b80b4000000             mov eax, dword ptr [eax + 0xb4]
00c9d3a0: b101                     mov cl, 1
00c9d3a2: 8b55f4                   mov edx, dword ptr [ebp - 0xc]
00c9d3a5: e8beb72800               call 0xf28b68 ; CIS_TCommonCBus.TCBusGroupManager.GroupByAddress
00c9d3aa: 8bd0                     mov edx, eax
00c9d3ac: 8b45fc                   mov eax, dword ptr [ebp - 4]
00c9d3af: e8c8010000               call 0xc9d57c ; CIS_TCBusInputUnit.TCBusInputUnit.SetAreaGroup
00c9d3b4: 8b45fc                   mov eax, dword ptr [ebp - 4]
00c9d3b7: e86cffffff               call 0xc9d328 ; CIS_TCBusInputUnit.TCBusInputUnit.GetAreaGroup
00c9d3bc: 8945f8                   mov dword ptr [ebp - 8], eax
00c9d3bf: 8b45f8                   mov eax, dword ptr [ebp - 8]
00c9d3c2: 5b                       pop ebx
00c9d3c3: 8be5                     mov esp, ebp
00c9d3c5: 5d                       pop ebp
00c9d3c6: c3                       ret 
00c9d3c7: 00b0040200ff             add byte ptr [eax - 0xfffdfc], dh
