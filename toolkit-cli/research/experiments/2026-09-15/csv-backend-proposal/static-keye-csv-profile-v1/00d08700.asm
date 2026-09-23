00d08700: 55                       push ebp
00d08701: 8bec                     mov ebp, esp
00d08703: 83c4f4                   add esp, -0xc
00d08706: 8955f8                   mov dword ptr [ebp - 8], edx
00d08709: 8945fc                   mov dword ptr [ebp - 4], eax
00d0870c: 837df807                 cmp dword ptr [ebp - 8], 7
00d08710: 0f9e45f7                 setle byte ptr [ebp - 9]
00d08714: 8a45f7                   mov al, byte ptr [ebp - 9]
00d08717: 8be5                     mov esp, ebp
00d08719: 5d                       pop ebp
00d0871a: c3                       ret 
00d0871b: 90                       nop 
