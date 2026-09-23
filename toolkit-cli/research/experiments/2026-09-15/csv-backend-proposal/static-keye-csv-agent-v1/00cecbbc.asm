00cecbbc: 55                       push ebp
00cecbbd: 8bec                     mov ebp, esp
00cecbbf: 83c4d4                   add esp, -0x2c
00cecbc2: 53                       push ebx
00cecbc3: 33db                     xor ebx, ebx
00cecbc5: 895dd4                   mov dword ptr [ebp - 0x2c], ebx
00cecbc8: 895dd8                   mov dword ptr [ebp - 0x28], ebx
00cecbcb: 895ddc                   mov dword ptr [ebp - 0x24], ebx
00cecbce: 894df0                   mov dword ptr [ebp - 0x10], ecx
00cecbd1: 8955f8                   mov dword ptr [ebp - 8], edx
00cecbd4: 8945fc                   mov dword ptr [ebp - 4], eax
00cecbd7: 33c0                     xor eax, eax
00cecbd9: 55                       push ebp
00cecbda: 68f7ccce00               push 0xceccf7
00cecbdf: 64ff30                   push dword ptr fs:[eax]
00cecbe2: 648920                   mov dword ptr fs:[eax], esp
00cecbe5: 8d45dc                   lea eax, [ebp - 0x24]
00cecbe8: 50                       push eax
00cecbe9: 33c9                     xor ecx, ecx
00cecbeb: ba10cdce00               mov edx, 0xcecd10
00cecbf0: 8b45fc                   mov eax, dword ptr [ebp - 4]
00cecbf3: e86467fdff               call 0xcc335c ; CIS_TCBusUnitCGateAgent.TCBusUnitCGateAgent.QuickGet
00cecbf8: 8b55dc                   mov edx, dword ptr [ebp - 0x24]
00cecbfb: 8b45f8                   mov eax, dword ptr [ebp - 8]
00cecbfe: e821bd91ff               call 0x608924 ; System.@UStrAsg
00cecc03: 8b45f8                   mov eax, dword ptr [ebp - 8]
00cecc06: 50                       push eax
00cecc07: 8b55f8                   mov edx, dword ptr [ebp - 8]
00cecc0a: 8b12                     mov edx, dword ptr [edx]
00cecc0c: b838cdce00               mov eax, 0xcecd38
00cecc11: e81ada92ff               call 0x61a630 ; SysUtils.LastDelimiter
00cecc16: 8bc8                     mov ecx, eax
00cecc18: 49                       dec ecx
00cecc19: 8b45f8                   mov eax, dword ptr [ebp - 8]
00cecc1c: 8b00                     mov eax, dword ptr [eax]
00cecc1e: ba01000000               mov edx, 1
00cecc23: e8ecc491ff               call 0x609114 ; System.@UStrCopy
00cecc28: 8b45f0                   mov eax, dword ptr [ebp - 0x10]
00cecc2b: 33d2                     xor edx, edx
00cecc2d: e8f2bc91ff               call 0x608924 ; System.@UStrAsg
00cecc32: 8d45d8                   lea eax, [ebp - 0x28]
00cecc35: 50                       push eax
00cecc36: 33c9                     xor ecx, ecx
00cecc38: ba48cdce00               mov edx, 0xcecd48
00cecc3d: 8b45fc                   mov eax, dword ptr [ebp - 4]
00cecc40: e81767fdff               call 0xcc335c ; CIS_TCBusUnitCGateAgent.TCBusUnitCGateAgent.QuickGet
00cecc45: 8b45d8                   mov eax, dword ptr [ebp - 0x28]
00cecc48: 33d2                     xor edx, edx
00cecc4a: e85dcf92ff               call 0x619bac ; SysUtils.StrToIntDef
00cecc4f: 8945e4                   mov dword ptr [ebp - 0x1c], eax
00cecc52: 8b45fc                   mov eax, dword ptr [ebp - 4]
00cecc55: e882010000               call 0xcecddc ; CIS_TCoreNeoProInputCGateAgent.TCoreNeoProInputCGateAgent.CBusUnit
00cecc5a: 8b80c8010000             mov eax, dword ptr [eax + 0x1c8]
00cecc60: 8b10                     mov edx, dword ptr [eax]
00cecc62: ff5258                   call dword ptr [edx + 0x58]
00cecc65: 48                       dec eax
00cecc66: 85c0                     test eax, eax
00cecc68: 7c72                     jl 0xceccdc
00cecc6a: 40                       inc eax
00cecc6b: 8945e0                   mov dword ptr [ebp - 0x20], eax
00cecc6e: c745ec00000000           mov dword ptr [ebp - 0x14], 0
00cecc75: 8b4dec                   mov ecx, dword ptr [ebp - 0x14]
00cecc78: b801000000               mov eax, 1
00cecc7d: d3e0                     shl eax, cl
00cecc7f: 8945e8                   mov dword ptr [ebp - 0x18], eax
00cecc82: 8b45e4                   mov eax, dword ptr [ebp - 0x1c]
00cecc85: 2345e8                   and eax, dword ptr [ebp - 0x18]
00cecc88: 3b45e8                   cmp eax, dword ptr [ebp - 0x18]
00cecc8b: 0f94c0                   sete al
00cecc8e: 33d2                     xor edx, edx
00cecc90: e81f4cb0ff               call 0x7f18b4 ; CIS_Maths.BooltoInt
00cecc95: 8d55d4                   lea edx, [ebp - 0x2c]
00cecc98: e80fcc92ff               call 0x6198ac ; SysUtils.IntToStr
00cecc9d: 8b55d4                   mov edx, dword ptr [ebp - 0x2c]
00cecca0: 8b45f0                   mov eax, dword ptr [ebp - 0x10]
00cecca3: e8a0c091ff               call 0x608d48 ; System.@UStrCat
00cecca8: 8b45f0                   mov eax, dword ptr [ebp - 0x10]
00ceccab: 8b45fc                   mov eax, dword ptr [ebp - 4]
00ceccae: e829010000               call 0xcecddc ; CIS_TCoreNeoProInputCGateAgent.TCoreNeoProInputCGateAgent.CBusUnit
00ceccb3: 8b80c8010000             mov eax, dword ptr [eax + 0x1c8]
00ceccb9: 8b10                     mov edx, dword ptr [eax]
00ceccbb: ff5258                   call dword ptr [edx + 0x58]
00ceccbe: 48                       dec eax
00ceccbf: 3b45ec                   cmp eax, dword ptr [ebp - 0x14]
00ceccc2: 7410                     je 0xceccd4
00ceccc4: 8b45f0                   mov eax, dword ptr [ebp - 0x10]
00ceccc7: ba38cdce00               mov edx, 0xcecd38
00cecccc: e877c091ff               call 0x608d48 ; System.@UStrCat
00ceccd1: 8b45f0                   mov eax, dword ptr [ebp - 0x10]
00ceccd4: ff45ec                   inc dword ptr [ebp - 0x14]
00ceccd7: ff4de0                   dec dword ptr [ebp - 0x20]
00ceccda: 7599                     jne 0xcecc75
00ceccdc: 33c0                     xor eax, eax
00ceccde: 5a                       pop edx
00ceccdf: 59                       pop ecx
00cecce0: 59                       pop ecx
00cecce1: 648910                   mov dword ptr fs:[eax], edx
00cecce4: 68feccce00               push 0xceccfe
00cecce9: 8d45d4                   lea eax, [ebp - 0x2c]
00ceccec: ba03000000               mov edx, 3
00ceccf1: e826bc91ff               call 0x60891c ; System.@UStrArrayClr
00ceccf6: c3                       ret 
00ceccf7: e9289f91ff               jmp 0x606c24 ; System.@HandleFinally
00ceccfc: ebeb                     jmp 0xcecce9
00ceccfe: 5b                       pop ebx
00ceccff: 8be5                     mov esp, ebp
00cecd01: 5d                       pop ebp
00cecd02: c3                       ret 
00cecd03: 00b0040200ff             add byte ptr [eax - 0xfffdfc], dh
