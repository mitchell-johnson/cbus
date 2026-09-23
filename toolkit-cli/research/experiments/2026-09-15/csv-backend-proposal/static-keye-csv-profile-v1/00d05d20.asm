00d05d20: 55                       push ebp
00d05d21: 8bec                     mov ebp, esp
00d05d23: 51                       push ecx
00d05d24: 8945fc                   mov dword ptr [ebp - 4], eax
00d05d27: 8b45fc                   mov eax, dword ptr [ebp - 4]
00d05d2a: e801120000               call 0xd06f30 ; CIS_TCBusNeoInputUnit.TCBusNeoInputUnit.InternalCreate
00d05d2f: 684c5fd000               push 0xd05f4c
00d05d34: a10c56d000               mov eax, dword ptr [0xd0560c]
00d05d39: 50                       push eax
00d05d3a: 6a00                     push 0
00d05d3c: 6a00                     push 0
00d05d3e: 8b45fc                   mov eax, dword ptr [ebp - 4]
00d05d41: 8b4830                   mov ecx, dword ptr [eax + 0x30]
00d05d44: b201                     mov dl, 1
00d05d46: a1b47d8400               mov eax, dword ptr [0x847db4]
00d05d4b: e85427b4ff               call 0x8484a4 ; CIS_TEnumeratedTypeAttribute.TEnumeratedTypeAttribute.Create
00d05d50: 8b55fc                   mov edx, dword ptr [ebp - 4]
00d05d53: 898278020000             mov dword ptr [edx + 0x278], eax
00d05d59: 68745fd000               push 0xd05f74
00d05d5e: 6a00                     push 0
00d05d60: 6a00                     push 0
00d05d62: 6a00                     push 0
00d05d64: 8b45fc                   mov eax, dword ptr [ebp - 4]
00d05d67: 8b4830                   mov ecx, dword ptr [eax + 0x30]
00d05d6a: b201                     mov dl, 1
00d05d6c: a16c427f00               mov eax, dword ptr [0x7f426c]
00d05d71: e88e67aeff               call 0x7ec504 ; CIS_TCustomFlashObject.TFlashAttribute.Create
00d05d76: 8b55fc                   mov edx, dword ptr [ebp - 4]
00d05d79: 89827c020000             mov dword ptr [edx + 0x27c], eax
00d05d7f: 68a05fd000               push 0xd05fa0
00d05d84: 6a00                     push 0
00d05d86: 6a00                     push 0
00d05d88: 6a00                     push 0
00d05d8a: 8b45fc                   mov eax, dword ptr [ebp - 4]
00d05d8d: 8b4830                   mov ecx, dword ptr [eax + 0x30]
00d05d90: b201                     mov dl, 1
00d05d92: a16c427f00               mov eax, dword ptr [0x7f426c]
00d05d97: e86867aeff               call 0x7ec504 ; CIS_TCustomFlashObject.TFlashAttribute.Create
00d05d9c: 8b55fc                   mov edx, dword ptr [ebp - 4]
00d05d9f: 898280020000             mov dword ptr [edx + 0x280], eax
00d05da5: 68c45fd000               push 0xd05fc4
00d05daa: 6a00                     push 0
00d05dac: 6a00                     push 0
00d05dae: 6a00                     push 0
00d05db0: 8b45fc                   mov eax, dword ptr [ebp - 4]
00d05db3: 8b4830                   mov ecx, dword ptr [eax + 0x30]
00d05db6: b201                     mov dl, 1
00d05db8: a158d87d00               mov eax, dword ptr [0x7dd858]
00d05dbd: e88e7fadff               call 0x7ddd50 ; CIS_TObjectReferenceAttribute.TObjectReferenceAttribute.Create
00d05dc2: 8b55fc                   mov edx, dword ptr [ebp - 4]
00d05dc5: 898284020000             mov dword ptr [edx + 0x284], eax
00d05dcb: 68f05fd000               push 0xd05ff0
00d05dd0: 6a00                     push 0
00d05dd2: 6a00                     push 0
00d05dd4: 6a00                     push 0
00d05dd6: 8b45fc                   mov eax, dword ptr [ebp - 4]
00d05dd9: 8b4830                   mov ecx, dword ptr [eax + 0x30]
00d05ddc: b201                     mov dl, 1
00d05dde: a16c427f00               mov eax, dword ptr [0x7f426c]
00d05de3: e81c67aeff               call 0x7ec504 ; CIS_TCustomFlashObject.TFlashAttribute.Create
00d05de8: 8b55fc                   mov edx, dword ptr [ebp - 4]
00d05deb: 898288020000             mov dword ptr [edx + 0x288], eax
00d05df1: 682860d000               push 0xd06028
00d05df6: 6a00                     push 0
00d05df8: 6a00                     push 0
00d05dfa: 6a00                     push 0
00d05dfc: 8b45fc                   mov eax, dword ptr [ebp - 4]
00d05dff: 8b4830                   mov ecx, dword ptr [eax + 0x30]
00d05e02: b201                     mov dl, 1
00d05e04: a174058500               mov eax, dword ptr [0x850574]
00d05e09: e8f666aeff               call 0x7ec504 ; CIS_TCustomFlashObject.TFlashAttribute.Create
00d05e0e: 8b55fc                   mov edx, dword ptr [ebp - 4]
00d05e11: 89828c020000             mov dword ptr [edx + 0x28c], eax
00d05e17: 686060d000               push 0xd06060
00d05e1c: 6a00                     push 0
00d05e1e: 6a00                     push 0
00d05e20: 6a00                     push 0
00d05e22: 8b45fc                   mov eax, dword ptr [ebp - 4]
00d05e25: 8b4830                   mov ecx, dword ptr [eax + 0x30]
00d05e28: b201                     mov dl, 1
00d05e2a: a16c427f00               mov eax, dword ptr [0x7f426c]
00d05e2f: e8d066aeff               call 0x7ec504 ; CIS_TCustomFlashObject.TFlashAttribute.Create
00d05e34: 8b55fc                   mov edx, dword ptr [ebp - 4]
00d05e37: 898290020000             mov dword ptr [edx + 0x290], eax
00d05e3d: 8b45fc                   mov eax, dword ptr [ebp - 4]
00d05e40: 8b8090020000             mov eax, dword ptr [eax + 0x290]
00d05e46: 8b55fc                   mov edx, dword ptr [ebp - 4]
00d05e49: 895064                   mov dword ptr [eax + 0x64], edx
00d05e4c: 8b12                     mov edx, dword ptr [edx]
00d05e4e: 8b9248020000             mov edx, dword ptr [edx + 0x248]
00d05e54: 895060                   mov dword ptr [eax + 0x60], edx
00d05e57: 689460d000               push 0xd06094
00d05e5c: 6a00                     push 0
00d05e5e: 6a00                     push 0
00d05e60: 6a00                     push 0
00d05e62: 8b45fc                   mov eax, dword ptr [ebp - 4]
00d05e65: 8b4830                   mov ecx, dword ptr [eax + 0x30]
00d05e68: b201                     mov dl, 1
00d05e6a: a158d87d00               mov eax, dword ptr [0x7dd858]
00d05e6f: e8dc7eadff               call 0x7ddd50 ; CIS_TObjectReferenceAttribute.TObjectReferenceAttribute.Create
00d05e74: 8b55fc                   mov edx, dword ptr [ebp - 4]
00d05e77: 898294020000             mov dword ptr [edx + 0x294], eax
00d05e7d: 68c860d000               push 0xd060c8
00d05e82: 6a00                     push 0
00d05e84: 6a00                     push 0
00d05e86: 6a00                     push 0
00d05e88: 8b45fc                   mov eax, dword ptr [ebp - 4]
00d05e8b: 8b4830                   mov ecx, dword ptr [eax + 0x30]
00d05e8e: b201                     mov dl, 1
00d05e90: a158d87d00               mov eax, dword ptr [0x7dd858]
00d05e95: e8b67eadff               call 0x7ddd50 ; CIS_TObjectReferenceAttribute.TObjectReferenceAttribute.Create
00d05e9a: 8b55fc                   mov edx, dword ptr [ebp - 4]
00d05e9d: 898298020000             mov dword ptr [edx + 0x298], eax
00d05ea3: 8b45fc                   mov eax, dword ptr [ebp - 4]
00d05ea6: 8b8098020000             mov eax, dword ptr [eax + 0x298]
00d05eac: 8b55fc                   mov edx, dword ptr [ebp - 4]
00d05eaf: 899094000000             mov dword ptr [eax + 0x94], edx
00d05eb5: 8b12                     mov edx, dword ptr [edx]
00d05eb7: 8b9250020000             mov edx, dword ptr [edx + 0x250]
00d05ebd: 899090000000             mov dword ptr [eax + 0x90], edx
00d05ec3: 8b45fc                   mov eax, dword ptr [ebp - 4]
00d05ec6: 8b8098020000             mov eax, dword ptr [eax + 0x298]
00d05ecc: 8b55fc                   mov edx, dword ptr [ebp - 4]
00d05ecf: 895064                   mov dword ptr [eax + 0x64], edx
00d05ed2: 8b12                     mov edx, dword ptr [edx]
00d05ed4: 8b924c020000             mov edx, dword ptr [edx + 0x24c]
00d05eda: 895060                   mov dword ptr [eax + 0x60], edx
00d05edd: 68fc60d000               push 0xd060fc
00d05ee2: 6a00                     push 0
00d05ee4: 6a00                     push 0
00d05ee6: 6a00                     push 0
00d05ee8: 8b45fc                   mov eax, dword ptr [ebp - 4]
00d05eeb: 8b4830                   mov ecx, dword ptr [eax + 0x30]
00d05eee: b201                     mov dl, 1
00d05ef0: a158d87d00               mov eax, dword ptr [0x7dd858]
00d05ef5: e8567eadff               call 0x7ddd50 ; CIS_TObjectReferenceAttribute.TObjectReferenceAttribute.Create
00d05efa: 8b55fc                   mov edx, dword ptr [ebp - 4]
00d05efd: 89829c020000             mov dword ptr [edx + 0x29c], eax
00d05f03: 8b45fc                   mov eax, dword ptr [ebp - 4]
00d05f06: 8b809c020000             mov eax, dword ptr [eax + 0x29c]
00d05f0c: 8b55fc                   mov edx, dword ptr [ebp - 4]
00d05f0f: 899094000000             mov dword ptr [eax + 0x94], edx
00d05f15: 8b12                     mov edx, dword ptr [edx]
00d05f17: 8b9258020000             mov edx, dword ptr [edx + 0x258]
00d05f1d: 899090000000             mov dword ptr [eax + 0x90], edx
00d05f23: 8b45fc                   mov eax, dword ptr [ebp - 4]
00d05f26: 8b809c020000             mov eax, dword ptr [eax + 0x29c]
00d05f2c: 8b55fc                   mov edx, dword ptr [ebp - 4]
00d05f2f: 895064                   mov dword ptr [eax + 0x64], edx
00d05f32: 8b12                     mov edx, dword ptr [edx]
00d05f34: 8b9254020000             mov edx, dword ptr [edx + 0x254]
00d05f3a: 895060                   mov dword ptr [eax + 0x60], edx
00d05f3d: 59                       pop ecx
00d05f3e: 5d                       pop ebp
00d05f3f: c3                       ret 
00d05f40: b004                     mov al, 4
00d05f42: 0200                     add al, byte ptr [eax]
