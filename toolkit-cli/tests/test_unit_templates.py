"""Literal Toolkit templates, original EXE parser/checksum, native database I/O."""
from dataclasses import replace
import json
import os
from pathlib import Path
import struct
import sys
import unittest
from uuid import uuid4
import xml.etree.ElementTree as ET

from cbus_toolkit.unit_templates import UnitTemplates, UnitTemplate, UnitTemplateError, UnitTemplateApplyError, ATTRIBUTE_ORDER, PARAMETERS, PROFILES, PROFILE, template_crc
from cbus_toolkit.unitspec import UnitSpecStore,ParameterSpec
from test_macros import fixture as key_fixture, Session


ORDER=('Application','FirmwareVersion','UnitName','UnitType','LearnAnyApp','LearnMode','AreaGroupAddress',
       'StatusReportInterval','GroupAddress','DebounceTime','IndicatorBrightness','LongPressTime',
       'EEPROMLevelStore','LightIndex','LightLevel','LightLevelStore1','LightLevelStore2','RampRate',
       'InfraRedBank','JPCommand','SRCommand','LPCommand','LRCommand','BlockAllocation','IndicatorBlockAssignment',
       'IndicatorFunction','TimerHighByte','TimerLowByte','TimerExpiryCommand','GAVBroadcastFlag')


def fixture(unit_type='KEY4'):
    spec=key_fixture(unit_type);params=dict(spec.parameters)
    for name,kind,address,size,bits,bit,default in (
        ('LearnAnyApp','bit',62,1,1,4,'0'),('LearnMode','bit',62,1,1,3,'0'),
        ('AreaGroupAddress','int',67,1,8,0,'255'),('StatusReportInterval','int',66,1,8,0,'3'),
        ('DebounceTime','int',48,1,6,0,'3'),('IndicatorBrightness','int',63,1,8,0,'255'),
        ('LongPressTime','int',49,1,6,0,'25'),('EEPROMLevelStore','bit',62,1,1,1,'0'),
        ('LightIndex','int',0,1,8,0,'0'),('LightLevel','int',1,16,8,0,'0 '*8+'255 '*8),
        ('RampRate','int',64,2,8,0,'1 3'),('IndicatorBlockAssignment','int',96,4,2,0,'0 1 2 3'),
        ('IndicatorFunction','int',96,4,2,2,'0 0 0 0'),('UnitName','sixbit',42,8,8,0,'NEWUNIT')):
        fields={'Name':name,'Type':kind,'Address':str(address),'ArraySize':str(size),'BitSize':str(bits),
                'BitAddress':str(bit),'DefaultValue':default}
        params[name]=ParameterSpec(name,kind,'literal-template.xml',fields)
    return replace(spec,parameters=params)


