00ea8938: 55                       push ebp
00ea8939: 8bec                     mov ebp, esp
00ea893b: 83c4f4                   add esp, -0xc
00ea893e: 33d2                     xor edx, edx
00ea8940: 8955f8                   mov dword ptr [ebp - 8], edx
00ea8943: 8945fc                   mov dword ptr [ebp - 4], eax
00ea8946: 33c0                     xor eax, eax
00ea8948: 55                       push ebp
00ea8949: 68db89ea00               push 0xea89db
00ea894e: 64ff30                   push dword ptr fs:[eax]
00ea8951: 648920                   mov dword ptr fs:[eax], esp
00ea8954: 8b45fc                   mov eax, dword ptr [ebp - 4]
00ea8957: 8b809c030000             mov eax, dword ptr [eax + 0x39c]
00ea895d: e81a84bfff               call 0xaa0d7c ; cxInplaceContainer.TcxEditingControl.BeginUpdate
00ea8962: 33c0                     xor eax, eax
00ea8964: 55                       push ebp
00ea8965: 68ae89ea00               push 0xea89ae
00ea896a: 64ff30                   push dword ptr fs:[eax]
00ea896d: 648920                   mov dword ptr fs:[eax], esp
00ea8970: 8d55f8                   lea edx, [ebp - 8]
00ea8973: 8b45fc                   mov eax, dword ptr [ebp - 4]
00ea8976: e86d000000               call 0xea89e8 ; CIS_TfrmCSVSelection.TfrmCSVSelection.ReadRegistryCSVSelection
00ea897b: c645f700                 mov byte ptr [ebp - 9], 0
00ea897f: 55                       push ebp
00ea8980: 8a45f7                   mov al, byte ptr [ebp - 9]
00ea8983: e8acfeffff               call 0xea8834 ; CIS_TfrmCSVSelection.AddCSVOptionToList
00ea8988: 59                       pop ecx
00ea8989: fe45f7                   inc byte ptr [ebp - 9]
00ea898c: 807df71a                 cmp byte ptr [ebp - 9], 0x1a
00ea8990: 75ed                     jne 0xea897f
00ea8992: 33c0                     xor eax, eax
00ea8994: 5a                       pop edx
00ea8995: 59                       pop ecx
00ea8996: 59                       pop ecx
00ea8997: 648910                   mov dword ptr fs:[eax], edx
00ea899a: 68b589ea00               push 0xea89b5
00ea899f: 8b45fc                   mov eax, dword ptr [ebp - 4]
00ea89a2: 8b809c030000             mov eax, dword ptr [eax + 0x39c]
00ea89a8: e82f84bfff               call 0xaa0ddc ; cxInplaceContainer.TcxEditingControl.EndUpdate
00ea89ad: c3                       ret
00ea89ae: e971e275ff               jmp 0x606c24 ; System.@HandleFinally
00ea89b3: ebea                     jmp 0xea899f
00ea89b5: 8b45fc                   mov eax, dword ptr [ebp - 4]
00ea89b8: e843010000               call 0xea8b00 ; CIS_TfrmCSVSelection.TfrmCSVSelection.UpdateSelection
00ea89bd: 8b45fc                   mov eax, dword ptr [ebp - 4]
00ea89c0: e8fb010000               call 0xea8bc0 ; CIS_TfrmCSVSelection.TfrmCSVSelection.UpdateUI
00ea89c5: 33c0                     xor eax, eax
00ea89c7: 5a                       pop edx
00ea89c8: 59                       pop ecx
00ea89c9: 59                       pop ecx
00ea89ca: 648910                   mov dword ptr fs:[eax], edx
00ea89cd: 68e289ea00               push 0xea89e2
00ea89d2: 8d45f8                   lea eax, [ebp - 8]
00ea89d5: e83aff75ff               call 0x608914 ; System.@UStrClr
00ea89da: c3                       ret
00ea89db: e944e275ff               jmp 0x606c24 ; System.@HandleFinally
00ea89e0: ebf0                     jmp 0xea89d2
00ea89e2: 8be5                     mov esp, ebp
00ea89e4: 5d                       pop ebp
00ea89e5: c3                       ret
00ea89e6: 8bc0                     mov eax, eax
