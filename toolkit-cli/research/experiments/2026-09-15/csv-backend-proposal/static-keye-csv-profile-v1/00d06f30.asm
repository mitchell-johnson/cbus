00d06f30: 55                       push ebp
00d06f31: 8bec                     mov ebp, esp
00d06f33: 51                       push ecx
00d06f34: 8945fc                   mov dword ptr [ebp - 4], eax
00d06f37: 8b45fc                   mov eax, dword ptr [ebp - 4]
00d06f3a: e80591f9ff               call 0xca0044 ; CIS_TCBusKeyInputUnit.TCBusKeyInputUnit.InternalCreate
00d06f3f: 689072d000               push 0xd07290
00d06f44: 8b45fc                   mov eax, dword ptr [ebp - 4]
00d06f47: 8b4834                   mov ecx, dword ptr [eax + 0x34]
00d06f4a: b201                     mov dl, 1
00d06f4c: a1988cc900               mov eax, dword ptr [0xc98c98]
00d06f51: e83e2caeff               call 0x7e9b94 ; CIS_TCustomFlashObject.TFlashObjectCollection.Create
00d06f56: 8b55fc                   mov edx, dword ptr [ebp - 4]
00d06f59: 898244020000             mov dword ptr [edx + 0x244], eax
00d06f5f: 8b45fc                   mov eax, dword ptr [ebp - 4]
00d06f62: 8b8044020000             mov eax, dword ptr [eax + 0x244]
00d06f68: 8b55fc                   mov edx, dword ptr [ebp - 4]
00d06f6b: 895030                   mov dword ptr [eax + 0x30], edx
00d06f6e: 8b45fc                   mov eax, dword ptr [ebp - 4]
00d06f71: 8b8044020000             mov eax, dword ptr [eax + 0x244]
00d06f77: c7808000000050000000     mov dword ptr [eax + 0x80], 0x50
00d06f81: 8b45fc                   mov eax, dword ptr [ebp - 4]
00d06f84: 8b8044020000             mov eax, dword ptr [eax + 0x244]
00d06f8a: c7808400000014000000     mov dword ptr [eax + 0x84], 0x14
00d06f94: 8b45fc                   mov eax, dword ptr [ebp - 4]
00d06f97: 8b8044020000             mov eax, dword ptr [eax + 0x244]
00d06f9d: c7808800000028000000     mov dword ptr [eax + 0x88], 0x28
00d06fa7: 68ac72d000               push 0xd072ac
00d06fac: 6a00                     push 0
00d06fae: 6a00                     push 0
00d06fb0: 6a00                     push 0
00d06fb2: 8b45fc                   mov eax, dword ptr [ebp - 4]
00d06fb5: 8b4830                   mov ecx, dword ptr [eax + 0x30]
00d06fb8: b201                     mov dl, 1
00d06fba: a158d87d00               mov eax, dword ptr [0x7dd858]
00d06fbf: e88c6dadff               call 0x7ddd50 ; CIS_TObjectReferenceAttribute.TObjectReferenceAttribute.Create
00d06fc4: 8b55fc                   mov edx, dword ptr [ebp - 4]
00d06fc7: 898218020000             mov dword ptr [edx + 0x218], eax
00d06fcd: 8b45fc                   mov eax, dword ptr [ebp - 4]
00d06fd0: 8b8018020000             mov eax, dword ptr [eax + 0x218]
00d06fd6: 8b55fc                   mov edx, dword ptr [ebp - 4]
00d06fd9: 895064                   mov dword ptr [eax + 0x64], edx
00d06fdc: 8b12                     mov edx, dword ptr [edx]
00d06fde: 8b92e4010000             mov edx, dword ptr [edx + 0x1e4]
00d06fe4: 895060                   mov dword ptr [eax + 0x60], edx
00d06fe7: 68d872d000               push 0xd072d8
00d06fec: 6a00                     push 0
00d06fee: 6a00                     push 0
00d06ff0: 6a00                     push 0
00d06ff2: 8b45fc                   mov eax, dword ptr [ebp - 4]
00d06ff5: 8b4830                   mov ecx, dword ptr [eax + 0x30]
00d06ff8: b201                     mov dl, 1
00d06ffa: a16c427f00               mov eax, dword ptr [0x7f426c]
00d06fff: e80055aeff               call 0x7ec504 ; CIS_TCustomFlashObject.TFlashAttribute.Create
00d07004: 8b55fc                   mov edx, dword ptr [ebp - 4]
00d07007: 898220020000             mov dword ptr [edx + 0x220], eax
00d0700d: 680873d000               push 0xd07308
00d07012: 6a00                     push 0
00d07014: 6a00                     push 0
00d07016: 6a00                     push 0
00d07018: 8b45fc                   mov eax, dword ptr [ebp - 4]
00d0701b: 8b4830                   mov ecx, dword ptr [eax + 0x30]
00d0701e: b201                     mov dl, 1
00d07020: a16c427f00               mov eax, dword ptr [0x7f426c]
00d07025: e8da54aeff               call 0x7ec504 ; CIS_TCustomFlashObject.TFlashAttribute.Create
00d0702a: 8b55fc                   mov edx, dword ptr [ebp - 4]
00d0702d: 898224020000             mov dword ptr [edx + 0x224], eax
00d07033: 683c73d000               push 0xd0733c
00d07038: 6a00                     push 0
00d0703a: 6a00                     push 0
00d0703c: 6a00                     push 0
00d0703e: 8b45fc                   mov eax, dword ptr [ebp - 4]
00d07041: 8b4830                   mov ecx, dword ptr [eax + 0x30]
00d07044: b201                     mov dl, 1
00d07046: a174058500               mov eax, dword ptr [0x850574]
00d0704b: e8b454aeff               call 0x7ec504 ; CIS_TCustomFlashObject.TFlashAttribute.Create
00d07050: 8b55fc                   mov edx, dword ptr [ebp - 4]
00d07053: 898228020000             mov dword ptr [edx + 0x228], eax
00d07059: 688073d000               push 0xd07380
00d0705e: 6a00                     push 0
00d07060: 6a00                     push 0
00d07062: 6a00                     push 0
00d07064: 8b45fc                   mov eax, dword ptr [ebp - 4]
00d07067: 8b4830                   mov ecx, dword ptr [eax + 0x30]
00d0706a: b201                     mov dl, 1
00d0706c: a174058500               mov eax, dword ptr [0x850574]
00d07071: e88e54aeff               call 0x7ec504 ; CIS_TCustomFlashObject.TFlashAttribute.Create
00d07076: 8b55fc                   mov edx, dword ptr [ebp - 4]
00d07079: 89822c020000             mov dword ptr [edx + 0x22c], eax
00d0707f: 68bc73d000               push 0xd073bc
00d07084: 6a00                     push 0
00d07086: 6a00                     push 0
00d07088: 6a00                     push 0
00d0708a: 8b45fc                   mov eax, dword ptr [ebp - 4]
00d0708d: 8b4830                   mov ecx, dword ptr [eax + 0x30]
00d07090: b201                     mov dl, 1
00d07092: a16c427f00               mov eax, dword ptr [0x7f426c]
00d07097: e86854aeff               call 0x7ec504 ; CIS_TCustomFlashObject.TFlashAttribute.Create
00d0709c: 8b55fc                   mov edx, dword ptr [ebp - 4]
00d0709f: 898230020000             mov dword ptr [edx + 0x230], eax
00d070a5: 68ec73d000               push 0xd073ec
00d070aa: 6a00                     push 0
00d070ac: 6a00                     push 0
00d070ae: 6a00                     push 0
00d070b0: 8b45fc                   mov eax, dword ptr [ebp - 4]
00d070b3: 8b4830                   mov ecx, dword ptr [eax + 0x30]
00d070b6: b201                     mov dl, 1
00d070b8: a16c427f00               mov eax, dword ptr [0x7f426c]
00d070bd: e84254aeff               call 0x7ec504 ; CIS_TCustomFlashObject.TFlashAttribute.Create
00d070c2: 8b55fc                   mov edx, dword ptr [ebp - 4]
00d070c5: 898238020000             mov dword ptr [edx + 0x238], eax
00d070cb: 681c74d000               push 0xd0741c
00d070d0: 6a00                     push 0
00d070d2: 6a00                     push 0
00d070d4: 6a00                     push 0
00d070d6: 8b45fc                   mov eax, dword ptr [ebp - 4]
00d070d9: 8b4830                   mov ecx, dword ptr [eax + 0x30]
00d070dc: b201                     mov dl, 1
00d070de: a16c427f00               mov eax, dword ptr [0x7f426c]
00d070e3: e81c54aeff               call 0x7ec504 ; CIS_TCustomFlashObject.TFlashAttribute.Create
00d070e8: 8b55fc                   mov edx, dword ptr [ebp - 4]
00d070eb: 89823c020000             mov dword ptr [edx + 0x23c], eax
00d070f1: 684c74d000               push 0xd0744c
00d070f6: 6a00                     push 0
00d070f8: 6a00                     push 0
00d070fa: 6a00                     push 0
00d070fc: 8b45fc                   mov eax, dword ptr [ebp - 4]
00d070ff: 8b4830                   mov ecx, dword ptr [eax + 0x30]
00d07102: b201                     mov dl, 1
00d07104: a16c427f00               mov eax, dword ptr [0x7f426c]
00d07109: e8f653aeff               call 0x7ec504 ; CIS_TCustomFlashObject.TFlashAttribute.Create
00d0710e: 8b55fc                   mov edx, dword ptr [ebp - 4]
00d07111: 89821c020000             mov dword ptr [edx + 0x21c], eax
00d07117: 688874d000               push 0xd07488
00d0711c: 6a00                     push 0
00d0711e: 6a00                     push 0
00d07120: 6a00                     push 0
00d07122: 8b45fc                   mov eax, dword ptr [ebp - 4]
00d07125: 8b4830                   mov ecx, dword ptr [eax + 0x30]
00d07128: b201                     mov dl, 1
00d0712a: a1d0de7d00               mov eax, dword ptr [0x7dded0]
00d0712f: e8d053aeff               call 0x7ec504 ; CIS_TCustomFlashObject.TFlashAttribute.Create
00d07134: 8b55fc                   mov edx, dword ptr [ebp - 4]
00d07137: 898240020000             mov dword ptr [edx + 0x240], eax
00d0713d: 8b45fc                   mov eax, dword ptr [ebp - 4]
00d07140: e89738aeff               call 0x7ea9dc ; CIS_TCustomFlashObject.TCustomFlashObject.GetWorkSpace
00d07145: 50                       push eax
00d07146: 6a01                     push 1
00d07148: 6a00                     push 0
00d0714a: 8b45fc                   mov eax, dword ptr [ebp - 4]
00d0714d: 8b8844020000             mov ecx, dword ptr [eax + 0x244]
00d07153: b201                     mov dl, 1
00d07155: a19490c900               mov eax, dword ptr [0xc99094]
00d0715a: e8b53cf9ff               call 0xc9ae14 ; CIS_TInputKeyExtensionNeo.TNeoSceneManager.CreateInWorkSpace
00d0715f: 8bd0                     mov edx, eax
00d07161: 8b45fc                   mov eax, dword ptr [ebp - 4]
00d07164: 8b8040020000             mov eax, dword ptr [eax + 0x240]
00d0716a: 8b08                     mov ecx, dword ptr [eax]
00d0716c: ff91a8000000             call dword ptr [ecx + 0xa8]
00d07172: 68b074d000               push 0xd074b0
00d07177: 6a00                     push 0
00d07179: 6a00                     push 0
00d0717b: 6a00                     push 0
00d0717d: 8b45fc                   mov eax, dword ptr [ebp - 4]
00d07180: 8b4830                   mov ecx, dword ptr [eax + 0x30]
00d07183: b201                     mov dl, 1
00d07185: a16c427f00               mov eax, dword ptr [0x7f426c]
00d0718a: e87553aeff               call 0x7ec504 ; CIS_TCustomFlashObject.TFlashAttribute.Create
00d0718f: 8b55fc                   mov edx, dword ptr [ebp - 4]
00d07192: 898248020000             mov dword ptr [edx + 0x248], eax
00d07198: 68d874d000               push 0xd074d8
00d0719d: 6a00                     push 0
00d0719f: 6a00                     push 0
00d071a1: 6a00                     push 0
00d071a3: 8b45fc                   mov eax, dword ptr [ebp - 4]
00d071a6: 8b4830                   mov ecx, dword ptr [eax + 0x30]
00d071a9: b201                     mov dl, 1
00d071ab: a16c427f00               mov eax, dword ptr [0x7f426c]
00d071b0: e84f53aeff               call 0x7ec504 ; CIS_TCustomFlashObject.TFlashAttribute.Create
00d071b5: 8b55fc                   mov edx, dword ptr [ebp - 4]
00d071b8: 89824c020000             mov dword ptr [edx + 0x24c], eax
00d071be: 680875d000               push 0xd07508
00d071c3: a18469d000               mov eax, dword ptr [0xd06984]
00d071c8: 50                       push eax
00d071c9: 6a00                     push 0
00d071cb: 6a00                     push 0
00d071cd: 8b45fc                   mov eax, dword ptr [ebp - 4]
00d071d0: 8b4830                   mov ecx, dword ptr [eax + 0x30]
00d071d3: b201                     mov dl, 1
00d071d5: a1b47d8400               mov eax, dword ptr [0x847db4]
00d071da: e8c512b4ff               call 0x8484a4 ; CIS_TEnumeratedTypeAttribute.TEnumeratedTypeAttribute.Create
00d071df: 8b55fc                   mov edx, dword ptr [ebp - 4]
00d071e2: 898250020000             mov dword ptr [edx + 0x250], eax
00d071e8: 683075d000               push 0xd07530
00d071ed: 6a00                     push 0
00d071ef: 6a00                     push 0
00d071f1: 6a00                     push 0
00d071f3: 8b45fc                   mov eax, dword ptr [ebp - 4]
00d071f6: 8b4830                   mov ecx, dword ptr [eax + 0x30]
00d071f9: b201                     mov dl, 1
00d071fb: a16c427f00               mov eax, dword ptr [0x7f426c]
00d07200: e8ff52aeff               call 0x7ec504 ; CIS_TCustomFlashObject.TFlashAttribute.Create
00d07205: 8b55fc                   mov edx, dword ptr [ebp - 4]
00d07208: 898254020000             mov dword ptr [edx + 0x254], eax
00d0720e: 686475d000               push 0xd07564
00d07213: 6a00                     push 0
00d07215: 6a00                     push 0
00d07217: 6a00                     push 0
00d07219: 8b45fc                   mov eax, dword ptr [ebp - 4]
00d0721c: 8b4830                   mov ecx, dword ptr [eax + 0x30]
00d0721f: b201                     mov dl, 1
00d07221: a158d87d00               mov eax, dword ptr [0x7dd858]
00d07226: e8256badff               call 0x7ddd50 ; CIS_TObjectReferenceAttribute.TObjectReferenceAttribute.Create
00d0722b: 8b55fc                   mov edx, dword ptr [ebp - 4]
00d0722e: 898258020000             mov dword ptr [edx + 0x258], eax
00d07234: 689075d000               push 0xd07590
00d07239: 6a00                     push 0
00d0723b: 6a00                     push 0
00d0723d: 6a00                     push 0
00d0723f: 8b45fc                   mov eax, dword ptr [ebp - 4]
00d07242: 8b4830                   mov ecx, dword ptr [eax + 0x30]
00d07245: b201                     mov dl, 1
00d07247: a158d87d00               mov eax, dword ptr [0x7dd858]
00d0724c: e8ff6aadff               call 0x7ddd50 ; CIS_TObjectReferenceAttribute.TObjectReferenceAttribute.Create
00d07251: 8b55fc                   mov edx, dword ptr [ebp - 4]
00d07254: 89825c020000             mov dword ptr [edx + 0x25c], eax
00d0725a: 68b075d000               push 0xd075b0
00d0725f: 6a00                     push 0
00d07261: 6a00                     push 0
00d07263: 6a00                     push 0
00d07265: 8b45fc                   mov eax, dword ptr [ebp - 4]
00d07268: 8b4830                   mov ecx, dword ptr [eax + 0x30]
00d0726b: b201                     mov dl, 1
00d0726d: a158d87d00               mov eax, dword ptr [0x7dd858]
00d07272: e8d96aadff               call 0x7ddd50 ; CIS_TObjectReferenceAttribute.TObjectReferenceAttribute.Create
00d07277: 8b55fc                   mov edx, dword ptr [ebp - 4]
00d0727a: 898260020000             mov dword ptr [edx + 0x260], eax
00d07280: 59                       pop ecx
00d07281: 5d                       pop ebp
00d07282: c3                       ret 
00d07283: 00b0040200ff             add byte ptr [eax - 0xfffdfc], dh