class UnitTemplateTest(unittest.TestCase):
    def setUp(self):self.spec=fixture();self.templates=UnitTemplates(self.spec);self.current=self.spec.defaults()

    def test_literal_format_inclusion_identity_duplicates_and_crc(self):
        template=self.templates.from_values(self.current)
        self.assertEqual(ATTRIBUTE_ORDER,ORDER);self.assertEqual(template.crc,14735)
        text=template.to_xml();root=ET.fromstring(text)
        self.assertEqual([n.tag for n in root],['Description','UnitType','FirmwareVersion','CRC']+list(ORDER))
        self.assertEqual([n.text for n in root.findall('UnitType')],['KEY4','KEY4'])
        self.assertNotIn('<UnitAddress>',text);self.assertNotIn('<Project>',text);self.assertNotIn('<LearnedFlag>',text)
        self.assertEqual(UnitTemplate.from_xml(text).attributes,template.attributes)
        self.assertEqual(UnitTemplate.from_xml(text.encode()).crc,14735)

    def test_exact_classic_profiles_and_cross_type_rejection_before_io(self):
        self.assertEqual(PROFILE,('KEY4','1.2.67','5034N','KEY4.xml'))
        for unit_type,catalog in (('KEY1','5031N'),('KEY2','5032N'),('KEY4','5034N')):
            spec=fixture(unit_type);templates=UnitTemplates(spec)
            template=templates.from_values(spec.defaults());parsed=UnitTemplate.from_xml(template.to_xml())
            self.assertEqual(parsed.as_dict()['tested_catalog_number'],catalog)
            self.assertEqual(parsed.attributes['UnitType'],unit_type)
            session=Session(spec);session.firmware='1.2.67';session.catalog_number=catalog
            self.assertTrue(templates.apply(session,parsed)['verified'])
            for other in (kind for kind in ('KEY1','KEY2','KEY4')if kind!=unit_type):
                wrong=UnitTemplates(fixture(other)).from_values(spec.defaults())
                with self.assertRaisesRegex(UnitTemplateError,'cross-type'):templates.apply(session,wrong)
                self.assertEqual(session.calls,[])
            for kwargs in ({'firmware':'1.2.66'},{'catalog_number':'OTHER'}):
                with self.assertRaises(UnitTemplateError):UnitTemplates(spec,**kwargs)

    def test_decimal_hex_and_padding_equivalence(self):
        current=dict(self.current,Application='0x38 0xff',UnitName='NEWUNIT ',JPCommand='0xB 0xB 0xB 0xB')
        first=self.templates.from_values(self.current);second=self.templates.from_values(current)
        self.assertEqual(first.to_xml(),second.to_xml())
        altered=first.to_xml().replace('<Application>56 255</Application>','<Application>0x38 0xff</Application>')
        self.assertEqual(UnitTemplate.from_xml(altered).crc,14735)

    def test_description_escapes_and_is_not_in_checksum(self):
        template=self.templates.from_values(self.current,description='Key <a> & "b"')
        self.assertIn('Key &lt;a&gt; &amp; "b"',template.to_xml())
        self.assertEqual(template.crc,14735);self.assertEqual(UnitTemplate.from_xml(template.to_xml()).description,template.description)

    def test_original_decimal_spacing_crc_checked_before_canonicalization(self):
        template=self.templates.from_values(self.current)
        fields=dict(template.attributes,Application='56  255')
        crc=template_crc(fields)
        self.assertNotEqual(crc,14735)
        text=template.to_xml().replace('<Application>56 255</Application>','<Application>56  255</Application>').replace('<CRC>14735</CRC>',f'<CRC>{crc}</CRC>')
        self.assertEqual(UnitTemplate.from_xml(text).to_xml(),template.to_xml())

    def test_xml_special_characters_match_original_writer(self):
        template=self.templates.from_values(dict(self.current,UnitName='A<&"B'))
        self.assertIn('<UnitName>A&lt;&amp;&quot;B</UnitName>',template.to_xml())
        self.assertEqual(UnitTemplate.from_xml(template.to_xml()).attributes['UnitName'],'A<&"B')
        with self.assertRaises(UnitTemplateError):UnitTemplate.from_xml(template.to_xml().replace('&amp;','&#38;'))

    def test_crc_corruption_identity_and_virtual_values_rejected(self):
        text=self.templates.from_values(self.current).to_xml()
        for changed in (text.replace('<CRC>14735','<CRC>0'),text.replace('<DebounceTime>3','<DebounceTime>4'),
                        text.replace('KEY4','KEY2'),text.replace('1.2.67','1.2.68'),
                        text.replace('<InfraRedBank>0','<InfraRedBank>1'),text.replace('<GAVBroadcastFlag>0','<GAVBroadcastFlag>1')):
            with self.subTest(changed=changed[:30]),self.assertRaises(UnitTemplateError):UnitTemplate.from_xml(changed)

    def test_strict_shape_bounds_and_duplicate_checks(self):
        text=self.templates.from_values(self.current).to_xml()
        for changed in ('x',text.replace('<UnitTemplate>','<UnitTemplate extra="x">'),text.replace('<UnitTemplate>','<UnitTemplate><!--comment-->'),
                        text.replace('<UnitTemplate>','<?other <UnitType>KEY2</UnitType>?><UnitTemplate>'),
                        text.replace('</UnitTemplate>','<Other>3</Other></UnitTemplate>'),
                        text.replace('<CRC>14735</CRC>',''),text.replace('<UnitName>NEWUNIT</UnitName>','<UnitName><Nested/></UnitName>'),
                        text.replace('</UnitTemplate>','<CRC>14735</CRC></UnitTemplate>'),
                        text.replace('</UnitTemplate>','<UnitType>KEY4</UnitType></UnitTemplate>'),
                        text.replace('<UnitType>KEY4</UnitType>','<UnitType>KEY2</UnitType>',1),
                        '<!DOCTYPE UnitTemplate []>'+text,'x'*(1024*1024+1)):
            with self.subTest(changed=changed[:30]),self.assertRaises(UnitTemplateError):UnitTemplate.from_xml(changed)
        for description in ('é','multi\nline','x'*4097):
            with self.assertRaises(UnitTemplateError):self.templates.from_values(self.current,description=description)

    def session(self):
        session=Session(self.spec);session.firmware='1.2.67';session.catalog_number='5034N';return session

    def test_apply_exports_only_included_fields_and_preserves_identity(self):
        current=dict(self.current,UnitName='OTHER',JPCommand='13 15 11 0',TimerLowByte='1 2 3 4')
        template=self.templates.from_values(current);session=self.session()
        session.current.update(UnitAddress='0xe7',Project='TARGET',SerialNo='1234',LearnedFlag='1',Other='preserved')
        result=self.templates.apply(session,UnitTemplate.from_xml(template.to_xml()))
        self.assertTrue(result['verified']);self.assertFalse(result['saved']);self.assertFalse(result['device_verified'])
        self.assertEqual(session.current['UnitAddress'],'0xe7');self.assertEqual(session.current['Project'],'TARGET')
        self.assertEqual(session.current['SerialNo'],'1234');self.assertEqual(session.current['Other'],'preserved')
        self.assertEqual(self.templates.export(session).crc,template.crc)
        self.assertEqual(set(result['changed_parameters']),{'UnitName','JPCommand','TimerLowByte'})

    def test_wrong_native_profile_or_schema_rejected_before_write(self):
        template=self.templates.from_values(self.current)
        for field,value in (('unit_type','KEY1'),('firmware','1.2.66'),('catalog_number','OTHER')):
            session=self.session();setattr(session,field,value)
            with self.assertRaisesRegex(UnitTemplateError,'Native session'):self.templates.apply(session,template)
            self.assertEqual(session.calls,[])
        session=self.session();bad=replace(self.spec.get('JPCommand'),fields=dict(self.spec.get('JPCommand').fields,Address='60'))
        session.spec=replace(self.spec,parameters=dict(self.spec.parameters,JPCommand=bad))
        with self.assertRaisesRegex(UnitTemplateError,'layout mismatch'):self.templates.apply(session,template)
        self.assertEqual(session.calls,[])

    def test_invalid_numeric_or_schema_values_fail_before_io(self):
        for change in ({'GroupAddress':'foo'},{'DebounceTime':'64'},{'JPCommand':'1 2'}, {'UnitName':'TOOLONGNAME'},
                       {'UnitName':'lower'},{'UnitName':'A?B'},{'UnitName':'A\nB'}):
            with self.subTest(change=change),self.assertRaises(UnitTemplateError):self.templates.from_values(dict(self.current,**change))
        with self.assertRaises(UnitTemplateError):UnitTemplates(replace(self.spec,filename='KEY2.xml'))

    def test_partial_write_no_retry_save_or_readback(self):
        template=self.templates.from_values(dict(self.current,UnitName='OTHER',JPCommand='13 15 11 0'))
        session=self.session();session.failure='UnitName'
        with self.assertRaises(UnitTemplateApplyError)as error:self.templates.apply(session,template)
        self.assertEqual(error.exception.attempted,('UnitName',));self.assertEqual(session.calls,[('UnitName','OTHER')])
        self.assertFalse(error.exception.details['saved'])


