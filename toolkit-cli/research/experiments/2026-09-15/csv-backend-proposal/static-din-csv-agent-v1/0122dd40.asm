0122dd40: 55                       push ebp
0122dd41: 8bec                     mov ebp, esp
0122dd43: 83c4e8                   add esp, -0x18
0122dd46: 33d2                     xor edx, edx
0122dd48: 8955ec                   mov dword ptr [ebp - 0x14], edx
0122dd4b: 8955e8                   mov dword ptr [ebp - 0x18], edx
0122dd4e: 8945fc                   mov dword ptr [ebp - 4], eax
0122dd51: 33c0                     xor eax, eax
0122dd53: 55                       push ebp
0122dd54: 68e7de2201               push 0x122dee7
0122dd59: 64ff30                   push dword ptr fs:[eax]
0122dd5c: 648920                   mov dword ptr fs:[eax], esp
0122dd5f: 8b45fc                   mov eax, dword ptr [ebp - 4]
0122dd62: e81daea8ff               call 0xcb8b84 ; CIS_TCBusUnitCGateAgent.TCBusUnitCGateAgent.LoadGroups
0122dd67: 8b45fc                   mov eax, dword ptr [ebp - 4]
0122dd6a: e811edffff               call 0x122ca80 ; CIS_TDinRailOutputCGateAgent.TBasicDinRailOutputCGateAgent.GetDinRailOutputUnit
0122dd6f: 80b87001000000           cmp byte ptr [eax + 0x170], 0
0122dd76: 0f8547010000             jne 0x122dec3
0122dd7c: 8b45fc                   mov eax, dword ptr [ebp - 4]
0122dd7f: e8fcecffff               call 0x122ca80 ; CIS_TDinRailOutputCGateAgent.TBasicDinRailOutputCGateAgent.GetDinRailOutputUnit
0122dd84: 8b10                     mov edx, dword ptr [eax]
0122dd86: ff92b0000000             call dword ptr [edx + 0xb0]
0122dd8c: 85c0                     test eax, eax
0122dd8e: 0f842f010000             je 0x122dec3
0122dd94: 8b45fc                   mov eax, dword ptr [ebp - 4]
0122dd97: e8e4ecffff               call 0x122ca80 ; CIS_TDinRailOutputCGateAgent.TBasicDinRailOutputCGateAgent.GetDinRailOutputUnit
0122dd9c: 8b80d0000000             mov eax, dword ptr [eax + 0xd0]
0122dda2: 8b10                     mov edx, dword ptr [eax]
0122dda4: ff526c                   call dword ptr [edx + 0x6c]
0122dda7: 8b45fc                   mov eax, dword ptr [ebp - 4]
0122ddaa: e8d1ecffff               call 0x122ca80 ; CIS_TDinRailOutputCGateAgent.TBasicDinRailOutputCGateAgent.GetDinRailOutputUnit
0122ddaf: 8b80d0000000             mov eax, dword ptr [eax + 0xd0]
0122ddb5: 8b10                     mov edx, dword ptr [eax]
0122ddb7: ff12                     call dword ptr [edx]
0122ddb9: 33c0                     xor eax, eax
0122ddbb: 55                       push ebp
0122ddbc: 68bcde2201               push 0x122debc
0122ddc1: 64ff30                   push dword ptr fs:[eax]
0122ddc4: 648920                   mov dword ptr fs:[eax], esp
0122ddc7: 8b45fc                   mov eax, dword ptr [ebp - 4]
0122ddca: e8b1ecffff               call 0x122ca80 ; CIS_TDinRailOutputCGateAgent.TBasicDinRailOutputCGateAgent.GetDinRailOutputUnit
0122ddcf: 8b80e8010000             mov eax, dword ptr [eax + 0x1e8]
0122ddd5: 8b10                     mov edx, dword ptr [eax]
0122ddd7: ff5258                   call dword ptr [edx + 0x58]
0122ddda: 48                       dec eax
0122dddb: 85c0                     test eax, eax
0122dddd: 0f8cb8000000             jl 0x122de9b
0122dde3: 40                       inc eax
0122dde4: 8945f0                   mov dword ptr [ebp - 0x10], eax
0122dde7: c745f800000000           mov dword ptr [ebp - 8], 0
0122ddee: 8d55e8                   lea edx, [ebp - 0x18]
0122ddf1: 8b45fc                   mov eax, dword ptr [ebp - 4]
0122ddf4: 8b801c010000             mov eax, dword ptr [eax + 0x11c]
0122ddfa: 8b08                     mov ecx, dword ptr [eax]
0122ddfc: ff512c                   call dword ptr [ecx + 0x2c]
0122ddff: 8b45e8                   mov eax, dword ptr [ebp - 0x18]
0122de02: 8d4dec                   lea ecx, [ebp - 0x14]
0122de05: ba00df2201               mov edx, 0x122df00
0122de0a: e819345cff               call 0x7f1228 ; CIS_Maths.StrToIntArray
0122de0f: 8b45ec                   mov eax, dword ptr [ebp - 0x14]
0122de12: b9ff000000               mov ecx, 0xff
0122de17: 8b55f8                   mov edx, dword ptr [ebp - 8]
0122de1a: e811315cff               call 0x7f0f30 ; CIS_Maths.IntArrayElementWithDefault
0122de1f: 8945f4                   mov dword ptr [ebp - 0xc], eax
0122de22: 8b45fc                   mov eax, dword ptr [ebp - 4]
0122de25: e856ecffff               call 0x122ca80 ; CIS_TDinRailOutputCGateAgent.TBasicDinRailOutputCGateAgent.GetDinRailOutputUnit
0122de2a: 8b10                     mov edx, dword ptr [eax]
0122de2c: ff92b0000000             call dword ptr [edx + 0xb0]
0122de32: 8b80b4000000             mov eax, dword ptr [eax + 0xb4]
0122de38: b101                     mov cl, 1
0122de3a: 8b55f4                   mov edx, dword ptr [ebp - 0xc]
0122de3d: e826adcfff               call 0xf28b68 ; CIS_TCommonCBus.TCBusGroupManager.GroupByAddress
0122de42: 50                       push eax
0122de43: 8b45fc                   mov eax, dword ptr [ebp - 4]
0122de46: e835ecffff               call 0x122ca80 ; CIS_TDinRailOutputCGateAgent.TBasicDinRailOutputCGateAgent.GetDinRailOutputUnit
0122de4b: 8b80e8010000             mov eax, dword ptr [eax + 0x1e8]
0122de51: 8b55f8                   mov edx, dword ptr [ebp - 8]
0122de54: e86fd1afff               call 0xd2afc8 ; CIS_TCBusDimmerUnit.TDimmerChannelCollection.GetItem
0122de59: 5a                       pop edx
0122de5a: e875caafff               call 0xd2a8d4 ; CIS_TCBusDimmerUnit.TDimmerChannel.SetGroup
0122de5f: 8b45fc                   mov eax, dword ptr [ebp - 4]
0122de62: e819ecffff               call 0x122ca80 ; CIS_TDinRailOutputCGateAgent.TBasicDinRailOutputCGateAgent.GetDinRailOutputUnit
0122de67: 8b80e8010000             mov eax, dword ptr [eax + 0x1e8]
0122de6d: 8b55f8                   mov edx, dword ptr [ebp - 8]
0122de70: e853d1afff               call 0xd2afc8 ; CIS_TCBusDimmerUnit.TDimmerChannelCollection.GetItem
0122de75: e816c0afff               call 0xd29e90 ; CIS_TCBusDimmerUnit.TDimmerChannel.GetGroup
0122de7a: 50                       push eax
0122de7b: 8b45fc                   mov eax, dword ptr [ebp - 4]
0122de7e: e8fdebffff               call 0x122ca80 ; CIS_TDinRailOutputCGateAgent.TBasicDinRailOutputCGateAgent.GetDinRailOutputUnit
0122de83: 8b80d0000000             mov eax, dword ptr [eax + 0xd0]
0122de89: 5a                       pop edx
0122de8a: 8b08                     mov ecx, dword ptr [eax]
0122de8c: ff5168                   call dword ptr [ecx + 0x68]
0122de8f: ff45f8                   inc dword ptr [ebp - 8]
0122de92: ff4df0                   dec dword ptr [ebp - 0x10]
0122de95: 0f8553ffffff             jne 0x122ddee
0122de9b: 33c0                     xor eax, eax
0122de9d: 5a                       pop edx
0122de9e: 59                       pop ecx
0122de9f: 59                       pop ecx
0122dea0: 648910                   mov dword ptr fs:[eax], edx
0122dea3: 68c3de2201               push 0x122dec3
0122dea8: 8b45fc                   mov eax, dword ptr [ebp - 4]
0122deab: e8d0ebffff               call 0x122ca80 ; CIS_TDinRailOutputCGateAgent.TBasicDinRailOutputCGateAgent.GetDinRailOutputUnit
0122deb0: 8b80d0000000             mov eax, dword ptr [eax + 0xd0]
0122deb6: 8b10                     mov edx, dword ptr [eax]
0122deb8: ff5208                   call dword ptr [edx + 8]
0122debb: c3                       ret 
0122debc: e9638d3dff               jmp 0x606c24 ; System.@HandleFinally
0122dec1: ebe5                     jmp 0x122dea8
0122dec3: 33c0                     xor eax, eax
0122dec5: 5a                       pop edx
0122dec6: 59                       pop ecx
0122dec7: 59                       pop ecx
0122dec8: 648910                   mov dword ptr fs:[eax], edx
0122decb: 68eede2201               push 0x122deee
0122ded0: 8d45e8                   lea eax, [ebp - 0x18]
0122ded3: e83caa3dff               call 0x608914 ; System.@UStrClr
0122ded8: 8d45ec                   lea eax, [ebp - 0x14]
0122dedb: 8b151c0e7f00             mov edx, dword ptr [0x7f0e1c]
0122dee1: e85ec93dff               call 0x60a844 ; System.@DynArrayClear
0122dee6: c3                       ret 
0122dee7: e9388d3dff               jmp 0x606c24 ; System.@HandleFinally
0122deec: ebe2                     jmp 0x122ded0
0122deee: 8be5                     mov esp, ebp
0122def0: 5d                       pop ebp
0122def1: c3                       ret 
0122def2: 0000                     add byte ptr [eax], al
0122def4: b004                     mov al, 4
0122def6: 0200                     add al, byte ptr [eax]
