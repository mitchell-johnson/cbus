"""Pin thermostat application manager order and JCL dependencies statically.

Reads only the explicitly supplied original EXE/MAP. Does not execute or emulate
original instructions, contact a server, or supply a fabricated Windows NLS
table or manager-session history. Emits sanitized hashes and source checkpoints.
"""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
import struct
import sys

sys.path.insert(0, str(Path(__file__).resolve().parent))
from topology_generator_static import EXE_SHA256, MAP_SHA256, _Image  # noqa: E402
from thermostat_post_load_static import _Walker  # noqa: E402

METHODS = {'CIS_TCommonCBus.TCBusGroupManager.GroupByTagNameExclude': {'start': '0xf28e28',
                                                             'end': '0xf28f34',
                                                             'sha256': 'e139064e84418d513365ba3316eeeb301dce1498bff6182b82505012bb68933c'},
 'CIS_TCommonCBus.TCBusGroup.HasDefaultTagName': {'start': '0xf27d10',
                                                  'end': '0xf27e14',
                                                  'sha256': '4bf4ca9399c260b80a6cd9b4d2c1b021c763ba9ae73145b71cccdf66d8608ba3'},
 'SysUtils.UpperCase': {'start': '0x6186e4',
                        'end': '0x61875c',
                        'sha256': '31d49e2c60709181dfc1e9cf67b3f0aeed856589842419b8ba2a7b8fc7205753'},
 'SysUtils.LowerCase': {'start': '0x6187ac',
                        'end': '0x618824',
                        'sha256': 'a673244ff7f84d8f63b2ad8c2d29b56a0c89489c85b2b1e0876378e75b6259ce'},
 'SysUtils.LowerCaseFromAnsiString': {'start': '0x61875c',
                                      'end': '0x6187ac',
                                      'sha256': 'b4640869f66a5c2091be6745558069deefb057e79f0baa9b34e044795dac22a2'},
 'CIS_TThermostat.TPlantControlService.FindExistingGroup': {'start': '0xfe2afc',
                                                            'end': '0xfe2be4',
                                                            'sha256': 'b375c529b20d7d4bdcf23c94e14b660eae67fe67fbdf31e31c172d8173bc8087'},
 'CIS_TThermostat.TPlantControlService.GetDefaultCoolStage3OutputGroupName': {'start': '0xfe6c84',
                                                                              'end': '0xfe6d88',
                                                                              'sha256': '22c8612c4b72fd777faa9dc7cf595a5404759c4f435f7dd15501f59f907bfba1'},
 'CIS_TThermostat.TPlantControlService.GetDefaultCoolStage3OutputGroupForPlantType': {'start': '0xfe6d88',
                                                                                      'end': '0xfe6fe4',
                                                                                      'sha256': 'cee4ff157a9d086126e88dcab78c45f5dcb6e8e0c09296e1a23ad0f41754c301'},
 'SysUtils.AnsiCompareText': {'start': '0x618cb0',
                              'end': '0x618d7c',
                              'sha256': '9cc63b66ab4bc741bb7bd430cb0d1bfb97b808927701b8cbba2fbdf882213948'},
 'SysUtils.GetFormatSettings': {'start': '0x62370c',
                                'end': '0x623af8',
                                'sha256': '59fa7fe20b60051409ff17db43b144cd373dcfb2b98c4bdea74c1558e6348f7b'},
 'SysUtils.GetLocaleChar': {'start': '0x62110c',
                            'end': '0x621138',
                            'sha256': '89e69f3dac843094931fe9fbffc88ebb85915111ccdfafffb77655b62eeb2959'},
 'Windows.GetStringTypeEx': {'start': '0x60e5d0',
                             'end': '0x60e5d8',
                             'sha256': '51d909813d91cb60afee64b293014177fbef6fcfea6c935df74afd3a6ac69e9e'},
 'Windows.CompareString': {'start': '0x60e274',
                           'end': '0x60e27c',
                           'sha256': 'd08516504df68989588260acb4c5c87c07927bc8856d821420911d34ffbd1576'},
 'JclStrings.LoadCharTypes': {'start': '0x781164',
                              'end': '0x7811a8',
                              'sha256': '79e68725a9e6e2b3b7463471399064f9d5269d0e1b968cde84af84a6612a9326'},
 'JclStrings.CharIsNumberChar': {'start': '0x78217c',
                                 'end': '0x7821c0',
                                 'sha256': '26c465b0e45cf1e2fedd86c91f0b7f6f31e57b92853af00d96472778eca3a5d8'},
 'JclStrings.StrConsistsOfNumberChars': {'start': '0x781350',
                                         'end': '0x7813b4',
                                         'sha256': '0099b0469ea60e453e02fea1abdab1dce26ea1cb096517c08a5917c6ac4abcb8'},
 'JclStrings.JclStrings': {'start': '0x1369f98',
                           'end': '0x1369fac',
                           'sha256': 'd18eae48ff7cb4cb57550210fa48c53e3b6f3a546733f8b886884b68ee9cad83'},
 'CIS_TCommonCBus.TCBUSApplication.InternalCreate': {'start': '0xf25704',
                                                     'end': '0xf25858',
                                                     'sha256': '74f748a4f29c737d626e5b88c62f5f60f6cd3a03eda9d46c4579f189706b5a0a'},
 'CIS_GlobalSoftwareParameters.SortModeGroupsUseAddress': {'start': '0x85b428',
                                                           'end': '0x85b43c',
                                                           'sha256': '29c9ec42994f8ce7dcf3c3f863c01fc292d7f4514b05ef912f42da2e178fd236'},
 'CIS_GlobalSoftwareParameters.LoadParametersFromRegistry': {'start': '0x85b67c',
                                                             'end': '0x85b924',
                                                             'sha256': 'b795c0830c979300b3b19b0ee41c2e4d62bdd9564bfb1105398c2da0dbe347b9'},
 'CIS_TCommonCBus.TCBusInstallation.SortAll': {'start': '0xf33190',
                                               'end': '0xf33430',
                                               'sha256': 'efa408665292c36e15f7f35d378c5b2f78827e905b6563cf58de1053a37d7195'},
 'CIS_TCommonCBus.TCBusGroupManager.Add': {'start': '0xf288f0',
                                           'end': '0xf28938',
                                           'sha256': 'd704bcb463fb41fb081f4a84151545818e93ca35b31da0eb74cb763d3bd3c0a9'},
 'CIS_TCustomFlashObject.TFlashObjectReferenceCollection.Append': {'start': '0x7e84ac',
                                                                   'end': '0x7e8730',
                                                                   'sha256': 'efb8b52181bf7c3850a8692720016f9dd76b785be74c9d23e7b9e6947fca72f3'},
 'CIS_TCustomFlashObject.TFlashObjectCollection.Append': {'start': '0x7e9fd0',
                                                          'end': '0x7ea004',
                                                          'sha256': '4e2bc2432cee7bbe7b3a04fca57752f41253a10460ee3f87da96ee298823de45'},
 'CIS_TCustomFlashObject.TFlashObjectCollection.AddSessionID': {'start': '0x7e9f3c',
                                                                'end': '0x7e9fd0',
                                                                'sha256': '8ad22431263e67e95a7d91941161f2593bd73c4b23bfcddd444e1ec8712dd757'},
 'CIS_TCustomFlashObject.TFlashObjectReferenceCollection.Compare': {'start': '0x7e98f8',
                                                                    'end': '0x7e9978',
                                                                    'sha256': '4010c8b23fb9138f5051c5f4ae0948b9369c812f32f92e1226988b7015e539ef'},
 'CIS_TCustomFlashObject.TFlashObjectReferenceCollection.QuickSort': {'start': '0x7e97c4',
                                                                      'end': '0x7e98f8',
                                                                      'sha256': '3a35266c9903303e60f220b580c5c7fc7d60da84f057fd39d86169ba35955615'},
 'CIS_TCustomFlashObject.QuickInsert': {'start': '0x7e9a84',
                                        'end': '0x7e9b30',
                                        'sha256': 'e4143c93209136ddd59564fa205e46041e67770b0e99a8aa7a3de2c4248c6651'},
 'CIS_TCustomFlashObject.TFlashObjectReferenceCollection.GetSortedInsertLocation': {'start': '0x7e9b30',
                                                                                    'end': '0x7e9b70',
                                                                                    'sha256': '7603adf73bc8371cedfabafb1463fa7963bf1bc923ba242978d4b76b2fd41ed7'},
 'CIS_TCustomFlashObject.TFlashObjectReferenceCollection.DoFullSort': {'start': '0x7e99b0',
                                                                       'end': '0x7e9a0c',
                                                                       'sha256': '6c2cc44d19cfe400712a90e2803485da54462d225ea13e23f73393acd50164f6'},
 'CIS_TCustomFlashObject.TFlashObjectReferenceCollection.SetSortStyle': {'start': '0x7e9978',
                                                                         'end': '0x7e99b0',
                                                                         'sha256': 'db6638575da006b04c97fb19c7dd4bf8e108c5a6a60bd4ee1751a41ae457d19d'},
 'CIS_TCustomFlashObject.TFlashObjectReferenceCollection.OnReferencedObjectChange': {'start': '0x7e9b70',
                                                                                     'end': '0x7e9b94',
                                                                                     'sha256': '109f4964f42a44dc31e9acdc162af532ee25f7a904266ced3ff8f936cae5b565'},
 'CIS_TCustomFlashObject.TFlashObjectReference.ResolveReference': {'start': '0x7ed41c',
                                                                   'end': '0x7ed68c',
                                                                   'sha256': 'fb0c76794fcaaf8c758111beb938ca33aba43d4f07bf4b74de29132c5abc56e7'},
 'CIS_TCustomFlashObject.TFlashObjectReference.SetFlashObject': {'start': '0x7ed6d4',
                                                                 'end': '0x7ed85c',
                                                                 'sha256': '159d5010edfa3ee972a627f414609ac6dc02e1645e7c98cf8cc46fba8221b740'},
 'CIS_TCustomFlashObject.TFlashObjectReference.ObjectChanged': {'start': '0x7ed3c4',
                                                                'end': '0x7ed3e8',
                                                                'sha256': '7afab599ae69adb9977c6f08f5ef6891571a67dfb79150c353a955e49ad4d334'},
 'CIS_TCBusObject.TCGateObjectManager.LoadAndSort': {'start': '0xf48798',
                                                     'end': '0xf487e0',
                                                     'sha256': '07225b4cb7f3f8f3f8905956c308890e60e23db28645329d5498521dba60d536'},
 'CIS_TCBusObject.TCGateObjectManager.CustomSortAddressAsc': {'start': '0xf4825c',
                                                              'end': '0xf48488',
                                                              'sha256': 'b5bd0358ec5d6c19a91107df4a3969458b4a7ad4f03bf43c61e1bf1508aec565'},
 'CIS_TCBusObject.TCGateObjectManager.CustomSortTagNameAsc': {'start': '0xf48488',
                                                              'end': '0xf48708',
                                                              'sha256': 'd6005d0f610c5d92df7c4846c76a355e0823fee802d849e43020e395458e1bda'},
 'CIS_TCBusObject.TCGateObjectManager.SetSortStyleCustomAddressAsc': {'start': '0xf48850',
                                                                      'end': '0xf48874',
                                                                      'sha256': '3330851a47529c9fc524358e61092edb4ad19601c69bfc38f4c7dc810b7d406b'},
 'CIS_TCBusObject.TCGateObjectManager.SetSortStyleCustomTagNameAsc': {'start': '0xf48874',
                                                                      'end': '0xf48898',
                                                                      'sha256': '01ee4000697615582739b0f2728059b078837628a14a59defd18822492bd2896'},
 'CIS_TCBusObject.TCGateObjectManager.SetAfterChangeTimerEnabled': {'start': '0xf487e0',
                                                                    'end': '0xf48850',
                                                                    'sha256': '49801b500170370f219c0d2c41c82a7f6b32f49842b545587916a4f80909bc02'},
 'CIS_TCBusObject.TCGateObjectManager.HandleAfterChangeTimerTrigger': {'start': '0xf48708',
                                                                       'end': '0xf48764',
                                                                       'sha256': '00e42c5ff7d77f4a8cff15b6cb93a027a3bfc24d31d76f169980de62729632b4'},
 'CIS_TCBusObject.TCGateObject.HandleAddressAfterChange': {'start': '0xf47a74',
                                                           'end': '0xf47b04',
                                                           'sha256': 'c7767271ac318b1a0e3a0f1b86a38100c043f4b6e6bdafa60fb5685d96f82cf1'},
 'CIS_TCBusObject.TCGateObject.HandleTagNameAfterChange': {'start': '0xf47b04',
                                                           'end': '0xf47bc8',
                                                           'sha256': 'a46b76fa204592199ff06435847c7f67f4f44b69a4c313a13ef1790d57661a23'},
 'CIS_TCBusObject.TCGateAddressAttribute.PopulateCacheValues': {'start': '0xf47eb8',
                                                                'end': '0xf48128',
                                                                'sha256': '7d8463e3db2a186503eb7f66f81d6f5be7936f8c0ca24b84b16b8f940b6124f6'},
 'CIS_TStringAttribute.TStringAttribute.InternalCreate': {'start': '0x7f37ac',
                                                          'end': '0x7f37d4',
                                                          'sha256': 'b2fc88b81327f8e2c960c8bff3d9364e68678d8ce9ba7fb9ceaf069993c8f4e4'},
 'CIS_TCBusObject.TCGateAddressAttribute.InternalCreate': {'start': '0xf481b4',
                                                           'end': '0xf481d0',
                                                           'sha256': '6c4601cc471444d394da51b62dc370be3096b6e8b58d0997e8865811c8172754'},
 'CIS_TCBusObject.TCGateObject.InternalCreate': {'start': '0xf47718',
                                                 'end': '0xf47880',
                                                 'sha256': '4f01608515a4aa6f5c989179f9eb001c39157861197fa9bfee3755f93370e260'},
 'CIS_TCGateCommand.TCGateCommand.Create': {'start': '0x8435dc',
                                            'end': '0x8436a4',
                                            'sha256': 'ef73b8e483d707e5737996723c5951b74daea5bd2f4defd0c3e00b452e6b0e21'},
 'CIS_TCGateCommand.TCGateCommand.InternalCreate': {'start': '0x843d84',
                                                    'end': '0x843d90',
                                                    'sha256': '494a3d3de7da0c232ada45a412c22b34308512ba69a64a307a2dee62e847af54'},
 'CIS_TCGateCommand.TCGateCommand.CommandExecuteBegin': {'start': '0x843bdc',
                                                         'end': '0x843c1c',
                                                         'sha256': '45f21f7eeee6e7eb72b13cce62804b19535910088c48736fbeac099adaafa247'},
 'CIS_TCGateCommand.TCGateCommand.CommandExecuteEnd': {'start': '0x843c1c',
                                                       'end': '0x843c5c',
                                                       'sha256': '3c4d94f097a4d8fcd40eec3aa306fb0dc606e972ad95b13a8396ac23a8269057'},
 'CIS_TCGateCommand.TCGateCommand.CommandExecute': {'start': '0x843860',
                                                    'end': '0x843bdc',
                                                    'sha256': '2a178ac3350bcf00d4275958f76aaea58a97c051cda5c52c987a39715485da60'},
 'CIS_TCGateCommand.InternalSendCommand': {'start': '0x8437bc',
                                           'end': '0x843860',
                                           'sha256': '3583bbfbac3a4dbfe7080e63a1b3d2a732c06cba47285e67b12cd5c25603b3e6'},
 'CIS_TCGateCommunicatorSocketHelper.TCGateCommunicationProcessor.SendCommand': {'start': '0xf4e0e8',
                                                                                 'end': '0xf4e25c',
                                                                                 'sha256': '0c1ce250ffb18a33671e5e3392fa6d2e4703b872919899fb6519cecc8cc28aca'},
 'CIS_TThreadWrappedIndySocket.TThreadCommandSocket.ProcessCommand': {'start': '0xf516a0',
                                                                      'end': '0xf519a0',
                                                                      'sha256': '0969b28dd34aa8a1860969785f76fc8be5c9b5cb739a31da63603d6e95a07ba1'},
 'CIS_TCGateCommand.TThreadCommandSynchroniser.Create': {'start': '0x844068',
                                                         'end': '0x84422c',
                                                         'sha256': '384f8b53b72a3896f58f584b6529e619e693f279978aec1dd58c2f2d1801e97c'},
 'CIS_TCGateCommand.TThreadCommandSynchroniser.ProcessResponsesSync': {'start': '0x8446f0',
                                                                       'end': '0x844904',
                                                                       'sha256': '1ae539a0ac6900d55fb06026d96e6c44f1a27801be782570fce80b1782a3dcd6'},
 'CIS_TCGateAgent.TCGateAgent.CommandDBSet': {'start': '0xcac928',
                                              'end': '0xcacaf0',
                                              'sha256': '6b426870691e983d78a22c72c06974511c65c0cfbf8a42cb46841f02a394bbaf'},
 'CIS_TCGateAgent.TCGateAgent.CommandDBAdd': {'start': '0xcad208',
                                              'end': '0xcad3a8',
                                              'sha256': '26a750e37de1384c27f5145a1fdbeb999cb81bd5a23b28545f7abd5ec9cb8caf'},
 'CIS_TProjectCGateAgent.TProjectCGateAgent.CommandProjectSave': {'start': '0x120a3e4',
                                                                  'end': '0x120a58c',
                                                                  'sha256': 'd951d371d1aca5795c3a45aba88ef801e64587c934e8992778529d815605b81a'},
 'CIS_TcgcProjectSave.TcgcProjectSave.Create': {'start': '0x1137f2c',
                                                'end': '0x1137f74',
                                                'sha256': 'dbf8e40ee8698e21a68fa0ae3d7a76c444526e7a1088cb0da7e167289305c09f'},
 'System.TObject.InitInstance': {'start': '0x60620c',
                                 'end': '0x606264',
                                 'sha256': 'fb7cb3f8df9713f17bd5d9170506b9dba7bd3f7ad43b4e0839aa4ec298c204a7'},
 'CIS_TBaseObject.TBASEObject.Create': {'start': '0x7681f0',
                                        'end': '0x768234',
                                        'sha256': '1d99602b403c4cee4c169a3f19e26de7d700cf3a7484bc7747d4b12dc5a305c1'},
 'SyncObjs.THandleObject.Create': {'start': '0x6525c4',
                                   'end': '0x652608',
                                   'sha256': 'df63d50515ab010a5b6f3eada853421724aa4fa86663330eb21b52127c36168e'},
 'SyncObjs.THandleObject.WaitFor': {'start': '0x652638',
                                    'end': '0x6526cc',
                                    'sha256': '9c92acce3af31f3d4d23ae544b1b64b33709679ee6e458a70e0988d0c9d76af1'},
 'SyncObjs.TEvent.Create@0x6526cc': {'start': '0x6526cc',
                                     'end': '0x652734',
                                     'sha256': 'd52b1c30868b5d372745a58b7af069ba12d27a82955e35219059f40aaff116fb'}}

