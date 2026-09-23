00f28938: 55                       push ebp
00f28939: 8bec                     mov ebp, esp
00f2893b: 83c4f8                   add esp, -8
00f2893e: 8945fc                   mov dword ptr [ebp - 4], eax
00f28941: 8b45fc                   mov eax, dword ptr [ebp - 4]
00f28944: e8a7ffffff               call 0xf288f0 ; CIS_TCommonCBus.TCBusGroupManager.Add
00f28949: 8945f8                   mov dword ptr [ebp - 8], eax
00f2894c: 8b45f8                   mov eax, dword ptr [ebp - 8]
00f2894f: 59                       pop ecx
00f28950: 59                       pop ecx
00f28951: 5d                       pop ebp
00f28952: c3                       ret 
00f28953: 90                       nop 
