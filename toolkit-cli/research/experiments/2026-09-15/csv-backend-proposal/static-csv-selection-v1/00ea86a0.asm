00ea86a0: 55                       push ebp
00ea86a1: 8bec                     mov ebp, esp
00ea86a3: 83c4e0                   add esp, -0x20
00ea86a6: 33c9                     xor ecx, ecx
00ea86a8: 894de0                   mov dword ptr [ebp - 0x20], ecx
00ea86ab: 894de4                   mov dword ptr [ebp - 0x1c], ecx
00ea86ae: 894de8                   mov dword ptr [ebp - 0x18], ecx
00ea86b1: 894dec                   mov dword ptr [ebp - 0x14], ecx
00ea86b4: 8955f0                   mov dword ptr [ebp - 0x10], edx
00ea86b7: 8945fc                   mov dword ptr [ebp - 4], eax
00ea86ba: 33c0                     xor eax, eax
00ea86bc: 55                       push ebp
00ea86bd: 688687ea00               push 0xea8786
00ea86c2: 64ff30                   push dword ptr fs:[eax]
00ea86c5: 648920                   mov dword ptr fs:[eax], esp
00ea86c8: 8b45fc                   mov eax, dword ptr [ebp - 4]
00ea86cb: 8b809c030000             mov eax, dword ptr [eax + 0x39c]
00ea86d1: e8a686bfff               call 0xaa0d7c ; cxInplaceContainer.TcxEditingControl.BeginUpdate
00ea86d6: 33c0                     xor eax, eax
00ea86d8: 55                       push ebp
00ea86d9: 685987ea00               push 0xea8759
00ea86de: 64ff30                   push dword ptr fs:[eax]
00ea86e1: 648920                   mov dword ptr fs:[eax], esp
00ea86e4: 8b45fc                   mov eax, dword ptr [ebp - 4]
00ea86e7: 8b809c030000             mov eax, dword ptr [eax + 0x39c]
00ea86ed: 8b80e8030000             mov eax, dword ptr [eax + 0x3e8]
00ea86f3: e88c46c1ff               call 0xabcd84 ; cxTL.TcxTreeListNodes.GetCount
00ea86f8: 48                       dec eax
00ea86f9: 85c0                     test eax, eax
00ea86fb: 7c40                     jl 0xea873d
00ea86fd: 40                       inc eax
00ea86fe: 8945f4                   mov dword ptr [ebp - 0xc], eax
00ea8701: c745f800000000           mov dword ptr [ebp - 8], 0
00ea8708: 8b45fc                   mov eax, dword ptr [ebp - 4]
00ea870b: 8b809c030000             mov eax, dword ptr [eax + 0x39c]
00ea8711: 8b80e8030000             mov eax, dword ptr [eax + 0x3e8]
00ea8717: 8b55f8                   mov edx, dword ptr [ebp - 8]
00ea871a: e8a946c1ff               call 0xabcdc8 ; cxTL.TcxTreeListNodes.GetItem
00ea871f: 50                       push eax
00ea8720: 8d45e0                   lea eax, [ebp - 0x20]
00ea8723: 33d2                     xor edx, edx
00ea8725: e8866d78ff               call 0x62f4b0 ; Variants.@VarFromBool
00ea872a: 8d4de0                   lea ecx, [ebp - 0x20]
00ea872d: 33d2                     xor edx, edx
00ea872f: 58                       pop eax
00ea8730: e84f5ec1ff               call 0xabe584 ; cxTL.TcxTreeListNode.SetValue
00ea8735: ff45f8                   inc dword ptr [ebp - 8]
00ea8738: ff4df4                   dec dword ptr [ebp - 0xc]
00ea873b: 75cb                     jne 0xea8708
00ea873d: 33c0                     xor eax, eax
00ea873f: 5a                       pop edx
00ea8740: 59                       pop ecx
00ea8741: 59                       pop ecx
00ea8742: 648910                   mov dword ptr fs:[eax], edx
00ea8745: 686087ea00               push 0xea8760
00ea874a: 8b45fc                   mov eax, dword ptr [ebp - 4]
00ea874d: 8b809c030000             mov eax, dword ptr [eax + 0x39c]
00ea8753: e88486bfff               call 0xaa0ddc ; cxInplaceContainer.TcxEditingControl.EndUpdate
00ea8758: c3                       ret
00ea8759: e9c6e475ff               jmp 0x606c24 ; System.@HandleFinally
00ea875e: ebea                     jmp 0xea874a
00ea8760: 8b45fc                   mov eax, dword ptr [ebp - 4]
00ea8763: e898030000               call 0xea8b00 ; CIS_TfrmCSVSelection.TfrmCSVSelection.UpdateSelection
00ea8768: 8b45fc                   mov eax, dword ptr [ebp - 4]
00ea876b: e850040000               call 0xea8bc0 ; CIS_TfrmCSVSelection.TfrmCSVSelection.UpdateUI
00ea8770: 33c0                     xor eax, eax
00ea8772: 5a                       pop edx
00ea8773: 59                       pop ecx
00ea8774: 59                       pop ecx
00ea8775: 648910                   mov dword ptr fs:[eax], edx
00ea8778: 688d87ea00               push 0xea878d
00ea877d: 8d45e0                   lea eax, [ebp - 0x20]
00ea8780: e8971778ff               call 0x629f1c ; Variants.@VarClr
00ea8785: c3                       ret
00ea8786: e999e475ff               jmp 0x606c24 ; System.@HandleFinally
00ea878b: ebf0                     jmp 0xea877d
00ea878d: 8be5                     mov esp, ebp
00ea878f: 5d                       pop ebp
00ea8790: c3                       ret
00ea8791: 8d4000                   lea eax, [eax]
