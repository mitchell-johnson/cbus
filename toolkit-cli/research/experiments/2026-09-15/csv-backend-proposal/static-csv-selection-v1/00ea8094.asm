00ea8094: 55                       push ebp
00ea8095: 8bec                     mov ebp, esp
00ea8097: 83c498                   add esp, -0x68
00ea809a: b88c81ea00               mov eax, 0xea818c
00ea809f: 894598                   mov dword ptr [ebp - 0x68], eax
00ea80a2: b8b481ea00               mov eax, 0xea81b4
00ea80a7: 89459c                   mov dword ptr [ebp - 0x64], eax
00ea80aa: b8d481ea00               mov eax, 0xea81d4
00ea80af: 8945a0                   mov dword ptr [ebp - 0x60], eax
00ea80b2: b8f481ea00               mov eax, 0xea81f4
00ea80b7: 8945a4                   mov dword ptr [ebp - 0x5c], eax
00ea80ba: b81482ea00               mov eax, 0xea8214
00ea80bf: 8945a8                   mov dword ptr [ebp - 0x58], eax
00ea80c2: b84082ea00               mov eax, 0xea8240
00ea80c7: 8945ac                   mov dword ptr [ebp - 0x54], eax
00ea80ca: b86882ea00               mov eax, 0xea8268
00ea80cf: 8945b0                   mov dword ptr [ebp - 0x50], eax
00ea80d2: b89882ea00               mov eax, 0xea8298
00ea80d7: 8945b4                   mov dword ptr [ebp - 0x4c], eax
00ea80da: b8cc82ea00               mov eax, 0xea82cc
00ea80df: 8945b8                   mov dword ptr [ebp - 0x48], eax
00ea80e2: b80483ea00               mov eax, 0xea8304
00ea80e7: 8945bc                   mov dword ptr [ebp - 0x44], eax
00ea80ea: b81c83ea00               mov eax, 0xea831c
00ea80ef: 8945c0                   mov dword ptr [ebp - 0x40], eax
00ea80f2: b83883ea00               mov eax, 0xea8338
00ea80f7: 8945c4                   mov dword ptr [ebp - 0x3c], eax
00ea80fa: b85483ea00               mov eax, 0xea8354
00ea80ff: 8945c8                   mov dword ptr [ebp - 0x38], eax
00ea8102: b87083ea00               mov eax, 0xea8370
00ea8107: 8945cc                   mov dword ptr [ebp - 0x34], eax
00ea810a: b88c83ea00               mov eax, 0xea838c
00ea810f: 8945d0                   mov dword ptr [ebp - 0x30], eax
00ea8112: b8a883ea00               mov eax, 0xea83a8
00ea8117: 8945d4                   mov dword ptr [ebp - 0x2c], eax
00ea811a: b8c483ea00               mov eax, 0xea83c4
00ea811f: 8945d8                   mov dword ptr [ebp - 0x28], eax
00ea8122: b8e083ea00               mov eax, 0xea83e0
00ea8127: 8945dc                   mov dword ptr [ebp - 0x24], eax
00ea812a: b8fc83ea00               mov eax, 0xea83fc
00ea812f: 8945e0                   mov dword ptr [ebp - 0x20], eax
00ea8132: b81884ea00               mov eax, 0xea8418
00ea8137: 8945e4                   mov dword ptr [ebp - 0x1c], eax
00ea813a: b83884ea00               mov eax, 0xea8438
00ea813f: 8945e8                   mov dword ptr [ebp - 0x18], eax
00ea8142: b85884ea00               mov eax, 0xea8458
00ea8147: 8945ec                   mov dword ptr [ebp - 0x14], eax
00ea814a: b87884ea00               mov eax, 0xea8478
00ea814f: 8945f0                   mov dword ptr [ebp - 0x10], eax
00ea8152: b89884ea00               mov eax, 0xea8498
00ea8157: 8945f4                   mov dword ptr [ebp - 0xc], eax
00ea815a: b8b884ea00               mov eax, 0xea84b8
00ea815f: 8945f8                   mov dword ptr [ebp - 8], eax
00ea8162: b8d884ea00               mov eax, 0xea84d8
00ea8167: 8945fc                   mov dword ptr [ebp - 4], eax
00ea816a: 8d5598                   lea edx, [ebp - 0x68]
00ea816d: b919000000               mov ecx, 0x19
00ea8172: a13c438500               mov eax, dword ptr [0x85433c]
00ea8177: e8a4fd99ff               call 0x847f20 ; CIS_TEnumeratedTypeAttribute.RegisterEnumeratedValueDescriptions
00ea817c: 8be5                     mov esp, ebp
00ea817e: 5d                       pop ebp
00ea817f: c3                       ret
00ea8180: b004                     mov al, 4
00ea8182: 0200                     add al, byte ptr [eax]
