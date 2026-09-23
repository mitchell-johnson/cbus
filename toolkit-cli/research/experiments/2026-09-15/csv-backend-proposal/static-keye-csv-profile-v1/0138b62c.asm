0138b62c: 832d282a450101           sub dword ptr [0x1452a28], 1
0138b633: 0f831a020000             jae 0x138b853
0138b639: e8def588ff               call 0xc1ac1c ; CIS_TCISUnitFactory.InitialiseUnitFactory
0138b63e: e86da9b7ff               call 0xf05fb0 ; CIS_TProjectDocumentor.InitialiseUnitDocumentorFactory
0138b643: 6860b83801               push 0x138b860
0138b648: 6870b83801               push 0x138b870
0138b64d: a1b03e3c01               mov eax, dword ptr [0x13c3eb0]
0138b652: 8b00                     mov eax, dword ptr [eax]
0138b654: 8b0dfc8cea00             mov ecx, dword ptr [0xea8cfc]
0138b65a: ba80b83801               mov edx, 0x138b880
0138b65f: e8f8f488ff               call 0xc1ab5c ; CIS_TCISUnitFactory.TUnitTypeFactory.RegisterUnitType
0138b664: 6860b83801               push 0x138b860
0138b669: 6870b83801               push 0x138b870
0138b66e: a1b03e3c01               mov eax, dword ptr [0x13c3eb0]
0138b673: 8b00                     mov eax, dword ptr [eax]
0138b675: 8b0dfc8cea00             mov ecx, dword ptr [0xea8cfc]
0138b67b: ba98b83801               mov edx, 0x138b898
0138b680: e8d7f488ff               call 0xc1ab5c ; CIS_TCISUnitFactory.TUnitTypeFactory.RegisterUnitType
0138b685: 6860b83801               push 0x138b860
0138b68a: 6870b83801               push 0x138b870
0138b68f: a1b03e3c01               mov eax, dword ptr [0x13c3eb0]
0138b694: 8b00                     mov eax, dword ptr [eax]
0138b696: 8b0dfc8cea00             mov ecx, dword ptr [0xea8cfc]
0138b69c: bab0b83801               mov edx, 0x138b8b0
0138b6a1: e8b6f488ff               call 0xc1ab5c ; CIS_TCISUnitFactory.TUnitTypeFactory.RegisterUnitType
0138b6a6: 6860b83801               push 0x138b860
0138b6ab: 6870b83801               push 0x138b870
0138b6b0: a1b03e3c01               mov eax, dword ptr [0x13c3eb0]
0138b6b5: 8b00                     mov eax, dword ptr [eax]
0138b6b7: 8b0dfc8cea00             mov ecx, dword ptr [0xea8cfc]
0138b6bd: bac8b83801               mov edx, 0x138b8c8
0138b6c2: e895f488ff               call 0xc1ab5c ; CIS_TCISUnitFactory.TUnitTypeFactory.RegisterUnitType
0138b6c7: 6860b83801               push 0x138b860
0138b6cc: 6870b83801               push 0x138b870
0138b6d1: a1b03e3c01               mov eax, dword ptr [0x13c3eb0]
0138b6d6: 8b00                     mov eax, dword ptr [eax]
0138b6d8: 8b0dfc8cea00             mov ecx, dword ptr [0xea8cfc]
0138b6de: bae0b83801               mov edx, 0x138b8e0
0138b6e3: e874f488ff               call 0xc1ab5c ; CIS_TCISUnitFactory.TUnitTypeFactory.RegisterUnitType
0138b6e8: 6860b83801               push 0x138b860
0138b6ed: 6870b83801               push 0x138b870
0138b6f2: a1b03e3c01               mov eax, dword ptr [0x13c3eb0]
0138b6f7: 8b00                     mov eax, dword ptr [eax]
0138b6f9: 8b0dfc8cea00             mov ecx, dword ptr [0xea8cfc]
0138b6ff: bafcb83801               mov edx, 0x138b8fc
0138b704: e853f488ff               call 0xc1ab5c ; CIS_TCISUnitFactory.TUnitTypeFactory.RegisterUnitType
0138b709: 6860b83801               push 0x138b860
0138b70e: 6870b83801               push 0x138b870
0138b713: a1b03e3c01               mov eax, dword ptr [0x13c3eb0]
0138b718: 8b00                     mov eax, dword ptr [eax]
0138b71a: 8b0dfc8cea00             mov ecx, dword ptr [0xea8cfc]
0138b720: ba18b93801               mov edx, 0x138b918
0138b725: e832f488ff               call 0xc1ab5c ; CIS_TCISUnitFactory.TUnitTypeFactory.RegisterUnitType
0138b72a: 6860b83801               push 0x138b860
0138b72f: 6870b83801               push 0x138b870
0138b734: a1b03e3c01               mov eax, dword ptr [0x13c3eb0]
0138b739: 8b00                     mov eax, dword ptr [eax]
0138b73b: 8b0dfc8cea00             mov ecx, dword ptr [0xea8cfc]
0138b741: ba34b93801               mov edx, 0x138b934
0138b746: e811f488ff               call 0xc1ab5c ; CIS_TCISUnitFactory.TUnitTypeFactory.RegisterUnitType
0138b74b: 6860b83801               push 0x138b860
0138b750: 6870b83801               push 0x138b870
0138b755: a164213c01               mov eax, dword ptr [0x13c2164]
0138b75a: 8b00                     mov eax, dword ptr [eax]
0138b75c: 8b0d20d9cc00             mov ecx, dword ptr [0xccd920]
0138b762: ba80b83801               mov edx, 0x138b880
0138b767: e884a7b7ff               call 0xf05ef0 ; CIS_TProjectDocumentor.TUnitTypeDocumentorFactory.RegisterUnitType
0138b76c: 6860b83801               push 0x138b860
0138b771: 6870b83801               push 0x138b870
0138b776: a164213c01               mov eax, dword ptr [0x13c2164]
0138b77b: 8b00                     mov eax, dword ptr [eax]
0138b77d: 8b0d20d9cc00             mov ecx, dword ptr [0xccd920]
0138b783: ba98b83801               mov edx, 0x138b898
0138b788: e863a7b7ff               call 0xf05ef0 ; CIS_TProjectDocumentor.TUnitTypeDocumentorFactory.RegisterUnitType
0138b78d: 6860b83801               push 0x138b860
0138b792: 6870b83801               push 0x138b870
0138b797: a164213c01               mov eax, dword ptr [0x13c2164]
0138b79c: 8b00                     mov eax, dword ptr [eax]
0138b79e: 8b0d20d9cc00             mov ecx, dword ptr [0xccd920]
0138b7a4: bab0b83801               mov edx, 0x138b8b0
0138b7a9: e842a7b7ff               call 0xf05ef0 ; CIS_TProjectDocumentor.TUnitTypeDocumentorFactory.RegisterUnitType
0138b7ae: 6860b83801               push 0x138b860
0138b7b3: 6870b83801               push 0x138b870
0138b7b8: a164213c01               mov eax, dword ptr [0x13c2164]
0138b7bd: 8b00                     mov eax, dword ptr [eax]
0138b7bf: 8b0d20d9cc00             mov ecx, dword ptr [0xccd920]
0138b7c5: bac8b83801               mov edx, 0x138b8c8
0138b7ca: e821a7b7ff               call 0xf05ef0 ; CIS_TProjectDocumentor.TUnitTypeDocumentorFactory.RegisterUnitType
0138b7cf: 6860b83801               push 0x138b860
0138b7d4: 6870b83801               push 0x138b870
0138b7d9: a164213c01               mov eax, dword ptr [0x13c2164]
0138b7de: 8b00                     mov eax, dword ptr [eax]
0138b7e0: 8b0d20d9cc00             mov ecx, dword ptr [0xccd920]
0138b7e6: bae0b83801               mov edx, 0x138b8e0
0138b7eb: e800a7b7ff               call 0xf05ef0 ; CIS_TProjectDocumentor.TUnitTypeDocumentorFactory.RegisterUnitType
0138b7f0: 6860b83801               push 0x138b860
0138b7f5: 6870b83801               push 0x138b870
0138b7fa: a164213c01               mov eax, dword ptr [0x13c2164]
0138b7ff: 8b00                     mov eax, dword ptr [eax]
0138b801: 8b0d20d9cc00             mov ecx, dword ptr [0xccd920]
0138b807: bafcb83801               mov edx, 0x138b8fc
0138b80c: e8dfa6b7ff               call 0xf05ef0 ; CIS_TProjectDocumentor.TUnitTypeDocumentorFactory.RegisterUnitType
0138b811: 6860b83801               push 0x138b860
0138b816: 6870b83801               push 0x138b870
0138b81b: a164213c01               mov eax, dword ptr [0x13c2164]
0138b820: 8b00                     mov eax, dword ptr [eax]
0138b822: 8b0d20d9cc00             mov ecx, dword ptr [0xccd920]
0138b828: ba18b93801               mov edx, 0x138b918
0138b82d: e8bea6b7ff               call 0xf05ef0 ; CIS_TProjectDocumentor.TUnitTypeDocumentorFactory.RegisterUnitType
0138b832: 6860b83801               push 0x138b860
0138b837: 6870b83801               push 0x138b870
0138b83c: a164213c01               mov eax, dword ptr [0x13c2164]
0138b841: 8b00                     mov eax, dword ptr [eax]
0138b843: 8b0d20d9cc00             mov ecx, dword ptr [0xccd920]
0138b849: ba34b93801               mov edx, 0x138b934
0138b84e: e89da6b7ff               call 0xf05ef0 ; CIS_TProjectDocumentor.TUnitTypeDocumentorFactory.RegisterUnitType
0138b853: c3                       ret 
0138b854: b004                     mov al, 4
0138b856: 0200                     add al, byte ptr [eax]
