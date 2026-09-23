01398060: 832d544a450101           sub dword ptr [0x1454a54], 1
01398067: 0f838e000000             jae 0x13980fb
0139806d: e8aa2b88ff               call 0xc1ac1c ; CIS_TCISUnitFactory.InitialiseUnitFactory
01398072: e839dfb6ff               call 0xf05fb0 ; CIS_TProjectDocumentor.InitialiseUnitDocumentorFactory
01398077: 6808813901               push 0x1398108
0139807c: 6818813901               push 0x1398118
01398081: a1b03e3c01               mov eax, dword ptr [0x13c3eb0]
01398086: 8b00                     mov eax, dword ptr [eax]
01398088: 8b0d2c942201             mov ecx, dword ptr [0x122942c]
0139808e: ba28813901               mov edx, 0x1398128
01398093: e8c42a88ff               call 0xc1ab5c ; CIS_TCISUnitFactory.TUnitTypeFactory.RegisterUnitType
01398098: 6808813901               push 0x1398108
0139809d: 6818813901               push 0x1398118
013980a2: a1b03e3c01               mov eax, dword ptr [0x13c3eb0]
013980a7: 8b00                     mov eax, dword ptr [eax]
013980a9: 8b0d6c962201             mov ecx, dword ptr [0x122966c]
013980af: ba44813901               mov edx, 0x1398144
013980b4: e8a32a88ff               call 0xc1ab5c ; CIS_TCISUnitFactory.TUnitTypeFactory.RegisterUnitType
013980b9: 6808813901               push 0x1398108
013980be: 6818813901               push 0x1398118
013980c3: a164213c01               mov eax, dword ptr [0x13c2164]
013980c8: 8b00                     mov eax, dword ptr [eax]
013980ca: 8b0d9446d200             mov ecx, dword ptr [0xd24694]
013980d0: ba28813901               mov edx, 0x1398128
013980d5: e816deb6ff               call 0xf05ef0 ; CIS_TProjectDocumentor.TUnitTypeDocumentorFactory.RegisterUnitType
013980da: 6808813901               push 0x1398108
013980df: 6818813901               push 0x1398118
013980e4: a164213c01               mov eax, dword ptr [0x13c2164]
013980e9: 8b00                     mov eax, dword ptr [eax]
013980eb: 8b0d9446d200             mov ecx, dword ptr [0xd24694]
013980f1: ba44813901               mov edx, 0x1398144
013980f6: e8f5ddb6ff               call 0xf05ef0 ; CIS_TProjectDocumentor.TUnitTypeDocumentorFactory.RegisterUnitType
013980fb: c3                       ret 
013980fc: b004                     mov al, 4
013980fe: 0200                     add al, byte ptr [eax]
