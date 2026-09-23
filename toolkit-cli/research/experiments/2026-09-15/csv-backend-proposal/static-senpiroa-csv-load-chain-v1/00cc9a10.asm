00cc9a10: 55                       push ebp
00cc9a11: 8bec                     mov ebp, esp
00cc9a13: 83c4f4                   add esp, -0xc
00cc9a16: 894df4                   mov dword ptr [ebp - 0xc], ecx
00cc9a19: 8955f8                   mov dword ptr [ebp - 8], edx
00cc9a1c: 8945fc                   mov dword ptr [ebp - 4], eax
00cc9a1f: 8b55f8                   mov edx, dword ptr [ebp - 8]
00cc9a22: 8b4df4                   mov ecx, dword ptr [ebp - 0xc]
00cc9a25: 8b45fc                   mov eax, dword ptr [ebp - 4]
00cc9a28: e8d7c5ffff               call 0xcc6004 ; CIS_TCBusLearnUnitCGateAgent.TCBusLearnUnitCGateAgent.AgentLoad
00cc9a2d: 8be5                     mov esp, ebp
00cc9a2f: 5d                       pop ebp
00cc9a30: c3                       ret 
00cc9a31: 8d4000                   lea eax, [eax]
