00ea8b00: 55                       push ebp
00ea8b01: 8bec                     mov ebp, esp
00ea8b03: 33c9                     xor ecx, ecx
00ea8b05: 51                       push ecx
00ea8b06: 51                       push ecx
00ea8b07: 51                       push ecx
00ea8b08: 51                       push ecx
00ea8b09: 51                       push ecx
00ea8b0a: 51                       push ecx
00ea8b0b: 51                       push ecx
00ea8b0c: 8945fc                   mov dword ptr [ebp - 4], eax
00ea8b0f: 33c0                     xor eax, eax
00ea8b11: 55                       push ebp
00ea8b12: 68af8bea00               push 0xea8baf
00ea8b17: 64ff30                   push dword ptr fs:[eax]
00ea8b1a: 648920                   mov dword ptr fs:[eax], esp
00ea8b1d: 8b45fc                   mov eax, dword ptr [ebp - 4]
00ea8b20: 8b15bc8bea00             mov edx, dword ptr [0xea8bbc]
00ea8b26: 8990b0030000             mov dword ptr [eax + 0x3b0], edx
00ea8b2c: 8b45fc                   mov eax, dword ptr [ebp - 4]
00ea8b2f: 8b809c030000             mov eax, dword ptr [eax + 0x39c]
00ea8b35: 8b80e8030000             mov eax, dword ptr [eax + 0x3e8]
00ea8b3b: e84442c1ff               call 0xabcd84 ; cxTL.TcxTreeListNodes.GetCount
00ea8b40: 48                       dec eax
00ea8b41: 85c0                     test eax, eax
00ea8b43: 7c54                     jl 0xea8b99
00ea8b45: 40                       inc eax
00ea8b46: 8945f4                   mov dword ptr [ebp - 0xc], eax
00ea8b49: c745f800000000           mov dword ptr [ebp - 8], 0
00ea8b50: 8b45fc                   mov eax, dword ptr [ebp - 4]
00ea8b53: 8b809c030000             mov eax, dword ptr [eax + 0x39c]
00ea8b59: 8b80e8030000             mov eax, dword ptr [eax + 0x3e8]
00ea8b5f: 8b55f8                   mov edx, dword ptr [ebp - 8]
00ea8b62: e86142c1ff               call 0xabcdc8 ; cxTL.TcxTreeListNodes.GetItem
00ea8b67: 8d4de4                   lea ecx, [ebp - 0x1c]
00ea8b6a: 33d2                     xor edx, edx
00ea8b6c: e8af54c1ff               call 0xabe020 ; cxTL.TcxTreeListNode.GetValue
00ea8b71: 8d45e4                   lea eax, [ebp - 0x1c]
00ea8b74: e81f3878ff               call 0x62c398 ; Variants.@VarToBool
00ea8b79: 84c0                     test al, al
00ea8b7b: 7414                     je 0xea8b91
00ea8b7d: 8a45f8                   mov al, byte ptr [ebp - 8]
00ea8b80: 8b55fc                   mov edx, dword ptr [ebp - 4]
00ea8b83: 3c1f                     cmp al, 0x1f
00ea8b85: 770a                     ja 0xea8b91
00ea8b87: 83e07f                   and eax, 0x7f
00ea8b8a: 0fab82b0030000           bts dword ptr [edx + 0x3b0], eax
00ea8b91: ff45f8                   inc dword ptr [ebp - 8]
00ea8b94: ff4df4                   dec dword ptr [ebp - 0xc]
00ea8b97: 75b7                     jne 0xea8b50
00ea8b99: 33c0                     xor eax, eax
00ea8b9b: 5a                       pop edx
00ea8b9c: 59                       pop ecx
00ea8b9d: 59                       pop ecx
00ea8b9e: 648910                   mov dword ptr fs:[eax], edx
00ea8ba1: 68b68bea00               push 0xea8bb6
00ea8ba6: 8d45e4                   lea eax, [ebp - 0x1c]
00ea8ba9: e86e1378ff               call 0x629f1c ; Variants.@VarClr
00ea8bae: c3                       ret
00ea8baf: e970e075ff               jmp 0x606c24 ; System.@HandleFinally
00ea8bb4: ebf0                     jmp 0xea8ba6
00ea8bb6: 8be5                     mov esp, ebp
00ea8bb8: 5d                       pop ebp
00ea8bb9: c3                       ret
00ea8bba: 0000                     add byte ptr [eax], al
00ea8bbc: 0000                     add byte ptr [eax], al
00ea8bbe: 0000                     add byte ptr [eax], al