@unittest.skipUnless(os.environ.get('CBUS_TOOLKIT_EXE'),'Set original Toolkit EXE for executable template validation')
class UnitTemplateSourceTest(unittest.TestCase):
    def test_original_constructor_template_flags_order_and_duplicate_header_writes(self):
        import pefile
        pe=pefile.PE(os.environ['CBUS_TOOLKIT_EXE']);base=pe.OPTIONAL_HEADER.ImageBase
        def at(address,size):return pe.get_data(address-base,size)
        # Constructor calls in inheritance order, independently traced from
        # TCBusKeyInputCGateAgent.InternalCreate down to its base class.
        calls=(0xCB52B5,0xCB52F6,0xCB531C,0xCB5342,0xCB5368,0xCB538E,0xCB53B4,0xCB5400,
               0xCC5AC7,0xCC5AED,0xCC5B13,0xCC6491,0xCC64F1,0xCC6D3F,0xCC6D65,0xCC6DA1,
               0xCC6DC7,0xCC72AF,0xCC72D5,0xCC72FB,0xCC7321,0xCC7347,0xCC6DF5,0xCC6E1B,
               0xCC6E41,0xCC6E67,0xCC6E8D,0xCC6EB3,0xCC6ED9,0xCC6EFF,0xCC6F25,
               0xCC719D,0xCC71F5,0xCC724D,0x1215B33)
        included=[];excluded=[]
        for call in calls:
            args=at(call-24,11)
            self.assertEqual((args[0],args[5],args[6],args[7],args[9]),(0x68,0x6a,0,0x6a,0x6a))
            pointer=struct.unpack_from('<I',args,1)[0]
            name=at(pointer,256).decode('utf-16le',errors='ignore').split('\0')[0]
            (included if args[10] else excluded).append(name)
        self.assertEqual(tuple(included),ORDER)
        self.assertEqual(excluded,['Project','SerialNo','State','UnitAddress','LearnedFlag'])
        # Constructor initializes persistent=1 and template flag from last
        # stack arg; SaveTemplate explicitly writes metadata before the loop.
        for address,literal in ((0x7EC579,'8b45fcc6403001'),(0x7EC580,'8b45fc8a550888506c'),
                                (0xCC3C8D,'8b80a4000000'),(0xCC3CA2,'8b808c000000'),
                                (0xCC3D5C,'80786c00'),(0xCBCF43,'ff5264')):
            self.assertEqual(at(address,len(bytes.fromhex(literal))),bytes.fromhex(literal))
        # Original registration binds all three concrete unit classes to the
        # same template-producing agent, independently of the Python registry.
        for call,unit_class in ((0x1397528,0xF70560),(0x1397540,0xF70D74),(0x1397558,0xF71588)):
            self.assertEqual(at(call-12,12),b'\x8b\x0d'+struct.pack('<I',0x1215934)+b'\x8b\x15'+struct.pack('<I',unit_class))

    def test_original_executable_checksum_and_template_reader(self):
        sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'research'))
        from native_template_probe import native_crc,native_read_attribute,native_xml_text
        executable=os.environ['CBUS_TOOLKIT_EXE'];template=UnitTemplates(fixture()).from_values(fixture().defaults())
        payload=''.join(template.attributes[name]for name in ORDER).encode('ascii')
        for data,expected in ((b'',65261),(b'a',65261),(b'ab',4767),(b'123456789',47524),(bytes(range(256)),15498)):
            self.assertEqual(native_crc(executable,data),expected)
        self.assertEqual(native_crc(executable,payload),template.crc)
        for unit_type in ('KEY1','KEY2'):
            spec=fixture(unit_type);other=UnitTemplates(spec).from_values(spec.defaults())
            self.assertEqual(native_crc(executable,''.join(other.attributes[name]for name in ORDER).encode()),other.crc)
            self.assertEqual(native_read_attribute(executable,other.to_xml(),'UnitType'),unit_type)
        for name in ('UnitType','FirmwareVersion','CRC','UnitName','JPCommand','TimerExpiryCommand','GAVBroadcastFlag','Missing'):
            expected=str(template.crc)if name=='CRC'else template.attributes.get(name,'')
            self.assertEqual(native_read_attribute(executable,template.to_xml(),name),expected)
        self.assertEqual(native_read_attribute(executable,template.to_xml().replace('<UnitType>KEY4</UnitType>','<UnitType>FIRST</UnitType>',1),'UnitType'),'FIRST')
        special='A<&"B'
        self.assertEqual(native_xml_text(executable,special),'A&lt;&amp;&quot;B')
        self.assertEqual(native_xml_text(executable,'A&lt;&amp;&quot;B',decode=True),special)
        self.assertEqual(native_xml_text(executable,'&apos;&gt;&amp;lt;',decode=True),"'>&lt;")
        special_template=UnitTemplates(fixture()).from_values(dict(fixture().defaults(),UnitName=special))
        self.assertEqual(native_xml_text(executable,native_read_attribute(executable,special_template.to_xml(),'UnitName'),decode=True),special)
        fields=dict(template.attributes,Application='56  255')
        self.assertEqual(native_crc(executable,''.join(fields[name]for name in ORDER).encode()),template_crc(fields))


