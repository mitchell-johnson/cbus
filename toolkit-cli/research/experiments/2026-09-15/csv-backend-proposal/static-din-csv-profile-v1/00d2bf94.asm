00d2bf94: 55                       push ebp
00d2bf95: 8bec                     mov ebp, esp
00d2bf97: 83c4f4                   add esp, -0xc
00d2bf9a: 8955f8                   mov dword ptr [ebp - 8], edx
00d2bf9d: 8945fc                   mov dword ptr [ebp - 4], eax
00d2bfa0: 8b45fc                   mov eax, dword ptr [ebp - 4]
00d2bfa3: 8b10                     mov edx, dword ptr [eax]
00d2bfa5: ff9288010000             call dword ptr [edx + 0x188]
00d2bfab: 3b45f8                   cmp eax, dword ptr [ebp - 8]
00d2bfae: 0f9f45f7                 setg byte ptr [ebp - 9]
00d2bfb2: 8a45f7                   mov al, byte ptr [ebp - 9]
00d2bfb5: 8be5                     mov esp, ebp
00d2bfb7: 5d                       pop ebp
00d2bfb8: c3                       ret 
00d2bfb9: 8d4000                   lea eax, [eax]