POINTS = {'0xf28e66': ('call', '0x6186e4'),
 '0xf28ece': ('call', '0x6186e4'),
 '0xf28ed9': ('call', '0x6090ac'),
 '0xf28eee': ('jmp', '0xf28ef8'),
 '0x6186fe': ('cmp', 'ax, 2'),
 '0x618702': ('je', '0x618713'),
 '0x618736': ('movzx', 'eax, word ptr [ebx]'),
 '0x61873b': ('add', 'esi, -0x61'),
 '0x61873e': ('sub', 'si, 0x1a'),
 '0x618742': ('jae', '0x618748'),
 '0x618744': ('xor', 'ax, 0x20'),
 '0x618748': ('mov', 'word ptr [ecx], ax'),
 '0x6187c6': ('cmp', 'ax, 2'),
 '0x6187ca': ('je', '0x6187db'),
 '0x6187d4': ('call', '0x61875c'),
 '0x6187fe': ('movzx', 'eax, word ptr [ebx]'),
 '0x618803': ('add', 'esi, -0x41'),
 '0x618806': ('sub', 'si, 0x1a'),
 '0x61880a': ('jae', '0x618810'),
 '0x61880c': ('or', 'ax, 0x20'),
 '0x618767': ('call', '0x608b50'),
 '0x618789': ('movzx', 'ecx, word ptr [eax]'),
 '0x61878c': ('add', 'ecx, -0x41'),
 '0x61878f': ('sub', 'cx, 0x1a'),
 '0x618793': ('jae', '0x61879f'),
 '0x618798': ('or', 'cx, 0x20'),
 '0xfe2b4b': ('mov', 'dword ptr [ebp - 0x14], 0'),
 '0xfe2b6c': ('call', '0xf28954'),
 '0xfe2b8b': ('call', '0x6187ac'),
 '0xfe2b9a': ('call', '0x6187ac'),
 '0xfe2ba3': ('call', '0x6090ac'),
 '0xfe2ba8': ('jne', '0xfe2bb2'),
 '0xfe2bb0': ('jmp', '0xfe2bba'),
 '0xfe6dfb': ('call', 'dword ptr [edx + 0xa0]'),
 '0xfe6e01': ('and', 'al, byte ptr [ebp - 9]'),
 '0xfe6e04': ('jne', '0xfe6e36'),
 '0xfe6e2a': ('call', '0x6094d4'),
 '0xfe6e30': ('jne', '0xfe6fb7'),
 '0xfe6e9b': ('cmp', 'dword ptr [ebp - 0x10], 0'),
 '0xfe6e9f': ('jne', '0xfe6fb7'),
 '0xfe6ced': ('xor', 'edx, edx'),
 '0xf27d64': ('call', '0x6094d4'),
 '0xf27d69': ('dec', 'eax'),
 '0xf27db6': ('add', 'edx, 2'),
 '0xf27db9': ('mov', 'ecx, 0x64'),
 '0xf27dc1': ('call', '0x609114'),
 '0xf27dc9': ('call', '0x781350'),
 '0xf257ad': ('call', '0x85b428'),
 '0xf257b4': ('je', '0xf257c7'),
 '0xf257bf': ('call', '0xf48850'),
 '0xf257d0': ('call', '0xf48874'),
 '0x85b695': ('mov', 'byte ptr [0x144df26], 0'),
 '0x85b761': ('call', '0x6619e4'),
 '0x85b766': ('mov', 'byte ptr [0x144df26], al'),
 '0xf28911': ('call', '0x7ea6ac'),
 '0xf28921': ('call', 'dword ptr [ecx + 0x68]'),
 '0xf2892a': ('mov', 'dword ptr [eax + 0x94], edx'),
 '0x7e9fc2': ('call', '0x643784'),
 '0x7e9ff2': ('call', '0x7e84ac'),
 '0x7ed7ff': ('je', '0x7ed827'),
 '0x7ed808': ('je', '0x7ed827'),
 '0x7ed824': ('call', 'dword ptr [ebx + 0x28]'),
 '0x7e859e': ('cmp', 'byte ptr [eax + 0x59], 0'),
 '0x7e85aa': ('call', '0x7e9b30'),
 '0x7e85be': ('call', '0x6439e4'),
 '0x7e85ce': ('call', '0x643784'),
 '0x7e9ac3': ('cmp', 'dword ptr [ebp - 0x1c], 0'),
 '0x7e9ac9': ('mov', 'eax, dword ptr [ebp - 0x14]'),
 '0x7e9ad7': ('mov', 'eax, dword ptr [ebp - 0x14]'),
 '0x7e9ae2': ('inc', 'eax'),
 '0x7e98a1': ('call', '0x643ad8'),
 '0x7e98b2': ('call', '0x643ad8'),
 '0x7e9b88': ('call', '0x7e99b0'),
 '0xf482b6': ('sub', 'ebx, eax'),
 '0xf48311': ('mov', 'dword ptr [eax], 0xffffffff'),
 '0xf4835f': ('mov', 'dword ptr [eax], 1'),
 '0xf48510': ('call', '0x618cb0'),
 '0xf4856e': ('mov', 'dword ptr [eax], 0xffffffff'),
 '0xf485bc': ('mov', 'dword ptr [eax], 1'),
 '0x618d40': ('push', '1'),
 '0x618d42': ('push', '0x400'),
 '0x618d47': ('call', '0x60e274'),
 '0x618d4c': ('sub', 'eax, 2'),
 '0xf47f37': ('mov', 'dword ptr [eax + 0x88], 0xff'),
 '0xf481c6': ('mov', 'byte ptr [eax + 0x94], 1'),
 '0x7f37cb': ('call', '0x608924'),
 '0xf4875b': ('call', '0x7e99b0'),
 '0xf487d4': ('call', '0x7e99b0'),
 '0xf4881d': ('call', '0x697290'),
 '0xf48844': ('call', '0x697280'),
 '0xf47b63': ('cmp', 'byte ptr [eax + 0x59], 3'),
 '0xf47b8a': ('cmp', 'byte ptr [eax + 0x84], 0'),
 '0xf47abc': ('cmp', 'byte ptr [eax + 0x59], 3'),
 '0xf47ae3': ('cmp', 'byte ptr [eax + 0x84], 0'),
 '0x844732': ('call', 'dword ptr [ecx + 8]'),
 '0x8447ac': ('cmp', 'byte ptr [eax + 0x78], 0'),
 '0x8447b0': ('je', '0x8447de'),
 '0x8447b9': ('call', '0x725c90'),
 '0x8440b8': ('push', '0'),
 '0x8440ba': ('push', '0'),
 '0x8440bc': ('push', '0'),
 '0x8440be': ('push', '0'),
 '0x8440c9': ('call', '0x6526cc'),
 '0x6526e4': ('movzx', 'ecx, byte ptr [ebp + 8]'),
 '0x6526ec': ('call', '0x6525c4'),
 '0x6525e6': ('mov', 'byte ptr [esi + 0xc], bl'),
 '0x65263d': ('cmp', 'byte ptr [esi + 0xc], 0'),
 '0x652641': ('je', '0x652683'),
 '0x652683': ('push', '0'),
 '0x65268e': ('call', '0x60e868'),
 '0x623742': ('call', '0x60e600'),
 '0x6237c6': ('mov', 'cx, 0x2e'),
 '0x6237ca': ('mov', 'edx, 0xe'),
 '0x6237d1': ('call', '0x62110c'),
 '0x6237d6': ('mov', 'word ptr [0x13c9ecc], ax'),
 '0x621116': ('push', '2'),
 '0x62111f': ('call', '0x60e504'),
 '0x621128': ('movzx', 'eax, word ptr [esp]'),
 '0x62112e': ('mov', 'eax, edi'),
 '0x1369fa1': ('call', '0x781164'),
 '0x781168': ('mov', 'word ptr [ebp - 2], 0'),
 '0x78116e': ('mov', 'word ptr [ebp - 4], 0'),
 '0x781178': ('push', '1'),
 '0x78117e': ('push', '1'),
 '0x781180': ('push', '0x400'),
 '0x781185': ('call', '0x60e5d0'),
 '0x781192': ('mov', 'word ptr [eax*2 + 0x142c644], dx'),
 '0x78119a': ('inc', 'word ptr [ebp - 2]'),
 '0x78119e': ('cmp', 'word ptr [ebp - 2], 0'),
 '0x7811a3': ('jne', '0x78116e'),
 '0x782188': ('test', 'byte ptr [eax*2 + 0x142c644], 4'),
 '0x782192': ('cmp', 'word ptr [ebp - 2], 0x2b'),
 '0x782199': ('cmp', 'word ptr [ebp - 2], 0x2d'),
 '0x7821a0': ('mov', 'eax, dword ptr [0x13c3f54]'),
 '0x7821a5': ('mov', 'ax, word ptr [eax]'),
 '0x7821a8': ('cmp', 'ax, word ptr [ebp - 2]'),
 '0x781359': ('cmp', 'dword ptr [ebp - 4], 0'),
 '0x78135d': ('setne', 'byte ptr [ebp - 5]'),
 '0x78138f': ('mov', 'ax, word ptr [eax + edx*2 - 2]'),
 '0x781394': ('call', '0x78217c'),
 '0x78139d': ('mov', 'byte ptr [ebp - 5], 0')}

