00ea7d70: c87dea00                 enter -0x1583, 0
00ea7d74: 0000                     add byte ptr [eax], al
00ea7d76: 0000                     add byte ptr [eax], al
00ea7d78: 0000                     add byte ptr [eax], al
00ea7d7a: 0000                     add byte ptr [eax], al
00ea7d7c: 0000                     add byte ptr [eax], al
00ea7d7e: 0000                     add byte ptr [eax], al
00ea7d80: 5c                       pop esp
00ea7d81: 80ea00                   sub dl, 0
00ea7d84: e07e                     loopne 0xea7e04
00ea7d86: ea00a97fea0000           ljmp 0:0xea7fa900
00ea7d8d: 0000                     add byte ptr [eax], al
00ea7d8f: 0028                     add byte ptr [eax], ch
00ea7d91: 80ea00                   sub dl, 0
00ea7d94: bc03000028               mov esp, 0x28000003
00ea7d99: 51                       push ecx
00ea7d9a: 7100                     jno 0xea7d9c
00ea7d9c: bc626000c4               mov esp, 0xc4006062
00ea7da1: 626000                   bound esp, qword ptr [eax]
00ea7da4: 0c65                     or al, 0x65
00ea7da6: 60                       pushal
00ea7da7: 00b0006500e4             add byte ptr [eax - 0x1bff9b00], dh
00ea7dad: b771                     mov bh, 0x71
00ea7daf: 00e0                     add al, ah
00ea7db1: b971002c65               mov ecx, 0x652c0071
00ea7db6: 60                       pushal
00ea7db7: 00d4                     add ah, dl
00ea7db9: ef                       out dx, eax
00ea7dba: 7100                     jno 0xea7dbc
00ea7dbc: 98                       cwde
00ea7dbd: 61                       popal
00ea7dbe: 60                       pushal
00ea7dbf: 00b461600054ba           add byte ptr [ecx - 0x45abffa0], dh
00ea7dc6: 7100                     jno 0xea7dc8
00ea7dc8: 18fd                     sbb ch, bh
00ea7dca: 6f                       outsd dx, dword ptr [esi]
00ea7dcb: 00b4c07100a84d           add byte ptr [eax + eax*8 + 0x4da80071], dh
00ea7dd2: 640064bc71               add byte ptr fs:[esp + edi*4 + 0x71], ah
00ea7dd7: 00e8                     add al, ch
00ea7dd9: bc710024be               mov esp, 0xbe240071
00ea7dde: 7100                     jno 0xea7de0
00ea7de0: 88606f                   mov byte ptr [eax + 0x6f], ah
00ea7de3: 00c8                     add al, cl
00ea7de5: 006500                   add byte ptr [ebp], ah
00ea7de8: e8c7710070               call 0x70eaefb4
00ea7ded: fa                       cli
00ea7dee: 6400601d                 add byte ptr fs:[eax + 0x1d], ah
00ea7df2: 7200                     jb 0xea7df4
00ea7df4: 3cb6                     cmp al, 0xb6
00ea7df6: 7100                     jno 0xea7df8
00ea7df8: d0ff                     sar bh, 1
00ea7dfa: 64003cf7                 add byte ptr fs:[edi + esi*8], bh
00ea7dfe: 6f                       outsd dx, dword ptr [esi]
00ea7dff: 0048fd                   add byte ptr [eax - 3], cl
00ea7e02: 6f                       outsd dx, dword ptr [esi]
00ea7e03: 0094fc6f00488a           add byte ptr [esp + edi*8 - 0x75b7ff91], dl
00ea7e0a: 6f                       outsd dx, dword ptr [esi]
00ea7e0b: 00d0                     add al, dl
00ea7e0d: ac                       lodsb al, byte ptr [esi]
00ea7e0e: 7100                     jno 0xea7e10
00ea7e10: 44                       inc esp
00ea7e11: ad                       lodsd eax, dword ptr [esi]
00ea7e12: 7100                     jno 0xea7e14
00ea7e14: 0452                     add al, 0x52
00ea7e16: 6f                       outsd dx, dword ptr [esi]
00ea7e17: 0044f16f                 add byte ptr [ecx + esi*8 + 0x6f], al
00ea7e1b: 0024c4                   add byte ptr [esp + eax*8], ah
00ea7e1e: 7100                     jno 0xea7e20
00ea7e20: 44                       inc esp
00ea7e21: ed                       in eax, dx
00ea7e22: 6f                       outsd dx, dword ptr [esi]
00ea7e23: 004851                   add byte ptr [eax + 0x51], cl
00ea7e26: 6f                       outsd dx, dword ptr [esi]
00ea7e27: 0030                     add byte ptr [eax], dh
00ea7e29: c57100                   lds esi, ptr [ecx]
00ea7e2c: 388f6f000c1a             cmp byte ptr [edi + 0x1a0c006f], cl
00ea7e32: 7200                     jb 0xea7e34
00ea7e34: 7060                     jo 0xea7e96
00ea7e36: 6f                       outsd dx, dword ptr [esi]
00ea7e37: 00e0                     add al, ah
00ea7e39: 53                       push ebx
00ea7e3a: 6f                       outsd dx, dword ptr [esi]
00ea7e3b: 00f8                     add al, bh
00ea7e3d: 61                       popal
00ea7e3e: 6f                       outsd dx, dword ptr [esi]
00ea7e3f: 002cc7                   add byte ptr [edi + eax*8], ch
00ea7e42: 7100                     jno 0xea7e44
00ea7e44: e8c571003c               call 0x3ceaf00e
00ea7e49: 636f00                   arpl word ptr [edi], bp
00ea7e4c: 28c8                     sub al, cl
00ea7e4e: 7100                     jno 0xea7e50
00ea7e50: 44                       inc esp
00ea7e51: 51                       push ecx
00ea7e52: 6f                       outsd dx, dword ptr [esi]
00ea7e53: 00bc8f6f00d0ed           add byte ptr [edi + ecx*4 - 0x122fff91], bh
00ea7e5a: 6f                       outsd dx, dword ptr [esi]
00ea7e5b: 00e4                     add ah, ah
00ea7e5d: ee                       out dx, al
00ea7e5e: 6f                       outsd dx, dword ptr [esi]
00ea7e5f: 0004e8                   add byte ptr [eax + ebp*8], al
00ea7e62: 6f                       outsd dx, dword ptr [esi]
00ea7e63: 00c8                     add al, cl
00ea7e65: ee                       out dx, al
00ea7e66: 6f                       outsd dx, dword ptr [esi]
00ea7e67: 00acb2710040d0           add byte ptr [edx + esi*4 - 0x2fbfff8f], ch
00ea7e6e: 7100                     jno 0xea7e70
00ea7e70: 04b3                     add al, 0xb3
00ea7e72: 6f                       outsd dx, dword ptr [esi]
00ea7e73: 00e8                     add al, ch
00ea7e75: e471                     in al, 0x71
00ea7e77: 00e0                     add al, ah
00ea7e79: ec                       in al, dx
00ea7e7a: 7100                     jno 0xea7e7c
00ea7e7c: e4ea                     in al, 0xea
00ea7e7e: 7100                     jno 0xea7e80
00ea7e80: 9c                       pushfd
00ea7e81: b36f                     mov bl, 0x6f
00ea7e83: 00c0                     add al, al
00ea7e85: b36f                     mov bl, 0x6f
00ea7e87: 005cee71                 add byte ptr [esi + ebp*8 + 0x71], bl
00ea7e8b: 0090ef7100d8             add byte ptr [eax - 0x27ff8e11], dl
00ea7e91: b16f                     mov cl, 0x6f
00ea7e93: 00800e700010             add byte ptr [eax + 0x1000700e], al
