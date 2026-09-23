00cebbe4: 55                       push ebp
00cebbe5: 8bec                     mov ebp, esp
00cebbe7: 83c4f4                   add esp, -0xc
00cebbea: 894df4                   mov dword ptr [ebp - 0xc], ecx
00cebbed: 8955f8                   mov dword ptr [ebp - 8], edx
00cebbf0: 8945fc                   mov dword ptr [ebp - 4], eax
00cebbf3: 8b55f8                   mov edx, dword ptr [ebp - 8]
00cebbf6: 8b4df4                   mov ecx, dword ptr [ebp - 0xc]
00cebbf9: 8b45fc                   mov eax, dword ptr [ebp - 4]
00cebbfc: e8d7e6fdff               call 0xcca2d8 ; CIS_TCoreNeoInputCGateAgent.TCoreNeoInputCGateAgent.AgentLoad
00cebc01: 8be5                     mov esp, ebp
00cebc03: 5d                       pop ebp
00cebc04: c3                       ret 
00cebc05: 8d4000                   lea eax, [eax]
