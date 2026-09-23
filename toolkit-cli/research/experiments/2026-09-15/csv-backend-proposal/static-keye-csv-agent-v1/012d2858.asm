012d2858: 55                       push ebp
012d2859: 8bec                     mov ebp, esp
012d285b: 83c4f4                   add esp, -0xc
012d285e: 53                       push ebx
012d285f: 894df4                   mov dword ptr [ebp - 0xc], ecx
012d2862: 8955f8                   mov dword ptr [ebp - 8], edx
012d2865: 8945fc                   mov dword ptr [ebp - 4], eax
012d2868: 8b55f8                   mov edx, dword ptr [ebp - 8]
012d286b: 8b4df4                   mov ecx, dword ptr [ebp - 0xc]
012d286e: 8b45fc                   mov eax, dword ptr [ebp - 4]
012d2871: e86e93a1ff               call 0xcebbe4 ; CIS_TCBusNeoInputCGateAgent.TCBusNeoInputCGateAgent.AgentLoad
012d2876: 8b45f4                   mov eax, dword ptr [ebp - 0xc]
012d2879: 50                       push eax
012d287a: 8b4df8                   mov ecx, dword ptr [ebp - 8]
012d287d: ba44292d01               mov edx, 0x12d2944
012d2882: 8b45fc                   mov eax, dword ptr [ebp - 4]
012d2885: e8e2cb51ff               call 0x7ef46c ; CIS_TCustomFlashObject.TFlashAgent.IsInVerbs
012d288a: 84c0                     test al, al
012d288c: 7425                     je 0x12d28b3
012d288e: 8b45fc                   mov eax, dword ptr [ebp - 4]
012d2891: e816fdffff               call 0x12d25ac ; CIS_TCBusKEYExCGateAgent.TCBusKEYExCGateAgent.LoadKeyMask
012d2896: 8b45fc                   mov eax, dword ptr [ebp - 4]
012d2899: e802030000               call 0x12d2ba0 ; CIS_TCBusKEYExCGateAgent.TCBusKEYExCGateAgent.CBusUnit
012d289e: e8f569bdff               call 0xea9298 ; CIS_TKEYEx.TKEYEx.GetKeyMask
012d28a3: 8bd8                     mov ebx, eax
012d28a5: 8b45fc                   mov eax, dword ptr [ebp - 4]
012d28a8: e8f3020000               call 0x12d2ba0 ; CIS_TCBusKEYExCGateAgent.TCBusKEYExCGateAgent.CBusUnit
012d28ad: 8998bc020000             mov dword ptr [eax + 0x2bc], ebx
012d28b3: 8b45f4                   mov eax, dword ptr [ebp - 0xc]
012d28b6: 50                       push eax
012d28b7: 8b4df8                   mov ecx, dword ptr [ebp - 8]
012d28ba: ba60292d01               mov edx, 0x12d2960
012d28bf: 8b45fc                   mov eax, dword ptr [ebp - 4]
012d28c2: e8a5cb51ff               call 0x7ef46c ; CIS_TCustomFlashObject.TFlashAgent.IsInVerbs
012d28c7: 84c0                     test al, al
012d28c9: 7431                     je 0x12d28fc
012d28cb: 8b45f4                   mov eax, dword ptr [ebp - 0xc]
012d28ce: 50                       push eax
012d28cf: 8b4df8                   mov ecx, dword ptr [ebp - 8]
012d28d2: ba98292d01               mov edx, 0x12d2998
012d28d7: 8b45fc                   mov eax, dword ptr [ebp - 4]
012d28da: e88dcb51ff               call 0x7ef46c ; CIS_TCustomFlashObject.TFlashAgent.IsInVerbs
012d28df: 84c0                     test al, al
012d28e1: 7419                     je 0x12d28fc
012d28e3: 8b45fc                   mov eax, dword ptr [ebp - 4]
012d28e6: e8b5020000               call 0x12d2ba0 ; CIS_TCBusKEYExCGateAgent.TCBusKEYExCGateAgent.CBusUnit
012d28eb: e8cc1bc6ff               call 0xf344bc ; CIS_TCommonCBus.TCBUSUnit.HasMatchingPhysicalUnit
012d28f0: 84c0                     test al, al
012d28f2: 7408                     je 0x12d28fc
012d28f4: 8b45fc                   mov eax, dword ptr [ebp - 4]
012d28f7: e8b0fcffff               call 0x12d25ac ; CIS_TCBusKEYExCGateAgent.TCBusKEYExCGateAgent.LoadKeyMask
012d28fc: 8b45f4                   mov eax, dword ptr [ebp - 0xc]
012d28ff: 50                       push eax
012d2900: 8b4df8                   mov ecx, dword ptr [ebp - 8]
012d2903: bab8292d01               mov edx, 0x12d29b8
012d2908: 8b45fc                   mov eax, dword ptr [ebp - 4]
012d290b: e85ccb51ff               call 0x7ef46c ; CIS_TCustomFlashObject.TFlashAgent.IsInVerbs
012d2910: 84c0                     test al, al
012d2912: 741d                     je 0x12d2931
012d2914: 8b45fc                   mov eax, dword ptr [ebp - 4]
012d2917: e884020000               call 0x12d2ba0 ; CIS_TCBusKEYExCGateAgent.TCBusKEYExCGateAgent.CBusUnit
012d291c: 8b80bc020000             mov eax, dword ptr [eax + 0x2bc]
012d2922: 50                       push eax
012d2923: 8b45fc                   mov eax, dword ptr [ebp - 4]
012d2926: e875020000               call 0x12d2ba0 ; CIS_TCBusKEYExCGateAgent.TCBusKEYExCGateAgent.CBusUnit
012d292b: 5a                       pop edx
012d292c: e88b69bdff               call 0xea92bc ; CIS_TKEYEx.TKEYEx.SetKeyMask
012d2931: 5b                       pop ebx
012d2932: 8be5                     mov esp, ebp
012d2934: 5d                       pop ebp
012d2935: c3                       ret 
012d2936: 0000                     add byte ptr [eax], al
012d2938: b004                     mov al, 4
012d293a: 0200                     add al, byte ptr [eax]
