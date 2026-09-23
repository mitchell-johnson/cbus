00c9dcc0: 55                       push ebp
00c9dcc1: 8bec                     mov ebp, esp
00c9dcc3: 51                       push ecx
00c9dcc4: 8945fc                   mov dword ptr [ebp - 4], eax
00c9dcc7: 8b45fc                   mov eax, dword ptr [ebp - 4]
00c9dcca: e8a9f60600               call 0xd0d378 ; CIS_TCustomKeyInputUnit.TCustomKeyInputUnit.InternalCreate
00c9dccf: 6844dec900               push 0xc9de44
00c9dcd4: 8b45fc                   mov eax, dword ptr [ebp - 4]
00c9dcd7: 8b4834                   mov ecx, dword ptr [eax + 0x34]
00c9dcda: b201                     mov dl, 1
00c9dcdc: a1f0e5d000               mov eax, dword ptr [0xd0e5f0]
00c9dce1: e8e6620700               call 0xd13fcc ; CIS_TInputKey.TInputKeyCollection.Create
00c9dce6: 8b55fc                   mov edx, dword ptr [ebp - 4]
00c9dce9: 8982e8010000             mov dword ptr [edx + 0x1e8], eax
00c9dcef: 8b45fc                   mov eax, dword ptr [ebp - 4]
00c9dcf2: 8b80e8010000             mov eax, dword ptr [eax + 0x1e8]
00c9dcf8: 8b55fc                   mov edx, dword ptr [ebp - 4]
00c9dcfb: 895030                   mov dword ptr [eax + 0x30], edx
00c9dcfe: 8b45fc                   mov eax, dword ptr [ebp - 4]
00c9dd01: 8b90c8010000             mov edx, dword ptr [eax + 0x1c8]
00c9dd07: 8b45fc                   mov eax, dword ptr [ebp - 4]
00c9dd0a: 8b80e8010000             mov eax, dword ptr [eax + 0x1e8]
00c9dd10: e817640700               call 0xd1412c ; CIS_TInputKey.TInputKeyCollection.SetBlockCollection
00c9dd15: 8b45fc                   mov eax, dword ptr [ebp - 4]
00c9dd18: e8b7040000               call 0xc9e1d4 ; CIS_TCoreKeyInputUnit.TCoreKeyInputUnit.MaximumVirtualKeyCount
00c9dd1d: 8bd0                     mov edx, eax
00c9dd1f: 8b45fc                   mov eax, dword ptr [ebp - 4]
00c9dd22: 8b80e8010000             mov eax, dword ptr [eax + 0x1e8]
00c9dd28: 8b08                     mov ecx, dword ptr [eax]
00c9dd2a: ff91b4000000             call dword ptr [ecx + 0xb4]
00c9dd30: 8b45fc                   mov eax, dword ptr [ebp - 4]
00c9dd33: 8b80e8010000             mov eax, dword ptr [eax + 0x1e8]
00c9dd39: e83e630700               call 0xd1407c ; CIS_TInputKey.TInputKeyCollection.CreateAllExtensions
00c9dd3e: 6864dec900               push 0xc9de64
00c9dd43: a100d7c900               mov eax, dword ptr [0xc9d700]
00c9dd48: 50                       push eax
00c9dd49: 6a00                     push 0
00c9dd4b: 6a00                     push 0
00c9dd4d: 8b45fc                   mov eax, dword ptr [ebp - 4]
00c9dd50: 8b4830                   mov ecx, dword ptr [eax + 0x30]
00c9dd53: b201                     mov dl, 1
00c9dd55: a1b47d8400               mov eax, dword ptr [0x847db4]
00c9dd5a: e845a7baff               call 0x8484a4 ; CIS_TEnumeratedTypeAttribute.TEnumeratedTypeAttribute.Create
00c9dd5f: 8b55fc                   mov edx, dword ptr [ebp - 4]
00c9dd62: 8982ec010000             mov dword ptr [edx + 0x1ec], eax
00c9dd68: 688cdec900               push 0xc9de8c
00c9dd6d: a15cd7c900               mov eax, dword ptr [0xc9d75c]
00c9dd72: 50                       push eax
00c9dd73: 6a00                     push 0
00c9dd75: 6a00                     push 0
00c9dd77: 8b45fc                   mov eax, dword ptr [ebp - 4]
00c9dd7a: 8b4830                   mov ecx, dword ptr [eax + 0x30]
00c9dd7d: b201                     mov dl, 1
00c9dd7f: a1b47d8400               mov eax, dword ptr [0x847db4]
00c9dd84: e81ba7baff               call 0x8484a4 ; CIS_TEnumeratedTypeAttribute.TEnumeratedTypeAttribute.Create
00c9dd89: 8b55fc                   mov edx, dword ptr [ebp - 4]
00c9dd8c: 8982f0010000             mov dword ptr [edx + 0x1f0], eax
00c9dd92: 68ccdec900               push 0xc9decc
00c9dd97: 6a00                     push 0
00c9dd99: 6a00                     push 0
00c9dd9b: 6a00                     push 0
00c9dd9d: 8b45fc                   mov eax, dword ptr [ebp - 4]
00c9dda0: 8b4830                   mov ecx, dword ptr [eax + 0x30]
00c9dda3: b201                     mov dl, 1
00c9dda5: a174058500               mov eax, dword ptr [0x850574]
00c9ddaa: e855e7b4ff               call 0x7ec504 ; CIS_TCustomFlashObject.TFlashAttribute.Create
00c9ddaf: 8b55fc                   mov edx, dword ptr [ebp - 4]
00c9ddb2: 8982f4010000             mov dword ptr [edx + 0x1f4], eax
00c9ddb8: 680cdfc900               push 0xc9df0c
00c9ddbd: 6a00                     push 0
00c9ddbf: 6a00                     push 0
00c9ddc1: 6a00                     push 0
00c9ddc3: 8b45fc                   mov eax, dword ptr [ebp - 4]
00c9ddc6: 8b4830                   mov ecx, dword ptr [eax + 0x30]
00c9ddc9: b201                     mov dl, 1
00c9ddcb: a158d87d00               mov eax, dword ptr [0x7dd858]
00c9ddd0: e87bffb3ff               call 0x7ddd50 ; CIS_TObjectReferenceAttribute.TObjectReferenceAttribute.Create
00c9ddd5: 8b55fc                   mov edx, dword ptr [ebp - 4]
00c9ddd8: 8982f8010000             mov dword ptr [edx + 0x1f8], eax
00c9ddde: 684cdfc900               push 0xc9df4c
00c9dde3: 6a00                     push 0
00c9dde5: 6a00                     push 0
00c9dde7: 6a00                     push 0
00c9dde9: 8b45fc                   mov eax, dword ptr [ebp - 4]
00c9ddec: 8b4830                   mov ecx, dword ptr [eax + 0x30]
00c9ddef: b201                     mov dl, 1
00c9ddf1: a16c427f00               mov eax, dword ptr [0x7f426c]
00c9ddf6: e809e7b4ff               call 0x7ec504 ; CIS_TCustomFlashObject.TFlashAttribute.Create
00c9ddfb: 8b55fc                   mov edx, dword ptr [ebp - 4]
00c9ddfe: 8982fc010000             mov dword ptr [edx + 0x1fc], eax
00c9de04: 6890dfc900               push 0xc9df90
00c9de09: 6a00                     push 0
00c9de0b: 6a00                     push 0
00c9de0d: 6a00                     push 0
00c9de0f: 8b45fc                   mov eax, dword ptr [ebp - 4]
00c9de12: 8b4830                   mov ecx, dword ptr [eax + 0x30]
00c9de15: b201                     mov dl, 1
00c9de17: a174058500               mov eax, dword ptr [0x850574]
00c9de1c: e8e3e6b4ff               call 0x7ec504 ; CIS_TCustomFlashObject.TFlashAttribute.Create
00c9de21: 8b55fc                   mov edx, dword ptr [ebp - 4]
00c9de24: 898200020000             mov dword ptr [edx + 0x200], eax
00c9de2a: 8b45fc                   mov eax, dword ptr [ebp - 4]
00c9de2d: 8b10                     mov edx, dword ptr [eax]
00c9de2f: ff92cc010000             call dword ptr [edx + 0x1cc]
00c9de35: 59                       pop ecx
00c9de36: 5d                       pop ebp
00c9de37: c3                       ret 
00c9de38: b004                     mov al, 4
00c9de3a: 0200                     add al, byte ptr [eax]
