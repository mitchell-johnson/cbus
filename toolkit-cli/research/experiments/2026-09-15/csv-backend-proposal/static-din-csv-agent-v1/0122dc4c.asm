0122dc4c: 55                       push ebp
0122dc4d: 8bec                     mov ebp, esp
0122dc4f: b907000000               mov ecx, 7
0122dc54: 6a00                     push 0
0122dc56: 6a00                     push 0
0122dc58: 49                       dec ecx
0122dc59: 75f9                     jne 0x122dc54
0122dc5b: 53                       push ebx
0122dc5c: 8945fc                   mov dword ptr [ebp - 4], eax
0122dc5f: 33c0                     xor eax, eax
0122dc61: 55                       push ebp
0122dc62: 680bdd2201               push 0x122dd0b
0122dc67: 64ff30                   push dword ptr fs:[eax]
0122dc6a: 648920                   mov dword ptr fs:[eax], esp
0122dc6d: 8b45fc                   mov eax, dword ptr [ebp - 4]
0122dc70: e85faea8ff               call 0xcb8ad4 ; CIS_TCBusUnitCGateAgent.TCBusUnitCGateAgent.LoadDBParametersForLoadGroups
0122dc75: 8d4de8                   lea ecx, [ebp - 0x18]
0122dc78: ba24dd2201               mov edx, 0x122dd24
0122dc7d: 8b45fc                   mov eax, dword ptr [ebp - 4]
0122dc80: e86faba8ff               call 0xcb87f4 ; CIS_TCBusUnitCGateAgent.TCBusUnitCGateAgent.QuickGetSingleParameter
0122dc85: 8b55e8                   mov edx, dword ptr [ebp - 0x18]
0122dc88: 8d45ec                   lea eax, [ebp - 0x14]
0122dc8b: e8e81840ff               call 0x62f578 ; Variants.@VarFromUStr
0122dc90: 8d55ec                   lea edx, [ebp - 0x14]
0122dc93: 8b45fc                   mov eax, dword ptr [ebp - 4]
0122dc96: 8b801c010000             mov eax, dword ptr [eax + 0x11c]
0122dc9c: 8b08                     mov ecx, dword ptr [eax]
0122dc9e: ff517c                   call dword ptr [ecx + 0x7c]
0122dca1: 8d55d8                   lea edx, [ebp - 0x28]
0122dca4: 8b45fc                   mov eax, dword ptr [ebp - 4]
0122dca7: 8b801c010000             mov eax, dword ptr [eax + 0x11c]
0122dcad: 8b08                     mov ecx, dword ptr [eax]
0122dcaf: ff5174                   call dword ptr [ecx + 0x74]
0122dcb2: 8d45d8                   lea eax, [ebp - 0x28]
0122dcb5: 50                       push eax
0122dcb6: 8d45c8                   lea eax, [ebp - 0x38]
0122dcb9: 33d2                     xor edx, edx
0122dcbb: e8b81840ff               call 0x62f578 ; Variants.@VarFromUStr
0122dcc0: 8d55c8                   lea edx, [ebp - 0x38]
0122dcc3: 58                       pop eax
0122dcc4: e8835f40ff               call 0x633c4c ; Variants.@VarCmpEQ
0122dcc9: 0f94c3                   sete bl
0122dccc: 8b45fc                   mov eax, dword ptr [ebp - 4]
0122dccf: e8acedffff               call 0x122ca80 ; CIS_TDinRailOutputCGateAgent.TBasicDinRailOutputCGateAgent.GetDinRailOutputUnit
0122dcd4: 889870010000             mov byte ptr [eax + 0x170], bl
0122dcda: 33c0                     xor eax, eax
0122dcdc: 5a                       pop edx
0122dcdd: 59                       pop ecx
0122dcde: 59                       pop ecx
0122dcdf: 648910                   mov dword ptr fs:[eax], edx
0122dce2: 6812dd2201               push 0x122dd12
0122dce7: 8d45c8                   lea eax, [ebp - 0x38]
0122dcea: 8b15b8126000             mov edx, dword ptr [0x6012b8]
0122dcf0: b902000000               mov ecx, 2
0122dcf5: e8b6bb3dff               call 0x6098b0 ; System.@FinalizeArray
0122dcfa: 8d45e8                   lea eax, [ebp - 0x18]
0122dcfd: e812ac3dff               call 0x608914 ; System.@UStrClr
0122dd02: 8d45ec                   lea eax, [ebp - 0x14]
0122dd05: e812c23fff               call 0x629f1c ; Variants.@VarClr
0122dd0a: c3                       ret 
0122dd0b: e9148f3dff               jmp 0x606c24 ; System.@HandleFinally
0122dd10: ebd5                     jmp 0x122dce7
0122dd12: 5b                       pop ebx
0122dd13: 8be5                     mov esp, ebp
0122dd15: 5d                       pop ebp
0122dd16: c3                       ret 
0122dd17: 00b0040200ff             add byte ptr [eax - 0xfffdfc], dh
