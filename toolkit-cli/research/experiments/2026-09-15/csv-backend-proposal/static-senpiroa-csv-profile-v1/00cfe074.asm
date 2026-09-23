00cfe074: 55                       push ebp
00cfe075: 8bec                     mov ebp, esp
00cfe077: 83c4f8                   add esp, -8
00cfe07a: 8945fc                   mov dword ptr [ebp - 4], eax
00cfe07d: c745f804000000           mov dword ptr [ebp - 8], 4
00cfe084: 8b45f8                   mov eax, dword ptr [ebp - 8]
00cfe087: 59                       pop ecx
00cfe088: 59                       pop ecx
00cfe089: 5d                       pop ebp
00cfe08a: c3                       ret 
00cfe08b: 90                       nop 