@unittest.skipUnless(os.environ.get('CBUS_CGATE_TEST_HOST')and os.environ.get('CBUS_UNITSPEC_DIR'),'Set native C-Gate and unit specifications')
class UnitTemplateNativeTest(unittest.TestCase):
    def test_closed_native_pp_template_roundtrip_preserves_destination_identity(self):
        report={'format':'cbus-unit-template-acceptance-v2','profiles':[],
                'scope':'Original Toolkit XML structure/reader/checksum plus native PP closed database transfer; no GUI process or physical device',
                'passed':False}
        try:
            for unit_type,firmware,catalog,spec in (('KEY1','1.2.67','5031N','KEY1.xml'),('KEY2','1.2.67','5032N','KEY2.xml'),('KEY4','1.2.67','5034N','KEY4.xml')):
                row={'profile':{'unit_type':unit_type,'firmware':firmware,'catalog_number':catalog,'spec':spec},
                     'parameters_roundtripped':0,'raw_bytes_compared':0,'save_reload_cases':0,
                     'xml_special_characters_in_unit_name':True,'passed':False}
                report['profiles'].append(row)
                with self.subTest(unit_type=unit_type):self._run_profile(row)
            report['passed']=all(row['passed']for row in report['profiles'])
        finally:
            for key in ('parameters_roundtripped','raw_bytes_compared','save_reload_cases'):
                report[key]=sum(row[key]for row in report['profiles'])
            if os.environ.get('CBUS_UNIT_TEMPLATE_REPORT'):Path(os.environ['CBUS_UNIT_TEMPLATE_REPORT']).write_text(json.dumps(report,indent=2)+'\n')

    def _run_profile(self,report):
        from cbus_toolkit.cgate import CGateClient
        from cbus_toolkit.native import NativeDatabase
        from cbus_toolkit.programming import Programmer
        project='UT'+uuid4().hex[:6].upper();network=f'//{project}/254';source=network+'/p/230';target=network+'/p/231'
        profile=report['profile'];unit_type=profile['unit_type'];firmware=profile['firmware'];catalog=profile['catalog_number']
        templates=UnitTemplates(UnitSpecStore(os.environ['CBUS_UNITSPEC_DIR']).load(profile['spec']))
        with CGateClient(os.environ['CBUS_CGATE_TEST_HOST'],int(os.environ.get('CBUS_CGATE_TEST_PORT','20023')),timeout=30)as client:
            report['greeting']=client.greeting;client.command('PROJECT NEW '+project)
            try:
                client.command('PROJECT USE '+project);client.command('DBCREATENET 254 Template_Offline Cni 127.0.0.1:29999')
                client.command('NET LOAD DB '+project);client.command('PROJECT SAVE '+project)
                database=NativeDatabase(client)
                database.create_unit(network,230,'Template_Source',unit_type,firmware,catalog_number=catalog)
                database.create_unit(network,231,'Template_Target',unit_type,firmware,catalog_number=catalog)
                programmer=Programmer(client)
                with programmer.load(network,'/db'+source)as session:
                    for name,value in (('UnitName','A<&"B'),('GroupAddress','12 24 25 27 255 255 255 255'),
                                       ('JPCommand','13 15 11 0'),('SRCommand','0 0 0 11'),('LPCommand','0 0 0 2'),
                                       ('LRCommand','0 0 0 14'),('TimerHighByte','1 2 3 4'),('TimerLowByte','4 3 2 1'),
                                       ('LightLevelStore1','64 127 200 255')):session.set(name,value)
                    template=templates.export(session,description=unit_type+' native acceptance')
                    document=template.to_xml();parsed=UnitTemplate.from_xml(document)
                with programmer.load(network,'/db'+target)as session:
                    before=session.values();identity={name:before[name]for name in ('UnitAddress','Project','NetworkAddress','CUSTYPE','PatchEnable','LearnedFlag')}
                    result=templates.apply(session,parsed);self.assertTrue(result['verified'])
                    after=session.values()
                    self.assertEqual({name:after[name]for name in identity},identity)
                    self.assertEqual(templates.export(session).crc,template.crc)
                    raw=lambda address,count:bytes.fromhex(session.get_raw_data(address,count).lines[-1].split('RawData=',1)[1])
                    for address,expected in ((50,bytes.fromhex('d000f000b0000b2e')),(68,bytes((1,2,3,4,4,3,2,1))),
                                             (80,bytes((12,24,25,27,255,255,255,255))),(17,bytes((64,127,200,255)))):
                        self.assertEqual(raw(address,len(expected)),expected);report['raw_bytes_compared']+=len(expected)
                    session.save_to_source();expected=templates.export(session).attributes
                    report['parameters_roundtripped']=len(PARAMETERS)
                client.command('PROJECT SAVE '+project)
                with programmer.load(network,'/db'+target)as session:
                    self.assertEqual(templates.export(session).attributes,expected)
                    self.assertEqual({name:session.values()[name]for name in identity},identity)
                    report['save_reload_cases']=1
                report.update(passed=True,crc=template.crc)
            finally:
                client.command('PROJECT CLOSE '+project);client.command('PROJECT DELETE '+project)


if __name__=='__main__':unittest.main()
