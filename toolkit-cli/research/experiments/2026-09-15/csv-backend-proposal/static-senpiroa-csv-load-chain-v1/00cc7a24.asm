00cc7a24: 55                       push ebp
00cc7a25: 8bec                     mov ebp, esp
00cc7a27: b911000000               mov ecx, 0x11
00cc7a2c: 6a00                     push 0
00cc7a2e: 6a00                     push 0
00cc7a30: 49                       dec ecx
00cc7a31: 75f9                     jne 0xcc7a2c
00cc7a33: 51                       push ecx
00cc7a34: 53                       push ebx
00cc7a35: 8945fc                   mov dword ptr [ebp - 4], eax
00cc7a38: 33c0                     xor eax, eax
00cc7a3a: 55                       push ebp
00cc7a3b: 688d7bcc00               push 0xcc7b8d
00cc7a40: 64ff30                   push dword ptr fs:[eax]
00cc7a43: 648920                   mov dword ptr fs:[eax], esp
00cc7a46: 8b45fc                   mov eax, dword ptr [ebp - 4]
00cc7a49: e88610ffff               call 0xcb8ad4 ; CIS_TCBusUnitCGateAgent.TCBusUnitCGateAgent.LoadDBParametersForLoadGroups
00cc7a4e: 8d4de8                   lea ecx, [ebp - 0x18]
00cc7a51: baa87bcc00               mov edx, 0xcc7ba8
00cc7a56: 8b45fc                   mov eax, dword ptr [ebp - 4]
00cc7a59: e8960dffff               call 0xcb87f4 ; CIS_TCBusUnitCGateAgent.TCBusUnitCGateAgent.QuickGetSingleParameter
00cc7a5e: 8b55e8                   mov edx, dword ptr [ebp - 0x18]
00cc7a61: 8d45ec                   lea eax, [ebp - 0x14]
00cc7a64: e80f7b96ff               call 0x62f578 ; Variants.@VarFromUStr
00cc7a69: 8d55ec                   lea edx, [ebp - 0x14]
00cc7a6c: 8b45fc                   mov eax, dword ptr [ebp - 4]
00cc7a6f: 8b8000010000             mov eax, dword ptr [eax + 0x100]
00cc7a75: 8b08                     mov ecx, dword ptr [eax]
00cc7a77: ff517c                   call dword ptr [ecx + 0x7c]
00cc7a7a: 8d55d8                   lea edx, [ebp - 0x28]
00cc7a7d: 8b45fc                   mov eax, dword ptr [ebp - 4]
00cc7a80: 8b8000010000             mov eax, dword ptr [eax + 0x100]
00cc7a86: 8b08                     mov ecx, dword ptr [eax]
00cc7a88: ff5174                   call dword ptr [ecx + 0x74]
00cc7a8b: 8d45d8                   lea eax, [ebp - 0x28]
00cc7a8e: 50                       push eax
00cc7a8f: 8d45c8                   lea eax, [ebp - 0x38]
00cc7a92: 33d2                     xor edx, edx
00cc7a94: e8df7a96ff               call 0x62f578 ; Variants.@VarFromUStr
00cc7a99: 8d55c8                   lea edx, [ebp - 0x38]
00cc7a9c: 58                       pop eax
00cc7a9d: e8bac196ff               call 0x633c5c ; Variants.@VarCmpNE
00cc7aa2: 742c                     je 0xcc7ad0
00cc7aa4: 8d4db4                   lea ecx, [ebp - 0x4c]
00cc7aa7: bad07bcc00               mov edx, 0xcc7bd0
00cc7aac: 8b45fc                   mov eax, dword ptr [ebp - 4]
00cc7aaf: e8400dffff               call 0xcb87f4 ; CIS_TCBusUnitCGateAgent.TCBusUnitCGateAgent.QuickGetSingleParameter
00cc7ab4: 8b55b4                   mov edx, dword ptr [ebp - 0x4c]
00cc7ab7: 8d45b8                   lea eax, [ebp - 0x48]
00cc7aba: e8b97a96ff               call 0x62f578 ; Variants.@VarFromUStr
00cc7abf: 8d55b8                   lea edx, [ebp - 0x48]
00cc7ac2: 8b45fc                   mov eax, dword ptr [ebp - 4]
00cc7ac5: 8b802c010000             mov eax, dword ptr [eax + 0x12c]
00cc7acb: 8b08                     mov ecx, dword ptr [eax]
00cc7acd: ff517c                   call dword ptr [ecx + 0x7c]
00cc7ad0: 8d55a4                   lea edx, [ebp - 0x5c]
00cc7ad3: 8b45fc                   mov eax, dword ptr [ebp - 4]
00cc7ad6: 8b8000010000             mov eax, dword ptr [eax + 0x100]
00cc7adc: 8b08                     mov ecx, dword ptr [eax]
00cc7ade: ff5174                   call dword ptr [ecx + 0x74]
00cc7ae1: 8d45a4                   lea eax, [ebp - 0x5c]
00cc7ae4: 50                       push eax
00cc7ae5: 8d4594                   lea eax, [ebp - 0x6c]
00cc7ae8: 33d2                     xor edx, edx
00cc7aea: e8897a96ff               call 0x62f578 ; Variants.@VarFromUStr
00cc7aef: 8d5594                   lea edx, [ebp - 0x6c]
00cc7af2: 58                       pop eax
00cc7af3: e854c196ff               call 0x633c4c ; Variants.@VarCmpEQ
00cc7af8: 7434                     je 0xcc7b2e
00cc7afa: 8d5584                   lea edx, [ebp - 0x7c]
00cc7afd: 8b45fc                   mov eax, dword ptr [ebp - 4]
00cc7b00: 8b802c010000             mov eax, dword ptr [eax + 0x12c]
00cc7b06: 8b08                     mov ecx, dword ptr [eax]
00cc7b08: ff5174                   call dword ptr [ecx + 0x74]
00cc7b0b: 8d4584                   lea eax, [ebp - 0x7c]
00cc7b0e: 50                       push eax
00cc7b0f: 8d8574ffffff             lea eax, [ebp - 0x8c]
00cc7b15: 33d2                     xor edx, edx
00cc7b17: e85c7a96ff               call 0x62f578 ; Variants.@VarFromUStr
00cc7b1c: 8d9574ffffff             lea edx, [ebp - 0x8c]
00cc7b22: 58                       pop eax
00cc7b23: e824c196ff               call 0x633c4c ; Variants.@VarCmpEQ
00cc7b28: 7404                     je 0xcc7b2e
00cc7b2a: 33db                     xor ebx, ebx
00cc7b2c: eb02                     jmp 0xcc7b30
00cc7b2e: b301                     mov bl, 1
00cc7b30: 8b45fc                   mov eax, dword ptr [ebp - 4]
00cc7b33: e814f9ffff               call 0xcc744c ; CIS_TCoreKeyInputCGateAgent.TCoreKeyInputCGateAgent.CBusUnit
00cc7b38: 889870010000             mov byte ptr [eax + 0x170], bl
00cc7b3e: 33c0                     xor eax, eax
00cc7b40: 5a                       pop edx
00cc7b41: 59                       pop ecx
00cc7b42: 59                       pop ecx
00cc7b43: 648910                   mov dword ptr fs:[eax], edx
00cc7b46: 68947bcc00               push 0xcc7b94
00cc7b4b: 8d8574ffffff             lea eax, [ebp - 0x8c]
00cc7b51: 8b15b8126000             mov edx, dword ptr [0x6012b8]
00cc7b57: b904000000               mov ecx, 4
00cc7b5c: e84f1d94ff               call 0x6098b0 ; System.@FinalizeArray
00cc7b61: 8d45b4                   lea eax, [ebp - 0x4c]
00cc7b64: e8ab0d94ff               call 0x608914 ; System.@UStrClr
00cc7b69: 8d45b8                   lea eax, [ebp - 0x48]
00cc7b6c: 8b15b8126000             mov edx, dword ptr [0x6012b8]
00cc7b72: b903000000               mov ecx, 3
00cc7b77: e8341d94ff               call 0x6098b0 ; System.@FinalizeArray
00cc7b7c: 8d45e8                   lea eax, [ebp - 0x18]
00cc7b7f: e8900d94ff               call 0x608914 ; System.@UStrClr
00cc7b84: 8d45ec                   lea eax, [ebp - 0x14]
00cc7b87: e8902396ff               call 0x629f1c ; Variants.@VarClr
00cc7b8c: c3                       ret 
00cc7b8d: e992f093ff               jmp 0x606c24 ; System.@HandleFinally
00cc7b92: ebb7                     jmp 0xcc7b4b
00cc7b94: 5b                       pop ebx
00cc7b95: 8be5                     mov esp, ebp
00cc7b97: 5d                       pop ebp
00cc7b98: c3                       ret 
00cc7b99: 0000                     add byte ptr [eax], al
00cc7b9b: 00b0040200ff             add byte ptr [eax - 0xfffdfc], dh
