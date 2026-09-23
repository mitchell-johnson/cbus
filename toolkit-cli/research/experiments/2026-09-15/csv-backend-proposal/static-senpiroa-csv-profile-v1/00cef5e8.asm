00cef5e8: 40                       inc eax
00cef5e9: f6ce00                   test dh, 0
00cef5ec: 0000                     add byte ptr [eax], al
00cef5ee: 0000                     add byte ptr [eax], al
00cef5f0: 0000                     add byte ptr [eax], al
00cef5f2: 0000                     add byte ptr [eax], al
00cef5f4: 0000                     add byte ptr [eax], al
00cef5f6: 0000                     add byte ptr [eax], al
00cef5f8: ec                       in al, dx
00cef5f9: f8                       clc 
00cef5fa: ce                       into 
00cef5fb: 0000                     add byte ptr [eax], al
00cef5fd: 0000                     add byte ptr [eax], al
00cef5ff: 0000                     add byte ptr [eax], al
00cef601: 0000                     add byte ptr [eax], al
00cef603: 0000                     add byte ptr [eax], al
00cef605: 0000                     add byte ptr [eax], al
00cef607: 00d8                     add al, bl
00cef609: f8                       clc 
00cef60a: ce                       into 
00cef60b: 005c0300                 add byte ptr [ebx + eax], bl
00cef60f: 0058a2                   add byte ptr [eax - 0x5e], bl
00cef612: cf                       iretd 
00cef613: 00bc626000c462           add byte ptr [edx + 0x62c40060], bh
00cef61a: 60                       pushal 
00cef61b: 000c6560000465           add byte ptr [0x65040060], cl
00cef622: 60                       pushal 
00cef623: 0064d9cf                 add byte ptr [ecx + ebx*8 - 0x31], ah
00cef627: 00c4                     add ah, al
