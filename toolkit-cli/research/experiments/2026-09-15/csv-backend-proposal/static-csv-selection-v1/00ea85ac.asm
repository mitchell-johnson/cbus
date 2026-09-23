00ea85ac: 55                       push ebp
00ea85ad: 8bec                     mov ebp, esp
00ea85af: 83c4e0                   add esp, -0x20
00ea85b2: 33c9                     xor ecx, ecx
00ea85b4: 894de0                   mov dword ptr [ebp - 0x20], ecx
00ea85b7: 894de4                   mov dword ptr [ebp - 0x1c], ecx
00ea85ba: 894de8                   mov dword ptr [ebp - 0x18], ecx
00ea85bd: 894dec                   mov dword ptr [ebp - 0x14], ecx
00ea85c0: 8955f0                   mov dword ptr [ebp - 0x10], edx
00ea85c3: 8945fc                   mov dword ptr [ebp - 4], eax
00ea85c6: 33c0                     xor eax, eax
00ea85c8: 55                       push ebp
00ea85c9: 689286ea00               push 0xea8692
00ea85ce: 64ff30                   push dword ptr fs:[eax]
00ea85d1: 648920                   mov dword ptr fs:[eax], esp
00ea85d4: 8b45fc                   mov eax, dword ptr [ebp - 4]
00ea85d7: 8b809c030000             mov eax, dword ptr [eax + 0x39c]
00ea85dd: e89a87bfff               call 0xaa0d7c ; cxInplaceContainer.TcxEditingControl.BeginUpdate
00ea85e2: 33c0                     xor eax, eax
00ea85e4: 55                       push ebp
00ea85e5: 686586ea00               push 0xea8665
00ea85ea: 64ff30                   push dword ptr fs:[eax]
00ea85ed: 648920                   mov dword ptr fs:[eax], esp
00ea85f0: 8b45fc                   mov eax, dword ptr [ebp - 4]
00ea85f3: 8b809c030000             mov eax, dword ptr [eax + 0x39c]
00ea85f9: 8b80e8030000             mov eax, dword ptr [eax + 0x3e8]
00ea85ff: e88047c1ff               call 0xabcd84 ; cxTL.TcxTreeListNodes.GetCount
00ea8604: 48                       dec eax
00ea8605: 85c0                     test eax, eax
00ea8607: 7c40                     jl 0xea8649
00ea8609: 40                       inc eax
00ea860a: 8945f4                   mov dword ptr [ebp - 0xc], eax
00ea860d: c745f800000000           mov dword ptr [ebp - 8], 0
00ea8614: 8b45fc                   mov eax, dword ptr [ebp - 4]
00ea8617: 8b809c030000             mov eax, dword ptr [eax + 0x39c]
00ea861d: 8b80e8030000             mov eax, dword ptr [eax + 0x3e8]
00ea8623: 8b55f8                   mov edx, dword ptr [ebp - 8]
00ea8626: e89d47c1ff               call 0xabcdc8 ; cxTL.TcxTreeListNodes.GetItem
00ea862b: 50                       push eax
00ea862c: 8d45e0                   lea eax, [ebp - 0x20]
00ea862f: b201                     mov dl, 1
00ea8631: e87a6e78ff               call 0x62f4b0 ; Variants.@VarFromBool
00ea8636: 8d4de0                   lea ecx, [ebp - 0x20]
00ea8639: 33d2                     xor edx, edx
00ea863b: 58                       pop eax
00ea863c: e8435fc1ff               call 0xabe584 ; cxTL.TcxTreeListNode.SetValue
00ea8641: ff45f8                   inc dword ptr [ebp - 8]
00ea8644: ff4df4                   dec dword ptr [ebp - 0xc]
00ea8647: 75cb                     jne 0xea8614
00ea8649: 33c0                     xor eax, eax
00ea864b: 5a                       pop edx
00ea864c: 59                       pop ecx
00ea864d: 59                       pop ecx
00ea864e: 648910                   mov dword ptr fs:[eax], edx
00ea8651: 686c86ea00               push 0xea866c
00ea8656: 8b45fc                   mov eax, dword ptr [ebp - 4]
00ea8659: 8b809c030000             mov eax, dword ptr [eax + 0x39c]
00ea865f: e87887bfff               call 0xaa0ddc ; cxInplaceContainer.TcxEditingControl.EndUpdate
00ea8664: c3                       ret
00ea8665: e9bae575ff               jmp 0x606c24 ; System.@HandleFinally
00ea866a: ebea                     jmp 0xea8656
00ea866c: 8b45fc                   mov eax, dword ptr [ebp - 4]
00ea866f: e88c040000               call 0xea8b00 ; CIS_TfrmCSVSelection.TfrmCSVSelection.UpdateSelection
00ea8674: 8b45fc                   mov eax, dword ptr [ebp - 4]
00ea8677: e844050000               call 0xea8bc0 ; CIS_TfrmCSVSelection.TfrmCSVSelection.UpdateUI
00ea867c: 33c0                     xor eax, eax
00ea867e: 5a                       pop edx
00ea867f: 59                       pop ecx
00ea8680: 59                       pop ecx
00ea8681: 648910                   mov dword ptr fs:[eax], edx
00ea8684: 689986ea00               push 0xea8699
00ea8689: 8d45e0                   lea eax, [ebp - 0x20]
00ea868c: e88b1878ff               call 0x629f1c ; Variants.@VarClr
00ea8691: c3                       ret
00ea8692: e98de575ff               jmp 0x606c24 ; System.@HandleFinally
00ea8697: ebf0                     jmp 0xea8689
00ea8699: 8be5                     mov esp, ebp
00ea869b: 5d                       pop ebp
00ea869c: c3                       ret
00ea869d: 8d4000                   lea eax, [eax]
