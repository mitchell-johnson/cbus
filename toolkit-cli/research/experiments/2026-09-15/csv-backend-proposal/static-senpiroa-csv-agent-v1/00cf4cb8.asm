00cf4cb8: 55                       push ebp
00cf4cb9: 8bec                     mov ebp, esp
00cf4cbb: 83c4f4                   add esp, -0xc
00cf4cbe: 894df4                   mov dword ptr [ebp - 0xc], ecx
00cf4cc1: 8955f8                   mov dword ptr [ebp - 8], edx
00cf4cc4: 8945fc                   mov dword ptr [ebp - 4], eax
00cf4cc7: 8b45f4                   mov eax, dword ptr [ebp - 0xc]
00cf4cca: 50                       push eax
00cf4ccb: 8b4df8                   mov ecx, dword ptr [ebp - 8]
00cf4cce: ba2c4dcf00               mov edx, 0xcf4d2c
00cf4cd3: 8b45fc                   mov eax, dword ptr [ebp - 4]
00cf4cd6: e891a7afff               call 0x7ef46c ; CIS_TCustomFlashObject.TFlashAgent.IsInVerbs
00cf4cdb: 84c0                     test al, al
00cf4cdd: 740a                     je 0xcf4ce9
00cf4cdf: 8b45fc                   mov eax, dword ptr [ebp - 4]
00cf4ce2: e8e12f0000               call 0xcf7cc8 ; CIS_TCBusST7SensorCGateAgent.TCBusST7MultisensorCGateAgent.QueryAmbientLight
00cf4ce7: eb30                     jmp 0xcf4d19
00cf4ce9: 8b45f4                   mov eax, dword ptr [ebp - 0xc]
00cf4cec: 50                       push eax
00cf4ced: 8b4df8                   mov ecx, dword ptr [ebp - 8]
00cf4cf0: ba704dcf00               mov edx, 0xcf4d70
00cf4cf5: 8b45fc                   mov eax, dword ptr [ebp - 4]
00cf4cf8: e86fa7afff               call 0x7ef46c ; CIS_TCustomFlashObject.TFlashAgent.IsInVerbs
00cf4cfd: 84c0                     test al, al
00cf4cff: 740a                     je 0xcf4d0b
00cf4d01: 8b45fc                   mov eax, dword ptr [ebp - 4]
00cf4d04: e8d7310000               call 0xcf7ee0 ; CIS_TCBusST7SensorCGateAgent.TCBusST7MultisensorCGateAgent.QueryPotentiometerReadings
00cf4d09: eb0e                     jmp 0xcf4d19
00cf4d0b: 8b55f8                   mov edx, dword ptr [ebp - 8]
00cf4d0e: 8b4df4                   mov ecx, dword ptr [ebp - 0xc]
00cf4d11: 8b45fc                   mov eax, dword ptr [ebp - 4]
00cf4d14: e8cb6effff               call 0xcebbe4 ; CIS_TCBusNeoInputCGateAgent.TCBusNeoInputCGateAgent.AgentLoad
00cf4d19: 8be5                     mov esp, ebp
00cf4d1b: 5d                       pop ebp
00cf4d1c: c3                       ret 
00cf4d1d: 0000                     add byte ptr [eax], al
00cf4d1f: 00b0040200ff             add byte ptr [eax - 0xfffdfc], dh
