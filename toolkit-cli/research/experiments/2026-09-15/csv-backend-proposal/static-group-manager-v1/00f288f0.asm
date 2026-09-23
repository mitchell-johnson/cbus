00f288f0: 55                       push ebp
00f288f1: 8bec                     mov ebp, esp
00f288f3: 83c4f8                   add esp, -8
00f288f6: 8945fc                   mov dword ptr [ebp - 4], eax
00f288f9: 6a01                     push 1
00f288fb: 6a00                     push 0
00f288fd: 8b45fc                   mov eax, dword ptr [ebp - 4]
00f28900: 8b4030                   mov eax, dword ptr [eax + 0x30]
00f28903: e8d4208cff               call 0x7ea9dc ; CIS_TCustomFlashObject.TCustomFlashObject.GetWorkSpace
00f28908: 8bc8                     mov ecx, eax
00f2890a: b201                     mov dl, 1
00f2890c: a1d43cf200               mov eax, dword ptr [0xf23cd4]
00f28911: e8961d8cff               call 0x7ea6ac ; CIS_TCustomFlashObject.TCustomFlashObject.CreateInWorkSpace
00f28916: 8945f8                   mov dword ptr [ebp - 8], eax
00f28919: 8b55f8                   mov edx, dword ptr [ebp - 8]
00f2891c: 8b45fc                   mov eax, dword ptr [ebp - 4]
00f2891f: 8b08                     mov ecx, dword ptr [eax]
00f28921: ff5168                   call dword ptr [ecx + 0x68]
00f28924: 8b45f8                   mov eax, dword ptr [ebp - 8]
00f28927: 8b55fc                   mov edx, dword ptr [ebp - 4]
00f2892a: 899094000000             mov dword ptr [eax + 0x94], edx
00f28930: 8b45f8                   mov eax, dword ptr [ebp - 8]
00f28933: 59                       pop ecx
00f28934: 59                       pop ecx
00f28935: 5d                       pop ebp
00f28936: c3                       ret 
00f28937: 90                       nop 