SOURCE_RULES = {'name_lookup': 'Migration GroupByTagNameExclude returns the first current manager position after '
                'excluding the object identity; UpperCase changes ASCII a..z only.',
 'ordinary_name_lookup': 'Ordinary FindExistingGroup iterates current manager positions and returns the '
                         'first equal pair of LowerCase results; it does not call '
                         'GroupByTagNameExclude.',
 'ordinary_lowercase': 'The UTF-16 branch changes ASCII A..Z with OR0x20 only. Its equality classes '
                       'match the ASCII-only UpperCase helper.',
 'ordinary_ansi_fallback': 'The non-UTF16 branch converts with UStrFromLStr, then uses the same ASCII '
                           'A..Z bounds; no locale-sensitive case-conversion call occurs in this '
                           'LowerCase implementation.',
 'unique_name_match': 'No manager-order or Windows collation dependency when the consumed eligible '
                      'match is unique.',
 'default_sort_preference': 'SortModeGroups defaults false (tag name); registry preference can select '
                            'address.',
 'xml_load': 'AddSessionID appends lazy references without sorting; native XML to complete importer '
             'relation order is not established here.',
 'new_group': 'Append receives empty TagName and empty Address; empty Address converts to255 before '
              'later address/name setters.',
 'append': 'Nonzero sort style uses midpoint binary insertion into the current list; equal inserts at '
           'the midpoint.',
 'address_comparator': 'left-right, then distinct left255→-1, then distinct right255→+1; later override '
                       'wins.',
 'tag_comparator': 'CompareStringW(USER_DEFAULT,NORM_IGNORECASE)-2, then the same255 overrides.',
 'full_sort': 'Unstable midpoint quicksort swaps equal entries; repeated sorts may change duplicate '
              'identity order.',
 'rename_timer': 'Address/name AfterChange queues a1ms timer under custom sort; timer clears itself '
                 'then fully sorts.',
 'normal_command_wait': 'DBAdd/DBSet/ProjectSave leave command+0x78 false. Their synchroniser uses '
                        'non-COM, non-alertable waits; its conditional ProcessMessages path is not '
                        'entered.',
 'message_scope': 'Successful inspected storage paths only; no claim for other commands or exception '
                  'dialogs.',
 'default_name': 'Exact localized resource prefix (pinned English resource Group) plus space, nonempty '
                 'suffix of at most100 UTF-16 units, every unit accepted by CharIsNumberChar.',
 'number_character': 'C1_DIGIT bit4 from startup StrCharTypes OR plus OR minus OR current '
                     'DecimalSeparator.',
 'ctype_initialization': 'Each of65536 UTF-16 code units separately calls '
                         'GetStringTypeExW(0x400,1,unit,1,flags), with flags reset0 and return ignored.',
 'decimal_separator': 'SysUtils.GetFormatSettings uses GetThreadLocale and GetLocaleInfoW(SDECIMAL=14), '
                      'first UTF-16 unit with period fallback.',
 'classifier_consumption': 'The initial UpdateGroup old-name reuse branch consults HasDefaultTagName '
                           'only if destination lookup found an old-name candidate; pinned separately '
                           'by application-change verifier. Later cl=true role default getters can '
                           'independently classify the newly allocated generic Group N before deciding '
                           'whether to rename it.',
 'unlabeled_role': 'For virtual plant1 CoolStage3 has an empty generated role label. Its default getter '
                   'preserves an existing provisional group whether HasDefaultTagName succeeds or '
                   'fails; it does not turn that non-unused group into255.'}

