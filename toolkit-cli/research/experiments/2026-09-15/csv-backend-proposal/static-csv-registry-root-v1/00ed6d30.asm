00ed6d30: 55                       push ebp
00ed6d31: 8bec                     mov ebp, esp
00ed6d33: 51                       push ecx
00ed6d34: b909000000               mov ecx, 9
00ed6d39: 6a00                     push 0
00ed6d3b: 6a00                     push 0
00ed6d3d: 49                       dec ecx
00ed6d3e: 75f9                     jne 0xed6d39
00ed6d40: 51                       push ecx
00ed6d41: 874dfc                   xchg dword ptr [ebp - 4], ecx
00ed6d44: 53                       push ebx
00ed6d45: 84d2                     test dl, dl
00ed6d47: 7408                     je 0xed6d51
00ed6d49: 83c4f0                   add esp, -0x10
00ed6d4c: e80ffa72ff               call 0x606760 ; System.@ClassCreate
00ed6d51: 884de3                   mov byte ptr [ebp - 0x1d], cl
00ed6d54: 8855fb                   mov byte ptr [ebp - 5], dl
00ed6d57: 8945fc                   mov dword ptr [ebp - 4], eax
00ed6d5a: 33c0                     xor eax, eax
00ed6d5c: 55                       push ebp
00ed6d5d: 680f70ed00               push 0xed700f
00ed6d62: 64ff30                   push dword ptr fs:[eax]
00ed6d65: 648920                   mov dword ptr fs:[eax], esp
00ed6d68: b101                     mov cl, 1
00ed6d6a: 33d2                     xor edx, edx
00ed6d6c: 8b45fc                   mov eax, dword ptr [ebp - 4]
00ed6d6f: e8f88b0300               call 0xf0f96c ; CIS_TApplicationManager.TApplicationManager.Create
00ed6d74: 8b45fc                   mov eax, dword ptr [ebp - 4]
00ed6d77: 83c040                   add eax, 0x40
00ed6d7a: ba4470ed00               mov edx, 0xed7044
00ed6d7f: e8a01b73ff               call 0x608924 ; System.@UStrAsg
00ed6d84: 33c9                     xor ecx, ecx
00ed6d86: b201                     mov dl, 1
00ed6d88: a18c93c100               mov eax, dword ptr [0xc1938c]
00ed6d8d: e86228d4ff               call 0xc195f4 ; CIS_TCGateSitesWorkspace.TCGateSitesWorkspace.Create
00ed6d92: 8b55fc                   mov edx, dword ptr [ebp - 4]
00ed6d95: 894278                   mov dword ptr [edx + 0x78], eax
00ed6d98: 6a01                     push 1
00ed6d9a: 6a00                     push 0
00ed6d9c: 8b45fc                   mov eax, dword ptr [ebp - 4]
00ed6d9f: 8b4878                   mov ecx, dword ptr [eax + 0x78]
00ed6da2: b201                     mov dl, 1
00ed6da4: a1248bc100               mov eax, dword ptr [0xc18b24]
00ed6da9: e8fe3891ff               call 0x7ea6ac ; CIS_TCustomFlashObject.TCustomFlashObject.CreateInWorkSpace
00ed6dae: 8b55fc                   mov edx, dword ptr [ebp - 4]
00ed6db1: 894268                   mov dword ptr [edx + 0x68], eax
00ed6db4: 8b45fc                   mov eax, dword ptr [ebp - 4]
00ed6db7: 8b4068                   mov eax, dword ptr [eax + 0x68]
00ed6dba: badc70ed00               mov edx, 0xed70dc
00ed6dbf: e8fc3889ff               call 0x76a6c0 ; CIS_TManagedFlashObject.TFlashElement.SetName
00ed6dc4: 6a00                     push 0
00ed6dc6: b101                     mov cl, 1
00ed6dc8: b201                     mov dl, 1
00ed6dca: a144e8f300               mov eax, dword ptr [0xf3e844]
00ed6dcf: e8dc3d91ff               call 0x7eabb0 ; CIS_TCustomFlashObject.TCustomFlashObject.Create
00ed6dd4: 8b55fc                   mov edx, dword ptr [ebp - 4]
00ed6dd7: 89426c                   mov dword ptr [edx + 0x6c], eax
00ed6dda: b201                     mov dl, 1
00ed6ddc: a1e43c7e00               mov eax, dword ptr [0x7e3ce4]
00ed6de1: e8aad190ff               call 0x7e3f90 ; CIS_TFlashStudio.TFlashStudio.Create
00ed6de6: 8b55fc                   mov edx, dword ptr [ebp - 4]
00ed6de9: 894274                   mov dword ptr [edx + 0x74], eax
00ed6dec: 8d55d8                   lea edx, [ebp - 0x28]
00ed6def: 33c0                     xor eax, eax
00ed6df1: e846df72ff               call 0x604d3c ; System.ParamStr
00ed6df6: 8b45d8                   mov eax, dword ptr [ebp - 0x28]
00ed6df9: 8d55dc                   lea edx, [ebp - 0x24]
00ed6dfc: e87f3a74ff               call 0x61a880 ; SysUtils.ExtractFilePath
00ed6e01: 8d45dc                   lea eax, [ebp - 0x24]
00ed6e04: ba0071ed00               mov edx, 0xed7100
00ed6e09: e83a1f73ff               call 0x608d48 ; System.@UStrCat
00ed6e0e: 8b45dc                   mov eax, dword ptr [ebp - 0x24]
00ed6e11: e8ca3374ff               call 0x61a1e0 ; SysUtils.FileExists
00ed6e16: 84c0                     test al, al
00ed6e18: 7430                     je 0xed6e4a
00ed6e1a: 8d55d0                   lea edx, [ebp - 0x30]
00ed6e1d: 33c0                     xor eax, eax
00ed6e1f: e818df72ff               call 0x604d3c ; System.ParamStr
00ed6e24: 8b45d0                   mov eax, dword ptr [ebp - 0x30]
00ed6e27: 8d55d4                   lea edx, [ebp - 0x2c]
00ed6e2a: e8513a74ff               call 0x61a880 ; SysUtils.ExtractFilePath
00ed6e2f: 8d45d4                   lea eax, [ebp - 0x2c]
00ed6e32: ba0071ed00               mov edx, 0xed7100
00ed6e37: e80c1f73ff               call 0x608d48 ; System.@UStrCat
00ed6e3c: 8b55d4                   mov edx, dword ptr [ebp - 0x2c]
00ed6e3f: 8b45fc                   mov eax, dword ptr [ebp - 4]
00ed6e42: 8b4068                   mov eax, dword ptr [eax + 0x68]
00ed6e45: e8ae5391ff               call 0x7ec1f8 ; CIS_TCustomFlashObject.TFoundationObject.StreamInFromXML
00ed6e4a: 8d55c8                   lea edx, [ebp - 0x38]
00ed6e4d: 33c0                     xor eax, eax
00ed6e4f: e8e8de72ff               call 0x604d3c ; System.ParamStr
00ed6e54: 8b45c8                   mov eax, dword ptr [ebp - 0x38]
00ed6e57: 8d55cc                   lea edx, [ebp - 0x34]
00ed6e5a: e8213a74ff               call 0x61a880 ; SysUtils.ExtractFilePath
00ed6e5f: 8d45cc                   lea eax, [ebp - 0x34]
00ed6e62: ba2c71ed00               mov edx, 0xed712c
00ed6e67: e8dc1e73ff               call 0x608d48 ; System.@UStrCat
00ed6e6c: 8b45cc                   mov eax, dword ptr [ebp - 0x34]
00ed6e6f: e86c3374ff               call 0x61a1e0 ; SysUtils.FileExists
00ed6e74: 84c0                     test al, al
00ed6e76: 7430                     je 0xed6ea8
00ed6e78: 8d55c0                   lea edx, [ebp - 0x40]
00ed6e7b: 33c0                     xor eax, eax
00ed6e7d: e8bade72ff               call 0x604d3c ; System.ParamStr
00ed6e82: 8b45c0                   mov eax, dword ptr [ebp - 0x40]
00ed6e85: 8d55c4                   lea edx, [ebp - 0x3c]
00ed6e88: e8f33974ff               call 0x61a880 ; SysUtils.ExtractFilePath
00ed6e8d: 8d45c4                   lea eax, [ebp - 0x3c]
00ed6e90: ba2c71ed00               mov edx, 0xed712c
00ed6e95: e8ae1e73ff               call 0x608d48 ; System.@UStrCat
00ed6e9a: 8b55c4                   mov edx, dword ptr [ebp - 0x3c]
00ed6e9d: 8b45fc                   mov eax, dword ptr [ebp - 4]
00ed6ea0: 8b406c                   mov eax, dword ptr [eax + 0x6c]
00ed6ea3: e8505391ff               call 0x7ec1f8 ; CIS_TCustomFlashObject.TFoundationObject.StreamInFromXML
00ed6ea8: b201                     mov dl, 1
00ed6eaa: a1ac67ed00               mov eax, dword ptr [0xed67ac]
00ed6eaf: e834fcffff               call 0xed6ae8 ; CIS_TamgKipper.TCBusInstallationConnectionManager.Create
00ed6eb4: 8b55fc                   mov edx, dword ptr [ebp - 4]
00ed6eb7: 894270                   mov dword ptr [edx + 0x70], eax
00ed6eba: a1f8363c01               mov eax, dword ptr [0x13c36f8]
00ed6ebf: 8b00                     mov eax, dword ptr [eax]
00ed6ec1: e81eac97ff               call 0x851ae4 ; CIS_Preferences.TPreferenceManager.LoadPreferences
00ed6ec6: 8d45f4                   lea eax, [ebp - 0xc]
00ed6ec9: ba5471ed00               mov edx, 0xed7154
00ed6ece: e8a51a73ff               call 0x608978 ; System.@UStrLAsg
00ed6ed3: 8d45f0                   lea eax, [ebp - 0x10]
00ed6ed6: ba8071ed00               mov edx, 0xed7180
00ed6edb: e8981a73ff               call 0x608978 ; System.@UStrLAsg
00ed6ee0: a150203c01               mov eax, dword ptr [0x13c2050]
00ed6ee5: 8b00                     mov eax, dword ptr [eax]
00ed6ee7: 8b4004                   mov eax, dword ptr [eax + 4]
00ed6eea: 83c014                   add eax, 0x14
00ed6eed: 33d2                     xor edx, edx
00ed6eef: e8301a73ff               call 0x608924 ; System.@UStrAsg
00ed6ef4: 8b45f4                   mov eax, dword ptr [ebp - 0xc]
00ed6ef7: 8945e4                   mov dword ptr [ebp - 0x1c], eax
00ed6efa: 837de400                 cmp dword ptr [ebp - 0x1c], 0
00ed6efe: 740b                     je 0xed6f0b
00ed6f00: 8b45e4                   mov eax, dword ptr [ebp - 0x1c]
00ed6f03: 83e804                   sub eax, 4
00ed6f06: 8b00                     mov eax, dword ptr [eax]
00ed6f08: 8945e4                   mov dword ptr [ebp - 0x1c], eax
00ed6f0b: 8b45e4                   mov eax, dword ptr [ebp - 0x1c]
00ed6f0e: 85c0                     test eax, eax
00ed6f10: 7e51                     jle 0xed6f63
00ed6f12: 8945e8                   mov dword ptr [ebp - 0x18], eax
00ed6f15: c745ec01000000           mov dword ptr [ebp - 0x14], 1
00ed6f1c: 8d45bc                   lea eax, [ebp - 0x44]
00ed6f1f: 8b55f0                   mov edx, dword ptr [ebp - 0x10]
00ed6f22: 8b4dec                   mov ecx, dword ptr [ebp - 0x14]
00ed6f25: 668b544afe               mov dx, word ptr [edx + ecx*2 - 2]
00ed6f2a: 8b4df4                   mov ecx, dword ptr [ebp - 0xc]
00ed6f2d: 8b5dec                   mov ebx, dword ptr [ebp - 0x14]
00ed6f30: 662b5459fe               sub dx, word ptr [ecx + ebx*2 - 2]
00ed6f35: 8b4df4                   mov ecx, dword ptr [ebp - 0xc]
00ed6f38: 66035112                 add dx, word ptr [ecx + 0x12]
00ed6f3c: e85f1b73ff               call 0x608aa0 ; System.@UStrFromWChar
00ed6f41: 8b55bc                   mov edx, dword ptr [ebp - 0x44]
00ed6f44: a150203c01               mov eax, dword ptr [0x13c2050]
00ed6f49: 8b00                     mov eax, dword ptr [eax]
00ed6f4b: 8b4004                   mov eax, dword ptr [eax + 4]
00ed6f4e: 83c014                   add eax, 0x14
00ed6f51: e8f21d73ff               call 0x608d48 ; System.@UStrCat
00ed6f56: a150203c01               mov eax, dword ptr [0x13c2050]
00ed6f5b: ff45ec                   inc dword ptr [ebp - 0x14]
00ed6f5e: ff4de8                   dec dword ptr [ebp - 0x18]
00ed6f61: 75b9                     jne 0xed6f1c
00ed6f63: 8d55b8                   lea edx, [ebp - 0x48]
00ed6f66: a180263c01               mov eax, dword ptr [0x13c2680]
00ed6f6b: 8b00                     mov eax, dword ptr [eax]
00ed6f6d: 8b4018                   mov eax, dword ptr [eax + 0x18]
00ed6f70: e8df3b74ff               call 0x61ab54 ; SysUtils.ExtractFileName
00ed6f75: 8b45b8                   mov eax, dword ptr [ebp - 0x48]
00ed6f78: 50                       push eax
00ed6f79: 8d55b0                   lea edx, [ebp - 0x50]
00ed6f7c: 33c0                     xor eax, eax
00ed6f7e: e8b9dd72ff               call 0x604d3c ; System.ParamStr
00ed6f83: 8b45b0                   mov eax, dword ptr [ebp - 0x50]
00ed6f86: 8d55b4                   lea edx, [ebp - 0x4c]
00ed6f89: e8f23874ff               call 0x61a880 ; SysUtils.ExtractFilePath
00ed6f8e: 8b55b4                   mov edx, dword ptr [ebp - 0x4c]
00ed6f91: a150203c01               mov eax, dword ptr [0x13c2050]
00ed6f96: 8b00                     mov eax, dword ptr [eax]
00ed6f98: 8b4004                   mov eax, dword ptr [eax + 4]
00ed6f9b: 83c01c                   add eax, 0x1c
00ed6f9e: 59                       pop ecx
00ed6f9f: e8641e73ff               call 0x608e08 ; System.@UStrCat3
00ed6fa4: a1d4383c01               mov eax, dword ptr [0x13c38d4]
00ed6fa9: 8b00                     mov eax, dword ptr [eax]
00ed6fab: 695020e8030000           imul edx, dword ptr [eax + 0x20], 0x3e8
00ed6fb2: a150203c01               mov eax, dword ptr [0x13c2050]
00ed6fb7: 8b00                     mov eax, dword ptr [eax]
00ed6fb9: 8b4004                   mov eax, dword ptr [eax + 4]
00ed6fbc: e8f7130800               call 0xf583b8 ; CIS_Log.TZippedLog.SetZipLimit
00ed6fc1: a10c3a3c01               mov eax, dword ptr [0x13c3a0c]
00ed6fc6: 8b00                     mov eax, dword ptr [eax]
00ed6fc8: 8a401a                   mov al, byte ptr [eax + 0x1a]
00ed6fcb: 8b1550203c01             mov edx, dword ptr [0x13c2050]
00ed6fd1: 8b12                     mov edx, dword ptr [edx]
00ed6fd3: 8b5204                   mov edx, dword ptr [edx + 4]
00ed6fd6: 884228                   mov byte ptr [edx + 0x28], al
00ed6fd9: a164333c01               mov eax, dword ptr [0x13c3364]
00ed6fde: 8b00                     mov eax, dword ptr [eax]
00ed6fe0: c7407488130000           mov dword ptr [eax + 0x74], 0x1388
00ed6fe7: 33c0                     xor eax, eax
00ed6fe9: 5a                       pop edx
00ed6fea: 59                       pop ecx
00ed6feb: 59                       pop ecx
00ed6fec: 648910                   mov dword ptr fs:[eax], edx
00ed6fef: 681670ed00               push 0xed7016
00ed6ff4: 8d45b0                   lea eax, [ebp - 0x50]
00ed6ff7: ba0c000000               mov edx, 0xc
00ed6ffc: e81b1973ff               call 0x60891c ; System.@UStrArrayClr
00ed7001: 8d45f0                   lea eax, [ebp - 0x10]
00ed7004: ba02000000               mov edx, 2
00ed7009: e80e1973ff               call 0x60891c ; System.@UStrArrayClr
00ed700e: c3                       ret
00ed700f: e910fc72ff               jmp 0x606c24 ; System.@HandleFinally
00ed7014: ebde                     jmp 0xed6ff4
00ed7016: 8b45fc                   mov eax, dword ptr [ebp - 4]
00ed7019: 807dfb00                 cmp byte ptr [ebp - 5], 0
00ed701d: 740f                     je 0xed702e
00ed701f: e894f772ff               call 0x6067b8 ; System.@AfterConstruction
00ed7024: 648f0500000000           pop dword ptr fs:[0]
00ed702b: 83c40c                   add esp, 0xc
00ed702e: 8b45fc                   mov eax, dword ptr [ebp - 4]
00ed7031: 5b                       pop ebx
00ed7032: 8be5                     mov esp, ebp
00ed7034: 5d                       pop ebp
00ed7035: c3                       ret
00ed7036: 0000                     add byte ptr [eax], al
00ed7038: b004                     mov al, 4
00ed703a: 0200                     add al, byte ptr [eax]
