"""Research-only execution: original DeviceOpen with explicit fake enumeration/descriptors."""
import importlib.util
import json
import struct
from pathlib import Path

HELPER=Path(__file__).resolve().parent/'native_dfu_probe.py'
spec=importlib.util.spec_from_file_location('dfu_probe',HELPER)
module=importlib.util.module_from_spec(spec);spec.loader.exec_module(module)

class OpenProbe(module.Probe):
    def __init__(self,dll,*,case='dfu',index=0):
        super().__init__(dll)
        self.case=case;self.index=index;self.enumerations=[];self.allocations=[]
        self.put(0x1001110C,0x40000600)
        self.stubs[0x40000600]=('enumerate',24)
        self.device=struct.pack('<BBHBBBBHHHBBBB',18,1,0x0200,0,0,0,64,0x166A,0x0501,0x1234,1,2,3,1)
        interface=bytes([9,4,0,0,0,0xFE,1,1 if case=='runtime' else 2,0])
        if case=='wrong-interface-class':interface=interface[:5]+b'\x03'+interface[6:]
        functional=struct.pack('<BBBHHH',9,0x21,7,1000,1024,0x100)
        if case=='missing-functional':functional=b''
        if case=='zero-transfer':functional=struct.pack('<BBBHHH',9,0x21,7,1000,0,0x100)
        if case=='zero-length-interface':interface=bytes([0])+interface[1:]
        self.config=struct.pack('<BBHBBBBB',9,2,9+len(interface)+len(functional),1,1,0,128,50)+interface+functional
        self.upload_data=struct.pack('<IHIIII',1024,1024,0,0,262144,8192)

    def _return(self,value,pop):
        eax,eip,espreg=self.registers;esp=self.u.reg_read(espreg)
        self.u.reg_write(eax,value);self.u.reg_write(eip,self.integer(esp));self.u.reg_write(espreg,esp+4+pop)

    def hook(self,emulator,address,size,user_data):
        eax,eip,espreg=self.registers;esp=self.u.reg_read(espreg)
        if address==0x40000600:
            vid,pid,guid,index,flags,error=[self.integer(esp+4+i*4) for i in range(6)]
            self.enumerations.append({'vid':vid,'pid':pid,'guid_hex':bytes(self.u.mem_read(guid,16)).hex(),'index':index,'flags':flags})
            assert (vid,pid,index,flags)==(0x166A,0x0501,self.index,0)
            self._return(0 if self.case=='not-found' else 0x1234,24);return
        if address==0x100041BB:self.allocations.append(self.integer(esp+4))
        if address==0x40000100:
            handle,bm,request,value,index,length,pointer,output=[self.integer(esp+4+i*4) for i in range(8)]
            if bm==0x80:
                assert handle==0x1234 and request==6 and index==0
                data=self.device if value==0x100 else self.config if value==0x200 else None
                if data is None:raise RuntimeError('Unscripted descriptor request')
                data=data[:length]
                if self.case=='short-device' and value==0x100:data=data[:-1]
                if self.case=='wrong-device-length' and value==0x100:data=bytes([17])+data[1:]
                if self.case=='short-config' and value==0x200:data=data[:-1]
                self.u.mem_write(pointer,data);self.u.mem_write(output,struct.pack('<H',len(data)))
                self.wire.append({'bmRequestType':bm,'bRequest':request,'wValue':value,'wIndex':index,'wLength':length,'data_hex':data.hex(),'fixture_transferred':len(data),'fixture_success':True})
                self._return(1,32);return
            if self.case=='status-failure' and bm==0xA1 and request==3 and not any(r.get('injected_failure') for r in self.wire):
                self.u.mem_write(output,b'\0\0');self.wire.append({'bmRequestType':bm,'bRequest':request,'wLength':length,'injected_failure':True});self._return(0,32);return
            if self.case=='no-extension' and bm==0xA1 and request==0x42:
                self.u.mem_write(pointer,b'NOPE');self.u.mem_write(output,struct.pack('<H',4));self.wire.append({'bmRequestType':bm,'bRequest':request,'data_hex':'4e4f5045'});self._return(1,32);return
        return super().hook(emulator,address,size,user_data)

    def result(self):
        info=self.OUT;handleout=self.OUT+64
        try:result=self.call(0x1000FB80,self.index,info,handleout,0);error=None
        except RuntimeError as e:result=None;error=str(e)
        handle=self.integer(handleout)
        return {'case':self.case,'native_return':result,'execution_error':error,
                'enumerations':self.enumerations,'allocation_lengths':self.allocations,
                'info_hex':bytes(self.u.mem_read(info,36)).hex(),
                'handle_hex':bytes(self.u.mem_read(handle,32)).hex() if handle else None,'wire':self.wire}

if __name__=='__main__':
    dll=Path('research/vendor/toolkit/app/Firmware/eDLTFirmware/usb_drivers/i386/lmdfu_edlt.dll')
    cases=['dfu','runtime','not-found','short-device','wrong-device-length','short-config',
           'wrong-interface-class','missing-functional','zero-transfer','status-failure','no-extension','zero-length-interface']
    rows=[]
    for case in cases:
        row=OpenProbe(dll,case=case,index=2).result();rows.append(row)
        print(case,row['native_return'],row['execution_error'],row['info_hex'])
    Path('research/runtime/native-dfu-device-open.json').write_text(json.dumps({'scope':'Unchanged original DeviceOpen with fake USB enumeration and descriptors; no hardware','cases':rows},indent=2)+'\n')
