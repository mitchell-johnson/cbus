00cc75e4: 55                       push ebp
00cc75e5: 8bec                     mov ebp, esp
00cc75e7: 83c4e8                   add esp, -0x18
00cc75ea: 53                       push ebx
00cc75eb: 33db                     xor ebx, ebx
00cc75ed: 895dec                   mov dword ptr [ebp - 0x14], ebx
00cc75f0: 895de8                   mov dword ptr [ebp - 0x18], ebx
00cc75f3: 894df4                   mov dword ptr [ebp - 0xc], ecx
00cc75f6: 8955f8                   mov dword ptr [ebp - 8], edx
00cc75f9: 8945fc                   mov dword ptr [ebp - 4], eax
00cc75fc: 33c0                     xor eax, eax
00cc75fe: 55                       push ebp
00cc75ff: 68dc76cc00               push 0xcc76dc
00cc7604: 64ff30                   push dword ptr fs:[eax]
00cc7607: 648920                   mov dword ptr fs:[eax], esp
00cc760a: 8d55e8                   lea edx, [ebp - 0x18]
00cc760d: 8b45fc                   mov eax, dword ptr [ebp - 4]
00cc7610: 8b8000010000             mov eax, dword ptr [eax + 0x100]
00cc7616: 8b08                     mov ecx, dword ptr [eax]
00cc7618: ff512c                   call dword ptr [ecx + 0x2c]
00cc761b: 8b45e8                   mov eax, dword ptr [ebp - 0x18]
00cc761e: 8d4dec                   lea ecx, [ebp - 0x14]
00cc7621: baf476cc00               mov edx, 0xcc76f4
00cc7626: e8fd9bb2ff               call 0x7f1228 ; CIS_Maths.StrToIntArray
00cc762b: 8b45ec                   mov eax, dword ptr [ebp - 0x14]
00cc762e: b9ff000000               mov ecx, 0xff
00cc7633: 8b55f4                   mov edx, dword ptr [ebp - 0xc]
00cc7636: e8f598b2ff               call 0x7f0f30 ; CIS_Maths.IntArrayElementWithDefault
00cc763b: 8945f0                   mov dword ptr [ebp - 0x10], eax
00cc763e: 8b45f8                   mov eax, dword ptr [ebp - 8]
00cc7641: e8727b0400               call 0xd0f1b8 ; CIS_TInputKey.TInputBlock.GetSecondaryApplication
00cc7646: 84c0                     test al, al
00cc7648: 744c                     je 0xcc7696
00cc764a: 8b45fc                   mov eax, dword ptr [ebp - 4]
00cc764d: e8fafdffff               call 0xcc744c ; CIS_TCoreKeyInputCGateAgent.TCoreKeyInputCGateAgent.CBusUnit
00cc7652: 8b10                     mov edx, dword ptr [eax]
00cc7654: ff92b4000000             call dword ptr [edx + 0xb4]
00cc765a: 85c0                     test eax, eax
00cc765c: 742c                     je 0xcc768a
00cc765e: 8b45fc                   mov eax, dword ptr [ebp - 4]
00cc7661: e8e6fdffff               call 0xcc744c ; CIS_TCoreKeyInputCGateAgent.TCoreKeyInputCGateAgent.CBusUnit
00cc7666: 8b10                     mov edx, dword ptr [eax]
00cc7668: ff92b4000000             call dword ptr [edx + 0xb4]
00cc766e: 8b80b4000000             mov eax, dword ptr [eax + 0xb4]
00cc7674: b101                     mov cl, 1
00cc7676: 8b55f0                   mov edx, dword ptr [ebp - 0x10]
00cc7679: e8ea142600               call 0xf28b68 ; CIS_TCommonCBus.TCBusGroupManager.GroupByAddress
00cc767e: 8bd0                     mov edx, eax
00cc7680: 8b45f8                   mov eax, dword ptr [ebp - 8]
00cc7683: e8787b0400               call 0xd0f200 ; CIS_TInputKey.TInputBlock.SetGroup
00cc7688: eb2e                     jmp 0xcc76b8
00cc768a: 33d2                     xor edx, edx
00cc768c: 8b45f8                   mov eax, dword ptr [ebp - 8]
00cc768f: e86c7b0400               call 0xd0f200 ; CIS_TInputKey.TInputBlock.SetGroup
00cc7694: eb22                     jmp 0xcc76b8
00cc7696: 8b45f8                   mov eax, dword ptr [ebp - 8]
00cc7699: e83e7b0400               call 0xd0f1dc ; CIS_TInputKey.TInputBlock.GetApplicationForBlock
00cc769e: 8b80b4000000             mov eax, dword ptr [eax + 0xb4]
00cc76a4: b101                     mov cl, 1
00cc76a6: 8b55f0                   mov edx, dword ptr [ebp - 0x10]
00cc76a9: e8ba142600               call 0xf28b68 ; CIS_TCommonCBus.TCBusGroupManager.GroupByAddress
00cc76ae: 8bd0                     mov edx, eax
00cc76b0: 8b45f8                   mov eax, dword ptr [ebp - 8]
00cc76b3: e8487b0400               call 0xd0f200 ; CIS_TInputKey.TInputBlock.SetGroup
00cc76b8: 33c0                     xor eax, eax
00cc76ba: 5a                       pop edx
00cc76bb: 59                       pop ecx
00cc76bc: 59                       pop ecx
00cc76bd: 648910                   mov dword ptr fs:[eax], edx
00cc76c0: 68e376cc00               push 0xcc76e3
00cc76c5: 8d45e8                   lea eax, [ebp - 0x18]
00cc76c8: e8471294ff               call 0x608914 ; System.@UStrClr
00cc76cd: 8d45ec                   lea eax, [ebp - 0x14]
00cc76d0: 8b151c0e7f00             mov edx, dword ptr [0x7f0e1c]
00cc76d6: e8693194ff               call 0x60a844 ; System.@DynArrayClear
00cc76db: c3                       ret 
00cc76dc: e943f593ff               jmp 0x606c24 ; System.@HandleFinally
00cc76e1: ebe2                     jmp 0xcc76c5
00cc76e3: 5b                       pop ebx
00cc76e4: 8be5                     mov esp, ebp
00cc76e6: 5d                       pop ebp
00cc76e7: c3                       ret 
00cc76e8: b004                     mov al, 4
00cc76ea: 0200                     add al, byte ptr [eax]
