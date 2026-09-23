00ea8834: 55                       push ebp
00ea8835: 8bec                     mov ebp, esp
00ea8837: 33c9                     xor ecx, ecx
00ea8839: 51                       push ecx
00ea883a: 51                       push ecx
00ea883b: 51                       push ecx
00ea883c: 51                       push ecx
00ea883d: 51                       push ecx
00ea883e: 51                       push ecx
00ea883f: 51                       push ecx
00ea8840: 51                       push ecx
00ea8841: 8845ff                   mov byte ptr [ebp - 1], al
00ea8844: 33c0                     xor eax, eax
00ea8846: 55                       push ebp
00ea8847: 68fd88ea00               push 0xea88fd
00ea884c: 64ff30                   push dword ptr fs:[eax]
00ea884f: 648920                   mov dword ptr fs:[eax], esp
00ea8852: 8d4df4                   lea ecx, [ebp - 0xc]
00ea8855: 33d2                     xor edx, edx
00ea8857: 8a55ff                   mov dl, byte ptr [ebp - 1]
00ea885a: a13c438500               mov eax, dword ptr [0x85433c]
00ea885f: e818f799ff               call 0x847f7c ; CIS_TEnumeratedTypeAttribute.GetDescriptionFromEnumeratedValueOrdinalValue
00ea8864: 8b4508                   mov eax, dword ptr [ebp + 8]
00ea8867: 8b40fc                   mov eax, dword ptr [eax - 4]
00ea886a: 8b809c030000             mov eax, dword ptr [eax + 0x39c]
00ea8870: e88f9bc1ff               call 0xac2404 ; cxTL.TcxTreeList.Add
00ea8875: 8945f8                   mov dword ptr [ebp - 8], eax
00ea8878: 8b4508                   mov eax, dword ptr [ebp + 8]
00ea887b: 8b40f8                   mov eax, dword ptr [eax - 8]
00ea887e: ba1489ea00               mov edx, 0xea8914
00ea8883: e8240876ff               call 0x6090ac ; System.@UStrEqual
00ea8888: 7426                     je 0xea88b0
00ea888a: 8d45e0                   lea eax, [ebp - 0x20]
00ea888d: b93489ea00               mov ecx, 0xea8934
00ea8892: 8b55f4                   mov edx, dword ptr [ebp - 0xc]
00ea8895: e86e0576ff               call 0x608e08 ; System.@UStrCat3
00ea889a: 8b45e0                   mov eax, dword ptr [ebp - 0x20]
00ea889d: 8b5508                   mov edx, dword ptr [ebp + 8]
00ea88a0: 8b52f8                   mov edx, dword ptr [edx - 8]
00ea88a3: e82c0c76ff               call 0x6094d4 ; System.Pos
00ea88a8: 85c0                     test eax, eax
00ea88aa: 7f04                     jg 0xea88b0
00ea88ac: 33d2                     xor edx, edx
00ea88ae: eb02                     jmp 0xea88b2
00ea88b0: b201                     mov dl, 1
00ea88b2: 8d45e4                   lea eax, [ebp - 0x1c]
00ea88b5: e8f66b78ff               call 0x62f4b0 ; Variants.@VarFromBool
00ea88ba: 8d4de4                   lea ecx, [ebp - 0x1c]
00ea88bd: 33d2                     xor edx, edx
00ea88bf: 8b45f8                   mov eax, dword ptr [ebp - 8]
00ea88c2: e8bd5cc1ff               call 0xabe584 ; cxTL.TcxTreeListNode.SetValue
00ea88c7: 8b4df4                   mov ecx, dword ptr [ebp - 0xc]
00ea88ca: ba01000000               mov edx, 1
00ea88cf: 8b45f8                   mov eax, dword ptr [ebp - 8]
00ea88d2: e8795bc1ff               call 0xabe450 ; cxTL.TcxTreeListNode.SetText
00ea88d7: 33c0                     xor eax, eax
00ea88d9: 5a                       pop edx
00ea88da: 59                       pop ecx
00ea88db: 59                       pop ecx
00ea88dc: 648910                   mov dword ptr fs:[eax], edx
00ea88df: 680489ea00               push 0xea8904
00ea88e4: 8d45e0                   lea eax, [ebp - 0x20]
00ea88e7: e8280076ff               call 0x608914 ; System.@UStrClr
00ea88ec: 8d45e4                   lea eax, [ebp - 0x1c]
00ea88ef: e8281678ff               call 0x629f1c ; Variants.@VarClr
00ea88f4: 8d45f4                   lea eax, [ebp - 0xc]
00ea88f7: e8180076ff               call 0x608914 ; System.@UStrClr
00ea88fc: c3                       ret
00ea88fd: e922e375ff               jmp 0x606c24 ; System.@HandleFinally
00ea8902: ebe0                     jmp 0xea88e4
00ea8904: 8be5                     mov esp, ebp
00ea8906: 5d                       pop ebp
00ea8907: c3                       ret
00ea8908: b004                     mov al, 4
00ea890a: 0200                     add al, byte ptr [eax]
