00c9fcbc: 55                       push ebp
00c9fcbd: 8bec                     mov ebp, esp
00c9fcbf: 83c4f4                   add esp, -0xc
00c9fcc2: 8955f8                   mov dword ptr [ebp - 8], edx
00c9fcc5: 8945fc                   mov dword ptr [ebp - 4], eax
00c9fcc8: 837df803                 cmp dword ptr [ebp - 8], 3
00c9fccc: 0f9e45f7                 setle byte ptr [ebp - 9]
00c9fcd0: 8a45f7                   mov al, byte ptr [ebp - 9]
00c9fcd3: 8be5                     mov esp, ebp
00c9fcd5: 5d                       pop ebp
00c9fcd6: c3                       ret 
00c9fcd7: 90                       nop 
