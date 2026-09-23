00ea89e8: 55                       push ebp
00ea89e9: 8bec                     mov ebp, esp
00ea89eb: 83c4f0                   add esp, -0x10
00ea89ee: 33c9                     xor ecx, ecx
00ea89f0: 894df0                   mov dword ptr [ebp - 0x10], ecx
00ea89f3: 8955f8                   mov dword ptr [ebp - 8], edx
00ea89f6: 8945fc                   mov dword ptr [ebp - 4], eax
00ea89f9: 33c0                     xor eax, eax
00ea89fb: 55                       push ebp
00ea89fc: 68908aea00               push 0xea8a90
00ea8a01: 64ff30                   push dword ptr fs:[eax]
00ea8a04: 648920                   mov dword ptr fs:[eax], esp
00ea8a07: a1c81b3c01               mov eax, dword ptr [0x13c1bc8]
00ea8a0c: 8b00                     mov eax, dword ptr [eax]
00ea8a0e: 8b4004                   mov eax, dword ptr [eax + 4]
00ea8a11: 8b5040                   mov edx, dword ptr [eax + 0x40]
00ea8a14: 8d45f0                   lea eax, [ebp - 0x10]
00ea8a17: b9a88aea00               mov ecx, 0xea8aa8
00ea8a1c: e8e70376ff               call 0x608e08 ; System.@UStrCat3
00ea8a21: 8b4df0                   mov ecx, dword ptr [ebp - 0x10]
00ea8a24: b201                     mov dl, 1
00ea8a26: a1b4f96500               mov eax, dword ptr [0x65f9b4]
00ea8a2b: e848937bff               call 0x661d78 ; Registry.TRegIniFile.Create
00ea8a30: 8945f4                   mov dword ptr [ebp - 0xc], eax
00ea8a33: 33c0                     xor eax, eax
00ea8a35: 55                       push ebp
00ea8a36: 68738aea00               push 0xea8a73
00ea8a3b: 64ff30                   push dword ptr fs:[eax]
00ea8a3e: 648920                   mov dword ptr fs:[eax], esp
00ea8a41: 68c48aea00               push 0xea8ac4
00ea8a46: 8b45f8                   mov eax, dword ptr [ebp - 8]
00ea8a49: 50                       push eax
00ea8a4a: 8b45fc                   mov eax, dword ptr [ebp - 4]
00ea8a4d: 8b5008                   mov edx, dword ptr [eax + 8]
00ea8a50: b9e48aea00               mov ecx, 0xea8ae4
00ea8a55: 8b45f4                   mov eax, dword ptr [ebp - 0xc]
00ea8a58: e8af937bff               call 0x661e0c ; Registry.TRegIniFile.ReadString
00ea8a5d: 33c0                     xor eax, eax
00ea8a5f: 5a                       pop edx
00ea8a60: 59                       pop ecx
00ea8a61: 59                       pop ecx
00ea8a62: 648910                   mov dword ptr fs:[eax], edx
00ea8a65: 687a8aea00               push 0xea8a7a
00ea8a6a: 8b45f4                   mov eax, dword ptr [ebp - 0xc]
00ea8a6d: e88ed775ff               call 0x606200 ; System.TObject.Free
00ea8a72: c3                       ret
00ea8a73: e9ace175ff               jmp 0x606c24 ; System.@HandleFinally
00ea8a78: ebf0                     jmp 0xea8a6a
00ea8a7a: 33c0                     xor eax, eax
00ea8a7c: 5a                       pop edx
00ea8a7d: 59                       pop ecx
00ea8a7e: 59                       pop ecx
00ea8a7f: 648910                   mov dword ptr fs:[eax], edx
00ea8a82: 68978aea00               push 0xea8a97
00ea8a87: 8d45f0                   lea eax, [ebp - 0x10]
00ea8a8a: e885fe75ff               call 0x608914 ; System.@UStrClr
00ea8a8f: c3                       ret
00ea8a90: e98fe175ff               jmp 0x606c24 ; System.@HandleFinally
00ea8a95: ebf0                     jmp 0xea8a87
00ea8a97: 8be5                     mov esp, ebp
00ea8a99: 5d                       pop ebp
00ea8a9a: c3                       ret
00ea8a9b: 00b0040200ff             add byte ptr [eax - 0xfffdfc], dh
