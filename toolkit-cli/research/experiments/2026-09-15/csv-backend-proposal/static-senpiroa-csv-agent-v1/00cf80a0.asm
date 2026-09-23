00cf80a0: 55                       push ebp
00cf80a1: 8bec                     mov ebp, esp
00cf80a3: 83c4f4                   add esp, -0xc
00cf80a6: 894df4                   mov dword ptr [ebp - 0xc], ecx
00cf80a9: 8955f8                   mov dword ptr [ebp - 8], edx
00cf80ac: 8945fc                   mov dword ptr [ebp - 4], eax
00cf80af: 8b55f8                   mov edx, dword ptr [ebp - 8]
00cf80b2: 8b4df4                   mov ecx, dword ptr [ebp - 0xc]
00cf80b5: 8b45fc                   mov eax, dword ptr [ebp - 4]
00cf80b8: e8fbcbffff               call 0xcf4cb8 ; CIS_TCBusST7SensorCGateAgent.TCBusST7MultisensorCGateAgent.AgentLoad
00cf80bd: 8be5                     mov esp, ebp
00cf80bf: 5d                       pop ebp
00cf80c0: c3                       ret 
00cf80c1: 8d4000                   lea eax, [eax]
