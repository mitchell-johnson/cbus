00f28954: 55                       push ebp
00f28955: 8bec                     mov ebp, esp
00f28957: 83c4f4                   add esp, -0xc
00f2895a: 8955f8                   mov dword ptr [ebp - 8], edx
00f2895d: 8945fc                   mov dword ptr [ebp - 4], eax
00f28960: 8b55f8                   mov edx, dword ptr [ebp - 8]
00f28963: 8b45fc                   mov eax, dword ptr [ebp - 4]
00f28966: e809068cff               call 0x7e8f74 ; CIS_TCustomFlashObject.TFlashObjectReferenceCollection.GetItem
00f2896b: 8945f4                   mov dword ptr [ebp - 0xc], eax
00f2896e: 8b45f4                   mov eax, dword ptr [ebp - 0xc]
00f28971: 8be5                     mov esp, ebp
00f28973: 5d                       pop ebp
00f28974: c3                       ret 
00f28975: 8d4000                   lea eax, [eax]
