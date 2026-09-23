00ea87bc: 55                       push ebp
00ea87bd: 8bec                     mov ebp, esp
00ea87bf: 83c4f8                   add esp, -8
00ea87c2: 8955f8                   mov dword ptr [ebp - 8], edx
00ea87c5: 8945fc                   mov dword ptr [ebp - 4], eax
00ea87c8: b9ec87ea00               mov ecx, 0xea87ec
00ea87cd: ba0888ea00               mov edx, 0xea8808
00ea87d2: 8b45fc                   mov eax, dword ptr [ebp - 4]
00ea87d5: e816df92ff               call 0x7d66f0 ; CIS_Graphics.SetFormGraphic
00ea87da: 59                       pop ecx
00ea87db: 59                       pop ecx
00ea87dc: 5d                       pop ebp
00ea87dd: c3                       ret
00ea87de: 0000                     add byte ptr [eax], al
00ea87e0: b004                     mov al, 4
00ea87e2: 0200                     add al, byte ptr [eax]
