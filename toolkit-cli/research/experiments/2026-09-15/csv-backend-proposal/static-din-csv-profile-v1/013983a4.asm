013983a4: 832d684a450101           sub dword ptr [0x1454a68], 1
013983ab: 734c                     jae 0x13983f9
013983ad: e86a2888ff               call 0xc1ac1c ; CIS_TCISUnitFactory.InitialiseUnitFactory
013983b2: e8f9dbb6ff               call 0xf05fb0 ; CIS_TProjectDocumentor.InitialiseUnitDocumentorFactory
013983b7: 6808843901               push 0x1398408
013983bc: 6818843901               push 0x1398418
013983c1: a1b03e3c01               mov eax, dword ptr [0x13c3eb0]
013983c6: 8b00                     mov eax, dword ptr [eax]
013983c8: 8b0d9ca42201             mov ecx, dword ptr [0x122a49c]
013983ce: ba28843901               mov edx, 0x1398428
013983d3: e8842788ff               call 0xc1ab5c ; CIS_TCISUnitFactory.TUnitTypeFactory.RegisterUnitType
013983d8: 6808843901               push 0x1398408
013983dd: 6818843901               push 0x1398418
013983e2: a164213c01               mov eax, dword ptr [0x13c2164]
013983e7: 8b00                     mov eax, dword ptr [eax]
013983e9: 8b0d9446d200             mov ecx, dword ptr [0xd24694]
013983ef: ba28843901               mov edx, 0x1398428
013983f4: e8f7dab6ff               call 0xf05ef0 ; CIS_TProjectDocumentor.TUnitTypeDocumentorFactory.RegisterUnitType
013983f9: c3                       ret 
013983fa: 0000                     add byte ptr [eax], al
013983fc: b004                     mov al, 4
013983fe: 0200                     add al, byte ptr [eax]
