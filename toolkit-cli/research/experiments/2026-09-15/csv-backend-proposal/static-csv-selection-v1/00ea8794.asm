00ea8794: 55                       push ebp
00ea8795: 8bec                     mov ebp, esp
00ea8797: 83c4f4                   add esp, -0xc
00ea879a: 894df4                   mov dword ptr [ebp - 0xc], ecx
00ea879d: 8955f8                   mov dword ptr [ebp - 8], edx
00ea87a0: 8945fc                   mov dword ptr [ebp - 4], eax
00ea87a3: 8b45fc                   mov eax, dword ptr [ebp - 4]
00ea87a6: e855030000               call 0xea8b00 ; CIS_TfrmCSVSelection.TfrmCSVSelection.UpdateSelection
00ea87ab: 8b45fc                   mov eax, dword ptr [ebp - 4]
00ea87ae: e80d040000               call 0xea8bc0 ; CIS_TfrmCSVSelection.TfrmCSVSelection.UpdateUI
00ea87b3: 8be5                     mov esp, ebp
00ea87b5: 5d                       pop ebp
00ea87b6: c20400                   ret 4
00ea87b9: 8d4000                   lea eax, [eax]
