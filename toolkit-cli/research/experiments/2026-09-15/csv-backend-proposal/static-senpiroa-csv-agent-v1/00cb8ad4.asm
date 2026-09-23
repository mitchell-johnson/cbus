00cb8ad4: 55                       push ebp
00cb8ad5: 8bec                     mov ebp, esp
00cb8ad7: 33c9                     xor ecx, ecx
00cb8ad9: 51                       push ecx
00cb8ada: 51                       push ecx
00cb8adb: 51                       push ecx
00cb8adc: 51                       push ecx
00cb8add: 51                       push ecx
00cb8ade: 51                       push ecx
00cb8adf: 8945fc                   mov dword ptr [ebp - 4], eax
00cb8ae2: 33c0                     xor eax, eax
00cb8ae4: 55                       push ebp
00cb8ae5: 68548bcb00               push 0xcb8b54
00cb8aea: 64ff30                   push dword ptr fs:[eax]
00cb8aed: 648920                   mov dword ptr fs:[eax], esp
00cb8af0: 8b45fc                   mov eax, dword ptr [ebp - 4]
00cb8af3: e828ccffff               call 0xcb5720 ; CIS_TCBusUnitCGateAgent.TCBusUnitCGateAgent.GetCBusUnit
00cb8af8: 8b80d0000000             mov eax, dword ptr [eax + 0xd0]
00cb8afe: 8b10                     mov edx, dword ptr [eax]
00cb8b00: ff5258                   call dword ptr [edx + 0x58]
00cb8b03: 85c0                     test eax, eax
00cb8b05: 752f                     jne 0xcb8b36
00cb8b07: 8d45e8                   lea eax, [ebp - 0x18]
00cb8b0a: 50                       push eax
00cb8b0b: 33c9                     xor ecx, ecx
00cb8b0d: ba6c8bcb00               mov edx, 0xcb8b6c
00cb8b12: 8b45fc                   mov eax, dword ptr [ebp - 4]
00cb8b15: e842a80000               call 0xcc335c ; CIS_TCBusUnitCGateAgent.TCBusUnitCGateAgent.QuickGet
00cb8b1a: 8b55e8                   mov edx, dword ptr [ebp - 0x18]
00cb8b1d: 8d45ec                   lea eax, [ebp - 0x14]
00cb8b20: e8536a97ff               call 0x62f578 ; Variants.@VarFromUStr
00cb8b25: 8d55ec                   lea edx, [ebp - 0x14]
00cb8b28: 8b45fc                   mov eax, dword ptr [ebp - 4]
00cb8b2b: 8b8088000000             mov eax, dword ptr [eax + 0x88]
00cb8b31: 8b08                     mov ecx, dword ptr [eax]
00cb8b33: ff517c                   call dword ptr [ecx + 0x7c]
00cb8b36: 33c0                     xor eax, eax
00cb8b38: 5a                       pop edx
00cb8b39: 59                       pop ecx
00cb8b3a: 59                       pop ecx
00cb8b3b: 648910                   mov dword ptr fs:[eax], edx
00cb8b3e: 685b8bcb00               push 0xcb8b5b
00cb8b43: 8d45e8                   lea eax, [ebp - 0x18]
00cb8b46: e8c9fd94ff               call 0x608914 ; System.@UStrClr
00cb8b4b: 8d45ec                   lea eax, [ebp - 0x14]
00cb8b4e: e8c91397ff               call 0x629f1c ; Variants.@VarClr
00cb8b53: c3                       ret 
00cb8b54: e9cbe094ff               jmp 0x606c24 ; System.@HandleFinally
00cb8b59: ebe8                     jmp 0xcb8b43
00cb8b5b: 8be5                     mov esp, ebp
00cb8b5d: 5d                       pop ebp
00cb8b5e: c3                       ret 
00cb8b5f: 00b0040200ff             add byte ptr [eax - 0xfffdfc], dh