BOUNDARY = {'implementation_complete': False,
 'original_execution': False,
 'historical_windows_ctype_table': 'Not embedded in EXE; no retained exact NLS table or captured API '
                                   'bitset established.',
 'python_unicode_category_equivalence': False,
 'initial_manager_order': 'Depends on actual load, sort preference, full-sort count and prior timer '
                          'history; arbitrary XML/address sorting is not authorized.',
 'tag_collation_profile': 'Windows locale/NLS input, not ASCII UpperCase equality.',
 'partial_dependency_resolution': 'A nonmatching prefix or definitive false suffix unit settles the '
                                  'classifier without assigning unrelated Unicode table bits.',
 'runtime_profile_fabricated': False}

def inspect(exe: Path, map_path: Path):
    raw, mapping = exe.read_bytes(), map_path.read_bytes()
    sha = lambda value: hashlib.sha256(value).hexdigest()
    if (sha(raw), sha(mapping)) != (EXE_SHA256, MAP_SHA256):
        raise ValueError('Expected the pinned Toolkit executable and map')
    image = _Image(raw, mapping)
    image.by_name['SyncObjs.TEvent.Create@0x6526cc'] = 0x6526cc
    walker = _Walker(image)
    checks, methods, instructions, listings = {}, {}, {}, {}
    for symbol, expected in METHODS.items():
        rows, _tables, digest = walker.listing(symbol)
        start = image.by_name[symbol]
        end = next(address for address in image.starts if address > start)
        actual = {'start': hex(start), 'end': hex(end), 'sha256': digest}
        checks['method:' + symbol] = actual == expected
        methods[symbol] = actual
        listings[symbol] = rows
        instructions.update({hex(a): (m, p) for a, m, p, _ in rows})
    checks.update({address: instructions.get(address) == expected
                   for address, expected in POINTS.items()})
    def word(address):
        return struct.unpack('<I', image.pe.get_data(address - image.base, 4))[0]
    slots = {}
    for name in ('CIS_TcgcDBAdd..TcgcDBAdd', 'CIS_TcgcDBSet..TcgcDBSet',
                 'CIS_TcgcProjectUse..TcgcProjectUse', 'CIS_TcgcProjectSave..TcgcProjectSave'):
        vmt = word(image.by_name[name])
        actual = {hex(off): hex(word(vmt + off)) for off in (0x10, 0x1c, 0x20)}
        checks['vmt:' + name] = actual == {'0x10': '0x843d84', '0x1c': '0x843bdc', '0x20': '0x843c1c'}
        slots[name] = {'vmt': hex(vmt), 'slots': actual}
    vmt = word(image.by_name['CIS_TCommonCBus..TCBusGroupManager'])
    checks['group_manager_append_slot'] = word(vmt + 0x68) == 0x7e9fd0
    checks['group_manager_xml_add_slot'] = word(vmt + 0xb0) == 0x7e9f3c
    checks['decimal_separator_pointer'] = word(0x13c3f54) == 0x13c9ecc
    checks['cool_stage3_plant1_empty_label'] = word(0xfe6cab + 4) == 0xfe6cea
    checks['cool_stage3_plant1_preserve_existing'] = word(0xfe6e51 + 4) == 0xfe6e9b
    checks['group_resource'] = image.resource(0xf210dc) == 'Group'
    checks['sort_registry_key'] = image.literal(0x85b8d8) == 'SortModeGroups'
    imports = {item.address: (entry.dll.decode(), item.name.decode())
               for entry in image.pe.DIRECTORY_ENTRY_IMPORT for item in entry.imports if item.name}
    checks['ctype_unicode_import'] = imports.get(0x1456948) == ('kernel32.dll', 'GetStringTypeExW')
    checks['compare_unicode_import'] = imports.get(0x1456a74) == ('kernel32.dll', 'CompareStringW')
    if not all(checks.values()):
        raise ValueError('Order/default-tag source differs: ' + ', '.join(key for key, value in checks.items() if not value))
    if (sha(exe.read_bytes()), sha(map_path.read_bytes())) != (EXE_SHA256, MAP_SHA256):
        raise ValueError('Original source inputs changed during inspection')
    return {
        'format': 'cbus-thermostat-application-order-static-v1',
        'original_exe_sha256': EXE_SHA256, 'original_map_sha256': MAP_SHA256,
        'original_executed': False, 'original_emulated': False,
        'native_vendor_executed': False, 'physical_io': False,
        'checks': dict(sorted(checks.items())), 'method_spans': methods,
        'command_vmt_slots': slots, 'source_rules': SOURCE_RULES, 'boundary': BOUNDARY,
    }


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--exe', type=Path, required=True)
    parser.add_argument('--map', type=Path, required=True)
    args = parser.parse_args()
    print(json.dumps(inspect(args.exe, args.map), indent=2, sort_keys=True))


if __name__ == '__main__':
    main()
