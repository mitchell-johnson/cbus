00cfa258: b0a2                     mov al, 0xa2
00cfa25a: cf                       iretd 
00cfa25b: 0000                     add byte ptr [eax], al
00cfa25d: 0000                     add byte ptr [eax], al
00cfa25f: 0000                     add byte ptr [eax], al
00cfa261: 0000                     add byte ptr [eax], al
00cfa263: 0000                     add byte ptr [eax], al
00cfa265: 0000                     add byte ptr [eax], al
00cfa267: 0064a5cf                 add byte ptr [ebp - 0x31], ah
00cfa26b: 0000                     add byte ptr [eax], al
00cfa26d: 0000                     add byte ptr [eax], al
00cfa26f: 0000                     add byte ptr [eax], al
00cfa271: 0000                     add byte ptr [eax], al
00cfa273: 0000                     add byte ptr [eax], al
00cfa275: 0000                     add byte ptr [eax], al
00cfa277: 0048a5                   add byte ptr [eax - 0x5b], cl
00cfa27a: cf                       iretd 
00cfa27b: 005c0300                 add byte ptr [ebx + eax], bl
00cfa27f: 000c9f                   add byte ptr [edi + ebx*4], cl
00cfa282: cf                       iretd 
00cfa283: 00bc626000c462           add byte ptr [edx + 0x62c40060], bh
00cfa28a: 60                       pushal 
00cfa28b: 000c6560000465           add byte ptr [0x65040060], cl
00cfa292: 60                       pushal 
00cfa293: 0064d9cf                 add byte ptr [ecx + ebx*8 - 0x31], ah
00cfa297: 00c4                     add ah, al
