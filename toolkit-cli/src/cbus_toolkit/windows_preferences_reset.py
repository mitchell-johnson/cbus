"""Windows-only adapter restricted to the original DontAskAgain subtree."""
import os
import re
from .toolkit_preferences_reset import (
    HKCU,DONT_ASK_AGAIN_KEY,ORIGINAL_ACCESS,OpenKeyResult,KeyInfoResult,EnumKeyResult,
)


class WindowsDontAskAgainRegistry:
    """No registry access at construction; every open/delete stays in one subtree."""
    def __init__(self,*,test_namespace=None):
        if test_namespace is not None and(type(test_namespace)is not str or re.fullmatch(r'[a-z0-9][a-z0-9-]{0,63}',test_namespace)is None):
            raise ValueError('test_namespace must be a simple owned identifier')
        if os.name!='nt':raise RuntimeError('Windows DontAskAgain access requires Windows')
        import ctypes
        from ctypes import wintypes as t
        c=ctypes;self._ctypes=c;self._types=t;self._handles={};self.test_namespace=test_namespace
        api=c.WinDLL('advapi32',use_last_error=True)
        declarations={
            '_open':('RegOpenKeyExW',[t.HKEY,t.LPCWSTR,t.DWORD,t.DWORD,c.POINTER(t.HKEY)]),
            '_query':('RegQueryInfoKeyW',[t.HKEY,t.LPWSTR,c.POINTER(t.DWORD),c.c_void_p,c.POINTER(t.DWORD),c.POINTER(t.DWORD),c.POINTER(t.DWORD),c.POINTER(t.DWORD),c.POINTER(t.DWORD),c.POINTER(t.DWORD),c.POINTER(t.DWORD),c.c_void_p]),
            '_enum':('RegEnumKeyExW',[t.HKEY,t.DWORD,t.LPWSTR,c.POINTER(t.DWORD),c.c_void_p,t.LPWSTR,c.POINTER(t.DWORD),c.c_void_p]),
            '_close':('RegCloseKey',[t.HKEY]),
            '_delete':('RegDeleteKeyExW',[t.HKEY,t.LPCWSTR,t.DWORD,t.DWORD]),
        }
        for attr,(name,args)in declarations.items():
            function=getattr(api,name);function.argtypes=args;function.restype=t.LONG;setattr(self,attr,function)

    def _owned(self,handle):
        if type(handle)is not int or handle not in self._handles:raise ValueError('handle is not owned by this adapter')
        return self._handles[handle]

    def _location(self,parent,key):
        if type(parent)is not int or type(key)is not str or not key or '\0'in key:
            raise ValueError('invalid registry parent or key')
        key.encode('utf-16le')
        if parent==HKCU:
            if key!=DONT_ASK_AGAIN_KEY:raise ValueError('only the original DontAskAgain key is supported')
            logical=key
            actual=('Software\\CBusToolkitCli\\Tests\\'+self.test_namespace+'\\HKCU\\'+key)if self.test_namespace is not None else key
        else:
            logical=self._owned(parent)+'\\'+key
            if '\\'in key:raise ValueError('child must be a single registry key component')
            actual=key
        return actual,logical

    def open_key(self,parent,key,access):
        actual,logical=self._location(parent,key)
        if type(access)is not int or access!=ORIGINAL_ACCESS:raise ValueError('only the original registry access mask is supported')
        handle=self._types.HKEY()
        status=int(self._open(parent,actual,0,access|0x200,self._ctypes.byref(handle)))&0xffffffff
        if status:return OpenKeyResult(status)
        value=int(handle.value)
        if value in self._handles:raise RuntimeError('Windows reused an active registry handle')
        self._handles[value]=logical
        return OpenKeyResult(0,value)

    def query_info(self,handle):
        self._owned(handle);c=self._ctypes;t=self._types
        count,max_name=t.DWORD(),t.DWORD()
        status=int(self._query(handle,None,None,None,c.byref(count),c.byref(max_name),None,None,None,None,None,None))&0xffffffff
        return KeyInfoResult(status,count.value,max_name.value)if not status else KeyInfoResult(status)

    def enum_key(self,handle,index,capacity):
        self._owned(handle)
        if type(index)is not int or not 0<=index<=0xffffffff or type(capacity)is not int or not 1<=capacity<=1000001:
            raise ValueError('invalid enumeration index or capacity')
        c=self._ctypes;buffer=c.create_unicode_buffer(capacity);length=self._types.DWORD(capacity)
        status=int(self._enum(handle,index,buffer,c.byref(length),None,None,None,None))&0xffffffff
        if status:return EnumKeyResult(status)
        if length.value>=capacity:raise RuntimeError('Windows returned an invalid name length')
        return EnumKeyResult(0,''.join(buffer[:length.value]))

    def close_key(self,handle):
        self._owned(handle);self._handles.pop(handle)
        return int(self._close(handle))&0xffffffff

    def delete_key(self,parent,key):
        actual,_=self._location(parent,key)
        # ExW selects the same 32-bit view as the original x86 RegDeleteKeyW.
        return int(self._delete(parent,actual,0x200,0))&0xffffffff
