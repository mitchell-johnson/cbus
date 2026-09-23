00ea84ec: 55                       push ebp
00ea84ed: 8bec                     mov ebp, esp
00ea84ef: 83c4ec                   add esp, -0x14
00ea84f2: 33c9                     xor ecx, ecx
00ea84f4: 894dec                   mov dword ptr [ebp - 0x14], ecx
00ea84f7: 894df8                   mov dword ptr [ebp - 8], ecx
00ea84fa: 8955f0                   mov dword ptr [ebp - 0x10], edx
00ea84fd: 8945fc                   mov dword ptr [ebp - 4], eax
00ea8500: 33c0                     xor eax, eax
00ea8502: 55                       push ebp
00ea8503: 688e85ea00               push 0xea858e
00ea8508: 64ff30                   push dword ptr fs:[eax]
00ea850b: 648920                   mov dword ptr fs:[eax], esp
00ea850e: 8d45f8                   lea eax, [ebp - 8]
00ea8511: 33d2                     xor edx, edx
00ea8513: e8600476ff               call 0x608978 ; System.@UStrLAsg
00ea8518: c645f700                 mov byte ptr [ebp - 9], 0
00ea851c: 8a45f7                   mov al, byte ptr [ebp - 9]
00ea851f: 8b55fc                   mov edx, dword ptr [ebp - 4]
00ea8522: 3c1f                     cmp al, 0x1f
00ea8524: 770a                     ja 0xea8530
00ea8526: 83e07f                   and eax, 0x7f
00ea8529: 0fa382b0030000           bt dword ptr [edx + 0x3b0], eax
00ea8530: 732a                     jae 0xea855c
00ea8532: ff75f8                   push dword ptr [ebp - 8]
00ea8535: 8d4dec                   lea ecx, [ebp - 0x14]
00ea8538: 33d2                     xor edx, edx
00ea853a: 8a55f7                   mov dl, byte ptr [ebp - 9]
00ea853d: a13c438500               mov eax, dword ptr [0x85433c]
00ea8542: e835fa99ff               call 0x847f7c ; CIS_TEnumeratedTypeAttribute.GetDescriptionFromEnumeratedValueOrdinalValue
00ea8547: ff75ec                   push dword ptr [ebp - 0x14]
00ea854a: 68a885ea00               push 0xea85a8
00ea854f: 8d45f8                   lea eax, [ebp - 8]
00ea8552: ba03000000               mov edx, 3
00ea8557: e8900976ff               call 0x608eec ; System.@UStrCatN
00ea855c: fe45f7                   inc byte ptr [ebp - 9]
00ea855f: 807df71a                 cmp byte ptr [ebp - 9], 0x1a
00ea8563: 75b7                     jne 0xea851c
00ea8565: 8b55f8                   mov edx, dword ptr [ebp - 8]
00ea8568: 8b45fc                   mov eax, dword ptr [ebp - 4]
00ea856b: e880060000               call 0xea8bf0 ; CIS_TfrmCSVSelection.TfrmCSVSelection.WriteRegistryCSVSelection
00ea8570: 33c0                     xor eax, eax
00ea8572: 5a                       pop edx
00ea8573: 59                       pop ecx
00ea8574: 59                       pop ecx
00ea8575: 648910                   mov dword ptr fs:[eax], edx
00ea8578: 689585ea00               push 0xea8595
00ea857d: 8d45ec                   lea eax, [ebp - 0x14]
00ea8580: e88f0376ff               call 0x608914 ; System.@UStrClr
00ea8585: 8d45f8                   lea eax, [ebp - 8]
00ea8588: e8870376ff               call 0x608914 ; System.@UStrClr
00ea858d: c3                       ret
00ea858e: e991e675ff               jmp 0x606c24 ; System.@HandleFinally
00ea8593: ebe8                     jmp 0xea857d
00ea8595: 8be5                     mov esp, ebp
00ea8597: 5d                       pop ebp
00ea8598: c3                       ret
00ea8599: 0000                     add byte ptr [eax], al
00ea859b: 00b0040200ff             add byte ptr [eax - 0xfffdfc], dh
