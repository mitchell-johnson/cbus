00ea8bc0: 55                       push ebp
00ea8bc1: 8bec                     mov ebp, esp
00ea8bc3: 51                       push ecx
00ea8bc4: 8945fc                   mov dword ptr [ebp - 4], eax
00ea8bc7: a1ec8bea00               mov eax, dword ptr [0xea8bec]
00ea8bcc: 8b55fc                   mov edx, dword ptr [ebp - 4]
00ea8bcf: 3b82b0030000             cmp eax, dword ptr [edx + 0x3b0]
00ea8bd5: 0f95c2                   setne dl
00ea8bd8: 8b45fc                   mov eax, dword ptr [ebp - 4]
00ea8bdb: 8b8090030000             mov eax, dword ptr [eax + 0x390]
00ea8be1: 8b08                     mov ecx, dword ptr [eax]
00ea8be3: ff5174                   call dword ptr [ecx + 0x74]
00ea8be6: 59                       pop ecx
00ea8be7: 5d                       pop ebp
00ea8be8: c3                       ret
00ea8be9: 0000                     add byte ptr [eax], al
00ea8beb: 0000                     add byte ptr [eax], al
00ea8bed: 0000                     add byte ptr [eax], al
