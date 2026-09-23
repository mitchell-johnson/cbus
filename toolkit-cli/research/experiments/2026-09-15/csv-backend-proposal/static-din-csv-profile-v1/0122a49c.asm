0122a49c: f4                       hlt 
0122a49d: a4                       movsb byte ptr es:[edi], byte ptr [esi]
0122a49e: 2201                     and al, byte ptr [ecx]
0122a4a0: 0000                     add byte ptr [eax], al
0122a4a2: 0000                     add byte ptr [eax], al
0122a4a4: 0000                     add byte ptr [eax], al
0122a4a6: 0000                     add byte ptr [eax], al
0122a4a8: 0000                     add byte ptr [eax], al
0122a4aa: 0000                     add byte ptr [eax], al
0122a4ac: b8a6220100               mov eax, 0x122a6
0122a4b1: 0000                     add byte ptr [eax], al
0122a4b3: 0000                     add byte ptr [eax], al
0122a4b5: 0000                     add byte ptr [eax], al
0122a4b7: 0000                     add byte ptr [eax], al
0122a4b9: 0000                     add byte ptr [eax], al
0122a4bb: 00a8a622013c             add byte ptr [eax + 0x3c0122a6], ch
0122a4c1: 0200                     add al, byte ptr [eax]
0122a4c3: 007096                   add byte ptr [eax - 0x6a], dh
0122a4c6: d200                     rol byte ptr [eax], cl
0122a4c8: bc626000c4               mov esp, 0xc4006062
0122a4cd: 626000                   bound esp, qword ptr [eax]
0122a4d0: 0c65                     or al, 0x65
0122a4d2: 60                       pushal 
0122a4d3: 0004656000a0a4           add byte ptr [0xa4a00060], al
0122a4da: 7600                     jbe 0x122a4dc
0122a4dc: 286560                   sub byte ptr [ebp + 0x60], ah
0122a4df: 002c6560002065           add byte ptr [0x65200060], ch
0122a4e6: 60                       pushal 
0122a4e7: 0098616000b4             add byte ptr [eax - 0x4bff9f9f], bl
0122a4ed: 61                       popal 
0122a4ee: 60                       pushal 
0122a4ef: 0000                     add byte ptr [eax], al
0122a4f1: b2d2                     mov dl, 0xd2
0122a4f3: 006882                   add byte ptr [eax - 0x7e], ch
0122a4f6: 7600                     jbe 0x122a4f8
0122a4f8: 10aa7e00a482             adc byte ptr [edx - 0x7d5bff82], ch
0122a4fe: 7600                     jbe 0x122a500
0122a500: 54                       push esp
0122a501: b4d2                     mov ah, 0xd2
0122a503: 00e4                     add ah, ah
0122a505: ec                       in al, dx
0122a506: d100                     rol dword ptr [eax], 1
0122a508: 78ab                     js 0x122a4b5
0122a50a: 7e00                     jle 0x122a50c
0122a50c: e4ad                     in al, 0xad
0122a50e: 7e00                     jle 0x122a510
0122a510: 04ae                     add al, 0xae
0122a512: 7e00                     jle 0x122a514
0122a514: b0ab                     mov al, 0xab
0122a516: 7e00                     jle 0x122a518
0122a518: 44                       inc esp
0122a519: a4                       movsb byte ptr es:[edi], byte ptr [esi]
0122a51a: 7600                     jbe 0x122a51c
0122a51c: 08a77e007ca4             or byte ptr [edi - 0x5b83ff82], ah
0122a522: 7e00                     jle 0x122a524
0122a524: 1ca6                     sbb al, 0xa6
0122a526: 7e00                     jle 0x122a528
0122a528: 38ac7e0054a17e           cmp byte ptr [esi + edi*2 + 0x7ea15400], ch
0122a52f: 0038                     add byte ptr [eax], bh
0122a531: a6                       cmpsb byte ptr [esi], byte ptr es:[edi]
0122a532: 7600                     jbe 0x122a534
0122a534: e8c27e0048               call 0x492323fb
0122a539: ab                       stosd dword ptr es:[edi], eax
0122a53a: 7e00                     jle 0x122a53c
0122a53c: 48                       dec eax
0122a53d: a6                       cmpsb byte ptr [esi], byte ptr es:[edi]
0122a53e: 7600                     jbe 0x122a540
0122a540: 70a6                     jo 0x122a4e8
0122a542: 7600                     jbe 0x122a544
0122a544: 44                       inc esp
0122a545: aa                       stosb byte ptr es:[edi], al
0122a546: 7e00                     jle 0x122a548
0122a548: 9c                       pushfd 
0122a549: a5                       movsd dword ptr es:[edi], dword ptr [esi]
0122a54a: 7600                     jbe 0x122a54c
0122a54c: 38e9                     cmp cl, ch
0122a54e: d100                     rol dword ptr [eax], 1
0122a550: 50                       push eax
0122a551: a07e00e440               mov al, byte ptr [0x40e4007e]
0122a556: f30098a67e00ac           add byte ptr [eax - 0x53ff815a], bl
0122a55d: a6                       cmpsb byte ptr [esi], byte ptr es:[edi]
0122a55e: 7e00                     jle 0x122a560
0122a560: f8                       clc 
0122a561: a97e0014bc               test eax, 0xbc14007e
0122a566: 7e00                     jle 0x122a568
0122a568: 7cfa                     jl 0x122a564
0122a56a: 7e00                     jle 0x122a56c
0122a56c: 340a                     xor al, 0xa
0122a56e: 7f00                     jg 0x122a570
0122a570: 5c                       pop esp
0122a571: 40                       inc eax
0122a572: 7f00                     jg 0x122a574
0122a574: 9c                       pushfd 
0122a575: 40                       inc eax
0122a576: 7f00                     jg 0x122a578
0122a578: ac                       lodsb al, byte ptr [esi]
0122a579: 3f                       aas 
0122a57a: 7f00                     jg 0x122a57c
0122a57c: 60                       pushal 
0122a57d: 41                       inc ecx
0122a57e: 7f00                     jg 0x122a580
0122a580: 7c40                     jl 0x122a5c2
0122a582: 7f00                     jg 0x122a584
0122a584: 2ce8                     sub al, 0xe8
0122a586: f200c4                   add ah, al
0122a589: 7df4                     jge 0x122a57f
0122a58b: 0028                     add byte ptr [eax], ch
0122a58d: 82f400                   xor ah, 0
0122a590: f8                       clc 
0122a591: e8d100dc7b               call 0x7cfea667
0122a596: f4                       hlt 
0122a597: 00c8                     add al, cl
0122a599: 7bf4                     jnp 0x122a58f
0122a59b: 00f4                     add ah, dh
0122a59d: ec                       in al, dx
0122a59e: f20014edf200c0eb         add byte ptr [ebp*8 - 0x143fff0e], dl
0122a5a6: f200f0                   add al, dh
0122a5a9: ebf2                     jmp 0x122a59d
0122a5ab: 00f4                     add ah, dh
0122a5ad: b8d200d440               mov eax, 0x40d400d2
0122a5b2: f300b047f300c4           add byte ptr [eax - 0x3bff0cb9], dh
0122a5b9: 47                       inc edi
0122a5ba: f3003c5c                 add byte ptr [esp + ebx*2], bh
0122a5be: f300704a                 add byte ptr [eax + 0x4a], dh
0122a5c2: f30098ecf200d8           add byte ptr [eax - 0x27ff0d14], bl
0122a5c9: 49                       dec ecx
0122a5ca: f300ec                   add ah, ch
0122a5cd: 49                       dec ecx
0122a5ce: f300244a                 add byte ptr [edx + ecx*2], ah
0122a5d2: f300e4                   add ah, ah
0122a5d5: e9d10010a7               jmp 0xa832a6ab
0122a5da: 2201                     and al, byte ptr [ecx]
0122a5dc: 883b                     mov byte ptr [ebx], bh
0122a5de: f30060ef                 add byte ptr [eax - 0x11], ah
0122a5e2: d100                     rol dword ptr [eax], 1
0122a5e4: e844f300fc               call 0xfd23992d
0122a5e9: 44                       inc esp
0122a5ea: f300c0                   add al, al
0122a5ed: b8d2006445               mov eax, 0x456400d2
0122a5f2: f30018                   add byte ptr [eax], bl
0122a5f5: e6d1                     out 0xd1, al
0122a5f7: 002445f3003845           add byte ptr [eax*2 + 0x453800f3], ah
0122a5fe: f30094bfd200e4e7         add byte ptr [edi + edi*4 - 0x181bff2e], dl
0122a606: f200ec                   add ah, ch
0122a609: f5                       cmc 
0122a60a: f200c0                   add al, al
0122a60d: ed                       in eax, dx
0122a60e: f20018                   add byte ptr [eax], bl
0122a611: f6f2                     div dl
0122a613: 00d8                     add al, bl
0122a615: f6f2                     div dl
0122a617: 0078f6                   add byte ptr [eax - 0xa], bh
0122a61a: f2005ceef2               add byte ptr [esi + ebp*8 - 0xe], bl
0122a61f: 0010                     add byte ptr [eax], dl
0122a621: b0d2                     mov al, 0xd2
0122a623: 00ec                     add ah, ch
0122a625: af                       scasd eax, dword ptr es:[edi]
0122a626: d200                     rol byte ptr [eax], cl
0122a628: c43e                     les edi, ptr [esi]
0122a62a: f30078a7                 add byte ptr [eax - 0x59], bh
0122a62e: 2201                     and al, byte ptr [ecx]
0122a630: 1c4b                     sbb al, 0x4b
0122a632: f30004ef                 add byte ptr [edi + ebp*8], al
0122a636: f200ec                   add ah, ch
0122a639: 01f3                     add ebx, esi
0122a63b: 00505c                   add byte ptr [eax + 0x5c], dl
0122a63e: f300b45cf300d046         add byte ptr [esp + ebx*2 + 0x46d000f3], dh
0122a646: f300e8                   add al, ch
0122a649: 46                       inc esi
0122a64a: f30030                   add byte ptr [eax], dh
0122a64d: fa                       cli 
0122a64e: f200ec                   add ah, ch
0122a651: fa                       cli 
0122a652: f20038                   add byte ptr [eax], bh
0122a655: ead10054e9d100           ljmp 0xd1:0xe95400d1
0122a65c: 78ed                     js 0x122a64b
0122a65e: d100                     rol dword ptr [eax], 1
0122a660: 78e9                     js 0x122a64b
0122a662: d100                     rol dword ptr [eax], 1
0122a664: 44                       inc esp
0122a665: ee                       out dx, al
0122a666: d100                     rol dword ptr [eax], 1
