0122dbf0: 55                       push ebp
0122dbf1: 8bec                     mov ebp, esp
0122dbf3: 83c4f4                   add esp, -0xc
0122dbf6: 894df4                   mov dword ptr [ebp - 0xc], ecx
0122dbf9: 8955f8                   mov dword ptr [ebp - 8], edx
0122dbfc: 8945fc                   mov dword ptr [ebp - 4], eax
0122dbff: 8b55f8                   mov edx, dword ptr [ebp - 8]
0122dc02: 8b4df4                   mov ecx, dword ptr [ebp - 0xc]
0122dc05: 8b45fc                   mov eax, dword ptr [ebp - 4]
0122dc08: e8ff80a8ff               call 0xcb5d0c ; CIS_TCBusUnitCGateAgent.TCBusUnitCGateAgent.AgentLoad
0122dc0d: 8b45f4                   mov eax, dword ptr [ebp - 0xc]
0122dc10: 50                       push eax
0122dc11: 8b4df8                   mov ecx, dword ptr [ebp - 8]
0122dc14: ba40dc2201               mov edx, 0x122dc40
0122dc19: 8b45fc                   mov eax, dword ptr [ebp - 4]
0122dc1c: e84b185cff               call 0x7ef46c ; CIS_TCustomFlashObject.TFlashAgent.IsInVerbs
0122dc21: 84c0                     test al, al
0122dc23: 7408                     je 0x122dc2d
0122dc25: 8b45fc                   mov eax, dword ptr [ebp - 4]
0122dc28: e837140000               call 0x122f064 ; CIS_TDinRailOutputCGateAgent.TBasicDinRailOutputCGateAgent.DoFARQ
0122dc2d: 8be5                     mov esp, ebp
0122dc2f: 5d                       pop ebp
0122dc30: c3                       ret 
0122dc31: 0000                     add byte ptr [eax], al
0122dc33: 00b0040200ff             add byte ptr [eax - 0xfffdfc], dh
