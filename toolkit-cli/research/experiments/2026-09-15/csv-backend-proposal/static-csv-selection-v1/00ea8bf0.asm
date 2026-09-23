00ea8bf0: 55                       push ebp
00ea8bf1: 8bec                     mov ebp, esp
00ea8bf3: 83c4f0                   add esp, -0x10
00ea8bf6: 33c9                     xor ecx, ecx
00ea8bf8: 894df0                   mov dword ptr [ebp - 0x10], ecx
00ea8bfb: 8955f8                   mov dword ptr [ebp - 8], edx
00ea8bfe: 8945fc                   mov dword ptr [ebp - 4], eax
00ea8c01: 8b45f8                   mov eax, dword ptr [ebp - 8]
00ea8c04: e803fd75ff               call 0x60890c ; System.@UStrAddRef
00ea8c09: 33c0                     xor eax, eax
00ea8c0b: 55                       push ebp
00ea8c0c: 68a38cea00               push 0xea8ca3
00ea8c11: 64ff30                   push dword ptr fs:[eax]
00ea8c14: 648920                   mov dword ptr fs:[eax], esp
00ea8c17: a1c81b3c01               mov eax, dword ptr [0x13c1bc8]
00ea8c1c: 8b00                     mov eax, dword ptr [eax]
00ea8c1e: 8b4004                   mov eax, dword ptr [eax + 4]
00ea8c21: 8b5040                   mov edx, dword ptr [eax + 0x40]
00ea8c24: 8d45f0                   lea eax, [ebp - 0x10]
00ea8c27: b9bc8cea00               mov ecx, 0xea8cbc
00ea8c2c: e8d70176ff               call 0x608e08 ; System.@UStrCat3
00ea8c31: 8b4df0                   mov ecx, dword ptr [ebp - 0x10]
00ea8c34: b201                     mov dl, 1
00ea8c36: a1b4f96500               mov eax, dword ptr [0x65f9b4]
00ea8c3b: e838917bff               call 0x661d78 ; Registry.TRegIniFile.Create
00ea8c40: 8945f4                   mov dword ptr [ebp - 0xc], eax
00ea8c43: 33c0                     xor eax, eax
00ea8c45: 55                       push ebp
00ea8c46: 687e8cea00               push 0xea8c7e
00ea8c4b: 64ff30                   push dword ptr fs:[eax]
00ea8c4e: 648920                   mov dword ptr fs:[eax], esp
00ea8c51: 8b45f8                   mov eax, dword ptr [ebp - 8]
00ea8c54: 50                       push eax
00ea8c55: 8b45fc                   mov eax, dword ptr [ebp - 4]
00ea8c58: 8b5008                   mov edx, dword ptr [eax + 8]
00ea8c5b: b9d88cea00               mov ecx, 0xea8cd8
00ea8c60: 8b45f4                   mov eax, dword ptr [ebp - 0xc]
00ea8c63: e878927bff               call 0x661ee0 ; Registry.TRegIniFile.WriteString
00ea8c68: 33c0                     xor eax, eax
00ea8c6a: 5a                       pop edx
00ea8c6b: 59                       pop ecx
00ea8c6c: 59                       pop ecx
00ea8c6d: 648910                   mov dword ptr fs:[eax], edx
00ea8c70: 68858cea00               push 0xea8c85
00ea8c75: 8b45f4                   mov eax, dword ptr [ebp - 0xc]
00ea8c78: e883d575ff               call 0x606200 ; System.TObject.Free
00ea8c7d: c3                       ret
00ea8c7e: e9a1df75ff               jmp 0x606c24 ; System.@HandleFinally
00ea8c83: ebf0                     jmp 0xea8c75
00ea8c85: 33c0                     xor eax, eax
00ea8c87: 5a                       pop edx
00ea8c88: 59                       pop ecx
00ea8c89: 59                       pop ecx
00ea8c8a: 648910                   mov dword ptr fs:[eax], edx
00ea8c8d: 68aa8cea00               push 0xea8caa
00ea8c92: 8d45f0                   lea eax, [ebp - 0x10]
00ea8c95: e87afc75ff               call 0x608914 ; System.@UStrClr
00ea8c9a: 8d45f8                   lea eax, [ebp - 8]
00ea8c9d: e872fc75ff               call 0x608914 ; System.@UStrClr
00ea8ca2: c3                       ret
00ea8ca3: e97cdf75ff               jmp 0x606c24 ; System.@HandleFinally
00ea8ca8: ebe8                     jmp 0xea8c92
00ea8caa: 8be5                     mov esp, ebp
00ea8cac: 5d                       pop ebp
00ea8cad: c3                       ret
00ea8cae: 0000                     add byte ptr [eax], al
00ea8cb0: b004                     mov al, 4
00ea8cb2: 0200                     add al, byte ptr [eax]
