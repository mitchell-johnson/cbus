00cb8b84: 55                       push ebp
00cb8b85: 8bec                     mov ebp, esp
00cb8b87: 51                       push ecx
00cb8b88: 8945fc                   mov dword ptr [ebp - 4], eax
00cb8b8b: 8b45fc                   mov eax, dword ptr [ebp - 4]
00cb8b8e: e88dcbffff               call 0xcb5720 ; CIS_TCBusUnitCGateAgent.TCBusUnitCGateAgent.GetCBusUnit
00cb8b93: c680d400000001           mov byte ptr [eax + 0xd4], 1
00cb8b9a: 8b45fc                   mov eax, dword ptr [ebp - 4]
00cb8b9d: e87ecbffff               call 0xcb5720 ; CIS_TCBusUnitCGateAgent.TCBusUnitCGateAgent.GetCBusUnit
00cb8ba2: 80b8b800000000           cmp byte ptr [eax + 0xb8], 0
00cb8ba9: 0f858f000000             jne 0xcb8c3e
00cb8baf: 8b45fc                   mov eax, dword ptr [ebp - 4]
00cb8bb2: 8b10                     mov edx, dword ptr [eax]
00cb8bb4: ff9200010000             call dword ptr [edx + 0x100]
00cb8bba: 8b45fc                   mov eax, dword ptr [ebp - 4]
00cb8bbd: e85ecbffff               call 0xcb5720 ; CIS_TCBusUnitCGateAgent.TCBusUnitCGateAgent.GetCBusUnit
00cb8bc2: c680b800000001           mov byte ptr [eax + 0xb8], 1
00cb8bc9: 8b45fc                   mov eax, dword ptr [ebp - 4]
00cb8bcc: e84fcbffff               call 0xcb5720 ; CIS_TCBusUnitCGateAgent.TCBusUnitCGateAgent.GetCBusUnit
00cb8bd1: c680b900000001           mov byte ptr [eax + 0xb9], 1
00cb8bd8: 33c0                     xor eax, eax
00cb8bda: 55                       push ebp
00cb8bdb: 68378ccb00               push 0xcb8c37
00cb8be0: 64ff30                   push dword ptr fs:[eax]
00cb8be3: 648920                   mov dword ptr fs:[eax], esp
00cb8be6: 8b45fc                   mov eax, dword ptr [ebp - 4]
00cb8be9: 8b10                     mov edx, dword ptr [eax]
00cb8beb: ff92e4000000             call dword ptr [edx + 0xe4]
00cb8bf1: 50                       push eax
00cb8bf2: 8b45fc                   mov eax, dword ptr [ebp - 4]
00cb8bf5: e826cbffff               call 0xcb5720 ; CIS_TCBusUnitCGateAgent.TCBusUnitCGateAgent.GetCBusUnit
00cb8bfa: 5a                       pop edx
00cb8bfb: e814742700               call 0xf30014 ; CIS_TCommonCBus.TCBUSUnit.SetApplicationObject
00cb8c00: 8b45fc                   mov eax, dword ptr [ebp - 4]
00cb8c03: 8b10                     mov edx, dword ptr [eax]
00cb8c05: ff92e8000000             call dword ptr [edx + 0xe8]
00cb8c0b: 50                       push eax
00cb8c0c: 8b45fc                   mov eax, dword ptr [ebp - 4]
00cb8c0f: e80ccbffff               call 0xcb5720 ; CIS_TCBusUnitCGateAgent.TCBusUnitCGateAgent.GetCBusUnit
00cb8c14: 5a                       pop edx
00cb8c15: e81e742700               call 0xf30038 ; CIS_TCommonCBus.TCBUSUnit.SetApplication2Object
00cb8c1a: 33c0                     xor eax, eax
00cb8c1c: 5a                       pop edx
00cb8c1d: 59                       pop ecx
00cb8c1e: 59                       pop ecx
00cb8c1f: 648910                   mov dword ptr fs:[eax], edx
00cb8c22: 683e8ccb00               push 0xcb8c3e
00cb8c27: 8b45fc                   mov eax, dword ptr [ebp - 4]
00cb8c2a: e8f1caffff               call 0xcb5720 ; CIS_TCBusUnitCGateAgent.TCBusUnitCGateAgent.GetCBusUnit
00cb8c2f: c680b900000000           mov byte ptr [eax + 0xb9], 0
00cb8c36: c3                       ret 
00cb8c37: e9e8df94ff               jmp 0x606c24 ; System.@HandleFinally
00cb8c3c: ebe9                     jmp 0xcb8c27
00cb8c3e: 59                       pop ecx
00cb8c3f: 5d                       pop ebp
00cb8c40: c3                       ret 
00cb8c41: 8d4000                   lea eax, [eax]
