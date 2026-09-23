00cecae4: 55                       push ebp
00cecae5: 8bec                     mov ebp, esp
00cecae7: 33c9                     xor ecx, ecx
00cecae9: 51                       push ecx
00cecaea: 51                       push ecx
00cecaeb: 51                       push ecx
00cecaec: 51                       push ecx
00cecaed: 51                       push ecx
00cecaee: 51                       push ecx
00cecaef: 8945fc                   mov dword ptr [ebp - 4], eax
00cecaf2: 33c0                     xor eax, eax
00cecaf4: 55                       push ebp
00cecaf5: 6872cbce00               push 0xcecb72
00cecafa: 64ff30                   push dword ptr fs:[eax]
00cecafd: 648920                   mov dword ptr fs:[eax], esp
00cecb00: 8b45fc                   mov eax, dword ptr [ebp - 4]
00cecb03: e81caffdff               call 0xcc7a24 ; CIS_TCoreKeyInputCGateAgent.TCoreKeyInputCGateAgent.LoadDBParametersForLoadGroups
00cecb08: 8d4df8                   lea ecx, [ebp - 8]
00cecb0b: ba8ccbce00               mov edx, 0xcecb8c
00cecb10: 8b45fc                   mov eax, dword ptr [ebp - 4]
00cecb13: e8dcbcfcff               call 0xcb87f4 ; CIS_TCBusUnitCGateAgent.TCBusUnitCGateAgent.QuickGetSingleParameter
00cecb18: 837df800                 cmp dword ptr [ebp - 8], 0
00cecb1c: 7427                     je 0xcecb45
00cecb1e: 8b45f8                   mov eax, dword ptr [ebp - 8]
00cecb21: e84ad092ff               call 0x619b70 ; SysUtils.StrToInt
00cecb26: 8bd0                     mov edx, eax
00cecb28: 8d45e8                   lea eax, [ebp - 0x18]
00cecb2b: b1fc                     mov cl, 0xfc
00cecb2d: e8622794ff               call 0x62f294 ; Variants.@VarFromInt
00cecb32: 8d55e8                   lea edx, [ebp - 0x18]
00cecb35: 8b45fc                   mov eax, dword ptr [ebp - 4]
00cecb38: 8b80cc010000             mov eax, dword ptr [eax + 0x1cc]
00cecb3e: 8b08                     mov ecx, dword ptr [eax]
00cecb40: ff517c                   call dword ptr [ecx + 0x7c]
00cecb43: eb0f                     jmp 0xcecb54
00cecb45: 8b45fc                   mov eax, dword ptr [ebp - 4]
00cecb48: e88f020000               call 0xcecddc ; CIS_TCoreNeoProInputCGateAgent.TCoreNeoProInputCGateAgent.CBusUnit
00cecb4d: c6807001000001           mov byte ptr [eax + 0x170], 1
00cecb54: 33c0                     xor eax, eax
00cecb56: 5a                       pop edx
00cecb57: 59                       pop ecx
00cecb58: 59                       pop ecx
00cecb59: 648910                   mov dword ptr fs:[eax], edx
00cecb5c: 6879cbce00               push 0xcecb79
00cecb61: 8d45e8                   lea eax, [ebp - 0x18]
00cecb64: e8b3d393ff               call 0x629f1c ; Variants.@VarClr
00cecb69: 8d45f8                   lea eax, [ebp - 8]
00cecb6c: e8a3bd91ff               call 0x608914 ; System.@UStrClr
00cecb71: c3                       ret 
00cecb72: e9ada091ff               jmp 0x606c24 ; System.@HandleFinally
00cecb77: ebe8                     jmp 0xcecb61
00cecb79: 8be5                     mov esp, ebp
00cecb7b: 5d                       pop ebp
00cecb7c: c3                       ret 
00cecb7d: 0000                     add byte ptr [eax], al
00cecb7f: 00b0040200ff             add byte ptr [eax - 0xfffdfc], dh
