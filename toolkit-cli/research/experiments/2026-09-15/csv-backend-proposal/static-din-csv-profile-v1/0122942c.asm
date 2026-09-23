0122942c: 84942201000000           test byte ptr [edx + 1], dl
01229433: 0000                     add byte ptr [eax], al
01229435: 0000                     add byte ptr [eax], al
01229437: 0000                     add byte ptr [eax], al
01229439: 0000                     add byte ptr [eax], al
0122943b: 00449622                 add byte ptr [esi + edx*4 + 0x22], al
0122943f: 0100                     add dword ptr [eax], eax
01229441: 0000                     add byte ptr [eax], al
01229443: 0000                     add byte ptr [eax], al
01229445: 0000                     add byte ptr [eax], al
01229447: 0000                     add byte ptr [eax], al
01229449: 0000                     add byte ptr [eax], al
0122944b: 0038                     add byte ptr [eax], bh
0122944d: 96                       xchg esi, eax
0122944e: 2201                     and al, byte ptr [ecx]
01229450: 3c02                     cmp al, 2
01229452: 0000                     add byte ptr [eax], al
01229454: 7096                     jo 0x12293ec
01229456: d200                     rol byte ptr [eax], cl
01229458: bc626000c4               mov esp, 0xc4006062
0122945d: 626000                   bound esp, qword ptr [eax]
01229460: 0c65                     or al, 0x65
01229462: 60                       pushal 
01229463: 0004656000a0a4           add byte ptr [0xa4a00060], al
0122946a: 7600                     jbe 0x122946c
0122946c: 286560                   sub byte ptr [ebp + 0x60], ah
0122946f: 002c6560002065           add byte ptr [0x65200060], ch
01229476: 60                       pushal 
01229477: 0098616000b4             add byte ptr [eax - 0x4bff9f9f], bl
0122947d: 61                       popal 
0122947e: 60                       pushal 
0122947f: 0000                     add byte ptr [eax], al
01229481: b2d2                     mov dl, 0xd2
01229483: 006882                   add byte ptr [eax - 0x7e], ch
01229486: 7600                     jbe 0x1229488
01229488: 10aa7e00a482             adc byte ptr [edx - 0x7d5bff82], ch
0122948e: 7600                     jbe 0x1229490
01229490: 54                       push esp
01229491: b4d2                     mov ah, 0xd2
01229493: 00e4                     add ah, ah
01229495: ec                       in al, dx
01229496: d100                     rol dword ptr [eax], 1
01229498: 78ab                     js 0x1229445
0122949a: 7e00                     jle 0x122949c
0122949c: e4ad                     in al, 0xad
0122949e: 7e00                     jle 0x12294a0
012294a0: 04ae                     add al, 0xae
012294a2: 7e00                     jle 0x12294a4
012294a4: b0ab                     mov al, 0xab
012294a6: 7e00                     jle 0x12294a8
012294a8: 44                       inc esp
012294a9: a4                       movsb byte ptr es:[edi], byte ptr [esi]
012294aa: 7600                     jbe 0x12294ac
012294ac: 08a77e007ca4             or byte ptr [edi - 0x5b83ff82], ah
012294b2: 7e00                     jle 0x12294b4
012294b4: 1ca6                     sbb al, 0xa6
012294b6: 7e00                     jle 0x12294b8
012294b8: 38ac7e0054a17e           cmp byte ptr [esi + edi*2 + 0x7ea15400], ch
012294bf: 0038                     add byte ptr [eax], bh
012294c1: a6                       cmpsb byte ptr [esi], byte ptr es:[edi]
012294c2: 7600                     jbe 0x12294c4
012294c4: e8c27e0048               call 0x4923138b
012294c9: ab                       stosd dword ptr es:[edi], eax
012294ca: 7e00                     jle 0x12294cc
012294cc: 48                       dec eax
012294cd: a6                       cmpsb byte ptr [esi], byte ptr es:[edi]
012294ce: 7600                     jbe 0x12294d0
012294d0: 70a6                     jo 0x1229478
012294d2: 7600                     jbe 0x12294d4
012294d4: 44                       inc esp
012294d5: aa                       stosb byte ptr es:[edi], al
012294d6: 7e00                     jle 0x12294d8
012294d8: 9c                       pushfd 
012294d9: a5                       movsd dword ptr es:[edi], dword ptr [esi]
012294da: 7600                     jbe 0x12294dc
012294dc: 38e9                     cmp cl, ch
012294de: d100                     rol dword ptr [eax], 1
012294e0: 50                       push eax
012294e1: a07e00e440               mov al, byte ptr [0x40e4007e]
012294e6: f30098a67e00ac           add byte ptr [eax - 0x53ff815a], bl
012294ed: a6                       cmpsb byte ptr [esi], byte ptr es:[edi]
012294ee: 7e00                     jle 0x12294f0
012294f0: f8                       clc 
012294f1: a97e0014bc               test eax, 0xbc14007e
012294f6: 7e00                     jle 0x12294f8
012294f8: 7cfa                     jl 0x12294f4
012294fa: 7e00                     jle 0x12294fc
012294fc: 340a                     xor al, 0xa
012294fe: 7f00                     jg 0x1229500
01229500: 5c                       pop esp
01229501: 40                       inc eax
01229502: 7f00                     jg 0x1229504
01229504: 9c                       pushfd 
01229505: 40                       inc eax
01229506: 7f00                     jg 0x1229508
01229508: ac                       lodsb al, byte ptr [esi]
01229509: 3f                       aas 
0122950a: 7f00                     jg 0x122950c
0122950c: 60                       pushal 
0122950d: 41                       inc ecx
0122950e: 7f00                     jg 0x1229510
01229510: 7c40                     jl 0x1229552
01229512: 7f00                     jg 0x1229514
01229514: 2ce8                     sub al, 0xe8
01229516: f200c4                   add ah, al
01229519: 7df4                     jge 0x122950f
0122951b: 0028                     add byte ptr [eax], ch
0122951d: 82f400                   xor ah, 0
01229520: f8                       clc 
01229521: e8d100dc7b               call 0x7cfe95f7
01229526: f4                       hlt 
01229527: 00c8                     add al, cl
01229529: 7bf4                     jnp 0x122951f
0122952b: 00f4                     add ah, dh
0122952d: ec                       in al, dx
0122952e: f20014edf200c0eb         add byte ptr [ebp*8 - 0x143fff0e], dl
01229536: f200f0                   add al, dh
01229539: ebf2                     jmp 0x122952d
0122953b: 00f4                     add ah, dh
0122953d: b8d200d440               mov eax, 0x40d400d2
01229542: f300b047f300c4           add byte ptr [eax - 0x3bff0cb9], dh
01229549: 47                       inc edi
0122954a: f3003c5c                 add byte ptr [esp + ebx*2], bh
0122954e: f300704a                 add byte ptr [eax + 0x4a], dh
01229552: f30098ecf200d8           add byte ptr [eax - 0x27ff0d14], bl
01229559: 49                       dec ecx
0122955a: f300ec                   add ah, ch
0122955d: 49                       dec ecx
0122955e: f300244a                 add byte ptr [edx + ecx*2], ah
01229562: f300e4                   add ah, ah
01229565: e9d10068b2               jmp 0xb38a963b
0122956a: d200                     rol byte ptr [eax], cl
0122956c: 883b                     mov byte ptr [ebx], bh
0122956e: f30060ef                 add byte ptr [eax - 0x11], ah
01229572: d100                     rol dword ptr [eax], 1
01229574: e844f300fc               call 0xfd2388bd
01229579: 44                       inc esp
0122957a: f300c0                   add al, al
0122957d: b8d2006445               mov eax, 0x456400d2
01229582: f30018                   add byte ptr [eax], bl
01229585: e6d1                     out 0xd1, al
01229587: 002445f3003845           add byte ptr [eax*2 + 0x453800f3], ah
0122958e: f30094bfd200e4e7         add byte ptr [edi + edi*4 - 0x181bff2e], dl
01229596: f200ec                   add ah, ch
01229599: f5                       cmc 
0122959a: f200c0                   add al, al
0122959d: ed                       in eax, dx
0122959e: f20018                   add byte ptr [eax], bl
012295a1: f6f2                     div dl
012295a3: 00d8                     add al, bl
012295a5: f6f2                     div dl
012295a7: 0078f6                   add byte ptr [eax - 0xa], bh
012295aa: f2005ceef2               add byte ptr [esi + ebp*8 - 0xe], bl
012295af: 0010                     add byte ptr [eax], dl
012295b1: b0d2                     mov al, 0xd2
012295b3: 00ec                     add ah, ch
012295b5: af                       scasd eax, dword ptr es:[edi]
012295b6: d200                     rol byte ptr [eax], cl
012295b8: c43e                     les edi, ptr [esi]
012295ba: f300e0                   add al, ah
012295bd: 98                       cwde 
012295be: 2201                     and al, byte ptr [ecx]
012295c0: 1c4b                     sbb al, 0x4b
012295c2: f30004ef                 add byte ptr [edi + ebp*8], al
012295c6: f200ec                   add ah, ch
012295c9: 01f3                     add ebx, esi
012295cb: 00505c                   add byte ptr [eax + 0x5c], dl
012295ce: f300b45cf300d046         add byte ptr [esp + ebx*2 + 0x46d000f3], dh
012295d6: f300e8                   add al, ch
012295d9: 46                       inc esi
012295da: f30030                   add byte ptr [eax], dh
012295dd: fa                       cli 
012295de: f200ec                   add ah, ch
012295e1: fa                       cli 
012295e2: f20038                   add byte ptr [eax], bh
012295e5: ead10054e9d100           ljmp 0xd1:0xe95400d1
012295ec: 78ed                     js 0x12295db
012295ee: d100                     rol dword ptr [eax], 1
012295f0: 78e9                     js 0x12295db
012295f2: d100                     rol dword ptr [eax], 1
012295f4: 44                       inc esp
012295f5: ee                       out dx, al
012295f6: d100                     rol dword ptr [eax], 1
