00cc7bf0: 55                       push ebp
00cc7bf1: 8bec                     mov ebp, esp
00cc7bf3: 83c4f0                   add esp, -0x10
00cc7bf6: 8945fc                   mov dword ptr [ebp - 4], eax
00cc7bf9: 8b45fc                   mov eax, dword ptr [ebp - 4]
00cc7bfc: e8830fffff               call 0xcb8b84 ; CIS_TCBusUnitCGateAgent.TCBusUnitCGateAgent.LoadGroups
00cc7c01: 8b45fc                   mov eax, dword ptr [ebp - 4]
00cc7c04: e843f8ffff               call 0xcc744c ; CIS_TCoreKeyInputCGateAgent.TCoreKeyInputCGateAgent.CBusUnit
00cc7c09: 80b87001000000           cmp byte ptr [eax + 0x170], 0
00cc7c10: 0f85e9000000             jne 0xcc7cff
00cc7c16: 8b45fc                   mov eax, dword ptr [ebp - 4]
00cc7c19: e82ef8ffff               call 0xcc744c ; CIS_TCoreKeyInputCGateAgent.TCoreKeyInputCGateAgent.CBusUnit
00cc7c1e: 8b80d0000000             mov eax, dword ptr [eax + 0xd0]
00cc7c24: 8b10                     mov edx, dword ptr [eax]
00cc7c26: ff526c                   call dword ptr [edx + 0x6c]
00cc7c29: 8b45fc                   mov eax, dword ptr [ebp - 4]
00cc7c2c: 8b10                     mov edx, dword ptr [eax]
00cc7c2e: ff9218010000             call dword ptr [edx + 0x118]
00cc7c34: 8b45fc                   mov eax, dword ptr [ebp - 4]
00cc7c37: e810f8ffff               call 0xcc744c ; CIS_TCoreKeyInputCGateAgent.TCoreKeyInputCGateAgent.CBusUnit
00cc7c3c: 8b80d0000000             mov eax, dword ptr [eax + 0xd0]
00cc7c42: 8b10                     mov edx, dword ptr [eax]
00cc7c44: ff12                     call dword ptr [edx]
00cc7c46: 33c0                     xor eax, eax
00cc7c48: 55                       push ebp
00cc7c49: 68f07ccc00               push 0xcc7cf0
00cc7c4e: 64ff30                   push dword ptr fs:[eax]
00cc7c51: 648920                   mov dword ptr fs:[eax], esp
00cc7c54: 8b45fc                   mov eax, dword ptr [ebp - 4]
00cc7c57: e8f0f7ffff               call 0xcc744c ; CIS_TCoreKeyInputCGateAgent.TCoreKeyInputCGateAgent.CBusUnit
00cc7c5c: 8b80c8010000             mov eax, dword ptr [eax + 0x1c8]
00cc7c62: 8b10                     mov edx, dword ptr [eax]
00cc7c64: ff5258                   call dword ptr [edx + 0x58]
00cc7c67: 48                       dec eax
00cc7c68: 85c0                     test eax, eax
00cc7c6a: 7c63                     jl 0xcc7ccf
00cc7c6c: 40                       inc eax
00cc7c6d: 8945f0                   mov dword ptr [ebp - 0x10], eax
00cc7c70: c745f800000000           mov dword ptr [ebp - 8], 0
00cc7c77: 8b45fc                   mov eax, dword ptr [ebp - 4]
00cc7c7a: e8cdf7ffff               call 0xcc744c ; CIS_TCoreKeyInputCGateAgent.TCoreKeyInputCGateAgent.CBusUnit
00cc7c7f: 8b80c8010000             mov eax, dword ptr [eax + 0x1c8]
00cc7c85: 8b55f8                   mov edx, dword ptr [ebp - 8]
00cc7c88: e8b3810400               call 0xd0fe40 ; CIS_TInputKey.TInputBlockCollection.GetItem
00cc7c8d: 8945f4                   mov dword ptr [ebp - 0xc], eax
00cc7c90: 8b4df8                   mov ecx, dword ptr [ebp - 8]
00cc7c93: 8b55f4                   mov edx, dword ptr [ebp - 0xc]
00cc7c96: 8b45fc                   mov eax, dword ptr [ebp - 4]
00cc7c99: e846f9ffff               call 0xcc75e4 ; CIS_TCoreKeyInputCGateAgent.TCoreKeyInputCGateAgent.GetBlockGroup
00cc7c9e: 8b45f4                   mov eax, dword ptr [ebp - 0xc]
00cc7ca1: e8c2730400               call 0xd0f068 ; CIS_TInputKey.TInputBlock.GetGroup
00cc7ca6: 85c0                     test eax, eax
00cc7ca8: 741d                     je 0xcc7cc7
00cc7caa: 8b45f4                   mov eax, dword ptr [ebp - 0xc]
00cc7cad: e8b6730400               call 0xd0f068 ; CIS_TInputKey.TInputBlock.GetGroup
00cc7cb2: 50                       push eax
00cc7cb3: 8b45fc                   mov eax, dword ptr [ebp - 4]
00cc7cb6: e891f7ffff               call 0xcc744c ; CIS_TCoreKeyInputCGateAgent.TCoreKeyInputCGateAgent.CBusUnit
00cc7cbb: 8b80d0000000             mov eax, dword ptr [eax + 0xd0]
00cc7cc1: 5a                       pop edx
00cc7cc2: 8b08                     mov ecx, dword ptr [eax]
00cc7cc4: ff5168                   call dword ptr [ecx + 0x68]
00cc7cc7: ff45f8                   inc dword ptr [ebp - 8]
00cc7cca: ff4df0                   dec dword ptr [ebp - 0x10]
00cc7ccd: 75a8                     jne 0xcc7c77
00cc7ccf: 33c0                     xor eax, eax
00cc7cd1: 5a                       pop edx
00cc7cd2: 59                       pop ecx
00cc7cd3: 59                       pop ecx
00cc7cd4: 648910                   mov dword ptr fs:[eax], edx
00cc7cd7: 68f77ccc00               push 0xcc7cf7
00cc7cdc: 8b45fc                   mov eax, dword ptr [ebp - 4]
00cc7cdf: e868f7ffff               call 0xcc744c ; CIS_TCoreKeyInputCGateAgent.TCoreKeyInputCGateAgent.CBusUnit
00cc7ce4: 8b80d0000000             mov eax, dword ptr [eax + 0xd0]
00cc7cea: 8b10                     mov edx, dword ptr [eax]
00cc7cec: ff5208                   call dword ptr [edx + 8]
00cc7cef: c3                       ret 
00cc7cf0: e92fef93ff               jmp 0x606c24 ; System.@HandleFinally
00cc7cf5: ebe5                     jmp 0xcc7cdc
00cc7cf7: 8b45fc                   mov eax, dword ptr [ebp - 4]
00cc7cfa: e8f9f9ffff               call 0xcc76f8 ; CIS_TCoreKeyInputCGateAgent.TCoreKeyInputCGateAgent.GetKeyBlocks
00cc7cff: 8be5                     mov esp, ebp
00cc7d01: 5d                       pop ebp
00cc7d02: c3                       ret 
00cc7d03: 90                       nop 
