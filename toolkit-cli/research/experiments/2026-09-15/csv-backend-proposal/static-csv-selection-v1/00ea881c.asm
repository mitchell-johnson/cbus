00ea881c: 55                       push ebp
00ea881d: 8bec                     mov ebp, esp
00ea881f: 83c4f8                   add esp, -8
00ea8822: 8955f8                   mov dword ptr [ebp - 8], edx
00ea8825: 8945fc                   mov dword ptr [ebp - 4], eax
00ea8828: 8b45fc                   mov eax, dword ptr [ebp - 4]
00ea882b: e808010000               call 0xea8938 ; CIS_TfrmCSVSelection.TfrmCSVSelection.PrepareCSVOptionList
00ea8830: 59                       pop ecx
00ea8831: 59                       pop ecx
00ea8832: 5d                       pop ebp
00ea8833: c3                       ret
