01385328: 832de824450101           sub dword ptr [0x14524e8], 1
0138532f: 0f831a020000             jae 0x138554f
01385335: e8e25889ff               call 0xc1ac1c ; CIS_TCISUnitFactory.InitialiseUnitFactory
0138533a: e8710cb8ff               call 0xf05fb0 ; CIS_TProjectDocumentor.InitialiseUnitDocumentorFactory
0138533f: 685c553801               push 0x138555c
01385344: 6874553801               push 0x1385574
01385349: a1b03e3c01               mov eax, dword ptr [0x13c3eb0]
0138534e: 8b00                     mov eax, dword ptr [eax]
01385350: 8b0dd8edce00             mov ecx, dword ptr [0xceedd8]
01385356: ba90553801               mov edx, 0x1385590
0138535b: e8fc5789ff               call 0xc1ab5c ; CIS_TCISUnitFactory.TUnitTypeFactory.RegisterUnitType
01385360: 68b0553801               push 0x13855b0
01385365: 6874553801               push 0x1385574
0138536a: a1b03e3c01               mov eax, dword ptr [0x13c3eb0]
0138536f: 8b00                     mov eax, dword ptr [eax]
01385371: 8b0d48f0ce00             mov ecx, dword ptr [0xcef048]
01385377: bacc553801               mov edx, 0x13855cc
0138537c: e8db5789ff               call 0xc1ab5c ; CIS_TCISUnitFactory.TUnitTypeFactory.RegisterUnitType
01385381: 68b0553801               push 0x13855b0
01385386: 6874553801               push 0x1385574
0138538b: a1b03e3c01               mov eax, dword ptr [0x13c3eb0]
01385390: 8b00                     mov eax, dword ptr [eax]
01385392: 8b0dd8edce00             mov ecx, dword ptr [0xceedd8]
01385398: baec553801               mov edx, 0x13855ec
0138539d: e8ba5789ff               call 0xc1ab5c ; CIS_TCISUnitFactory.TUnitTypeFactory.RegisterUnitType
013853a2: 68b0553801               push 0x13855b0
013853a7: 6874553801               push 0x1385574
013853ac: a1b03e3c01               mov eax, dword ptr [0x13c3eb0]
013853b1: 8b00                     mov eax, dword ptr [eax]
013853b3: 8b0dd8edce00             mov ecx, dword ptr [0xceedd8]
013853b9: ba0c563801               mov edx, 0x138560c
013853be: e8995789ff               call 0xc1ab5c ; CIS_TCISUnitFactory.TUnitTypeFactory.RegisterUnitType
013853c3: 685c553801               push 0x138555c
013853c8: 6874553801               push 0x1385574
013853cd: a164213c01               mov eax, dword ptr [0x13c2164]
013853d2: 8b00                     mov eax, dword ptr [eax]
013853d4: 8b0d4ce7ce00             mov ecx, dword ptr [0xcee74c]
013853da: ba90553801               mov edx, 0x1385590
013853df: e80c0bb8ff               call 0xf05ef0 ; CIS_TProjectDocumentor.TUnitTypeDocumentorFactory.RegisterUnitType
013853e4: 68b0553801               push 0x13855b0
013853e9: 6874553801               push 0x1385574
013853ee: a164213c01               mov eax, dword ptr [0x13c2164]
013853f3: 8b00                     mov eax, dword ptr [eax]
013853f5: 8b0d4ce7ce00             mov ecx, dword ptr [0xcee74c]
013853fb: bacc553801               mov edx, 0x13855cc
01385400: e8eb0ab8ff               call 0xf05ef0 ; CIS_TProjectDocumentor.TUnitTypeDocumentorFactory.RegisterUnitType
01385405: 68b0553801               push 0x13855b0
0138540a: 6874553801               push 0x1385574
0138540f: a164213c01               mov eax, dword ptr [0x13c2164]
01385414: 8b00                     mov eax, dword ptr [eax]
01385416: 8b0d4ce7ce00             mov ecx, dword ptr [0xcee74c]
0138541c: baec553801               mov edx, 0x13855ec
01385421: e8ca0ab8ff               call 0xf05ef0 ; CIS_TProjectDocumentor.TUnitTypeDocumentorFactory.RegisterUnitType
01385426: 68b0553801               push 0x13855b0
0138542b: 6874553801               push 0x1385574
01385430: a164213c01               mov eax, dword ptr [0x13c2164]
01385435: 8b00                     mov eax, dword ptr [eax]
01385437: 8b0d4ce7ce00             mov ecx, dword ptr [0xcee74c]
0138543d: ba0c563801               mov edx, 0x138560c
01385442: e8a90ab8ff               call 0xf05ef0 ; CIS_TProjectDocumentor.TUnitTypeDocumentorFactory.RegisterUnitType
01385447: 682c563801               push 0x138562c
0138544c: 6848563801               push 0x1385648
01385451: a1b03e3c01               mov eax, dword ptr [0x13c3eb0]
01385456: 8b00                     mov eax, dword ptr [eax]
01385458: 8b0de8f5ce00             mov ecx, dword ptr [0xcef5e8]
0138545e: bacc553801               mov edx, 0x13855cc
01385463: e8f45689ff               call 0xc1ab5c ; CIS_TCISUnitFactory.TUnitTypeFactory.RegisterUnitType
01385468: 682c563801               push 0x138562c
0138546d: 6848563801               push 0x1385648
01385472: a1b03e3c01               mov eax, dword ptr [0x13c3eb0]
01385477: 8b00                     mov eax, dword ptr [eax]
01385479: 8b0db8f2ce00             mov ecx, dword ptr [0xcef2b8]
0138547f: baec553801               mov edx, 0x13855ec
01385484: e8d35689ff               call 0xc1ab5c ; CIS_TCISUnitFactory.TUnitTypeFactory.RegisterUnitType
01385489: 682c563801               push 0x138562c
0138548e: 6858563801               push 0x1385658
01385493: a1b03e3c01               mov eax, dword ptr [0x13c3eb0]
01385498: 8b00                     mov eax, dword ptr [eax]
0138549a: 8b0db8f2ce00             mov ecx, dword ptr [0xcef2b8]
013854a0: ba0c563801               mov edx, 0x138560c
013854a5: e8b25689ff               call 0xc1ab5c ; CIS_TCISUnitFactory.TUnitTypeFactory.RegisterUnitType
013854aa: 6870563801               push 0x1385670
013854af: 6848563801               push 0x1385648
013854b4: a1b03e3c01               mov eax, dword ptr [0x13c3eb0]
013854b9: 8b00                     mov eax, dword ptr [eax]
013854bb: 8b0de8e3ce00             mov ecx, dword ptr [0xcee3e8]
013854c1: ba0c563801               mov edx, 0x138560c
013854c6: e8915689ff               call 0xc1ab5c ; CIS_TCISUnitFactory.TUnitTypeFactory.RegisterUnitType
013854cb: 682c563801               push 0x138562c
013854d0: 6848563801               push 0x1385648
013854d5: a164213c01               mov eax, dword ptr [0x13c2164]
013854da: 8b00                     mov eax, dword ptr [eax]
013854dc: 8b0d84eace00             mov ecx, dword ptr [0xceea84]
013854e2: bacc553801               mov edx, 0x13855cc
013854e7: e8040ab8ff               call 0xf05ef0 ; CIS_TProjectDocumentor.TUnitTypeDocumentorFactory.RegisterUnitType
013854ec: 682c563801               push 0x138562c
013854f1: 6848563801               push 0x1385648
013854f6: a164213c01               mov eax, dword ptr [0x13c2164]
013854fb: 8b00                     mov eax, dword ptr [eax]
013854fd: 8b0d84eace00             mov ecx, dword ptr [0xceea84]
01385503: baec553801               mov edx, 0x13855ec
01385508: e8e309b8ff               call 0xf05ef0 ; CIS_TProjectDocumentor.TUnitTypeDocumentorFactory.RegisterUnitType
0138550d: 682c563801               push 0x138562c
01385512: 6858563801               push 0x1385658
01385517: a164213c01               mov eax, dword ptr [0x13c2164]
0138551c: 8b00                     mov eax, dword ptr [eax]
0138551e: 8b0d84eace00             mov ecx, dword ptr [0xceea84]
01385524: ba0c563801               mov edx, 0x138560c
01385529: e8c209b8ff               call 0xf05ef0 ; CIS_TProjectDocumentor.TUnitTypeDocumentorFactory.RegisterUnitType
0138552e: 6870563801               push 0x1385670
01385533: 6848563801               push 0x1385648
01385538: a164213c01               mov eax, dword ptr [0x13c2164]
0138553d: 8b00                     mov eax, dword ptr [eax]
0138553f: 8b0d5083ca00             mov ecx, dword ptr [0xca8350]
01385545: ba0c563801               mov edx, 0x138560c
0138554a: e8a109b8ff               call 0xf05ef0 ; CIS_TProjectDocumentor.TUnitTypeDocumentorFactory.RegisterUnitType
0138554f: c3                       ret 
01385550: b004                     mov al, 4
01385552: 0200                     add al, byte ptr [eax]
