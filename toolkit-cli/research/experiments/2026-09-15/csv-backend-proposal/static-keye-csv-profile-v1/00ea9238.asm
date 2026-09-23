00ea9238: 55                       push ebp
00ea9239: 8bec                     mov ebp, esp
00ea923b: 51                       push ecx
00ea923c: 8945fc                   mov dword ptr [ebp - 4], eax
00ea923f: 8b45fc                   mov eax, dword ptr [ebp - 4]
00ea9242: e8b973dfff               call 0xca0600 ; CIS_TCBusNeoProInputUnit.TCBusNeoProInputUnit.InternalCreate
00ea9247: 688892ea00               push 0xea9288
00ea924c: 6a00                     push 0
00ea924e: 6a00                     push 0
00ea9250: 6a00                     push 0
00ea9252: 8b45fc                   mov eax, dword ptr [ebp - 4]
00ea9255: 8b4830                   mov ecx, dword ptr [eax + 0x30]
00ea9258: b201                     mov dl, 1
00ea925a: a174058500               mov eax, dword ptr [0x850574]
00ea925f: e8a03294ff               call 0x7ec504 ; CIS_TCustomFlashObject.TFlashAttribute.Create
00ea9264: 8b55fc                   mov edx, dword ptr [ebp - 4]
00ea9267: 8982b8020000             mov dword ptr [edx + 0x2b8], eax
00ea926d: 8b45fc                   mov eax, dword ptr [ebp - 4]
00ea9270: 33d2                     xor edx, edx
00ea9272: 8990bc020000             mov dword ptr [eax + 0x2bc], edx
00ea9278: 59                       pop ecx
00ea9279: 5d                       pop ebp
00ea927a: c3                       ret 
00ea927b: 00b0040200ff             add byte ptr [eax - 0xfffdfc], dh
