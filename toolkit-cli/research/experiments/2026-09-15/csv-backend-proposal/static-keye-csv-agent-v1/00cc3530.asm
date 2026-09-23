00cc3530: 55                       push ebp
00cc3531: 8bec                     mov ebp, esp
00cc3533: 83c4ec                   add esp, -0x14
00cc3536: 53                       push ebx
00cc3537: 33db                     xor ebx, ebx
00cc3539: 895dec                   mov dword ptr [ebp - 0x14], ebx
00cc353c: 894df0                   mov dword ptr [ebp - 0x10], ecx
00cc353f: 8955f8                   mov dword ptr [ebp - 8], edx
00cc3542: 8945fc                   mov dword ptr [ebp - 4], eax
00cc3545: 33c0                     xor eax, eax
00cc3547: 55                       push ebp
00cc3548: 689135cc00               push 0xcc3591
00cc354d: 64ff30                   push dword ptr fs:[eax]
00cc3550: 648920                   mov dword ptr fs:[eax], esp
00cc3553: 8d45ec                   lea eax, [ebp - 0x14]
00cc3556: 50                       push eax
00cc3557: 33c9                     xor ecx, ecx
00cc3559: baac35cc00               mov edx, 0xcc35ac
00cc355e: 8b45fc                   mov eax, dword ptr [ebp - 4]
00cc3561: e8f6fdffff               call 0xcc335c ; CIS_TCBusUnitCGateAgent.TCBusUnitCGateAgent.QuickGet
00cc3566: 8b55ec                   mov edx, dword ptr [ebp - 0x14]
00cc3569: 8b45f8                   mov eax, dword ptr [ebp - 8]
00cc356c: e8b35394ff               call 0x608924 ; System.@UStrAsg
00cc3571: 8b45f0                   mov eax, dword ptr [ebp - 0x10]
00cc3574: 33d2                     xor edx, edx
00cc3576: e8a95394ff               call 0x608924 ; System.@UStrAsg
00cc357b: 33c0                     xor eax, eax
00cc357d: 5a                       pop edx
00cc357e: 59                       pop ecx
00cc357f: 59                       pop ecx
00cc3580: 648910                   mov dword ptr fs:[eax], edx
00cc3583: 689835cc00               push 0xcc3598
00cc3588: 8d45ec                   lea eax, [ebp - 0x14]
00cc358b: e8845394ff               call 0x608914 ; System.@UStrClr
00cc3590: c3                       ret 
00cc3591: e98e3694ff               jmp 0x606c24 ; System.@HandleFinally
00cc3596: ebf0                     jmp 0xcc3588
00cc3598: 5b                       pop ebx
00cc3599: 8be5                     mov esp, ebp
00cc359b: 5d                       pop ebp
00cc359c: c3                       ret 
00cc359d: 0000                     add byte ptr [eax], al
00cc359f: 00b0040200ff             add byte ptr [eax - 0xfffdfc], dh
