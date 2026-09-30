"""Capture a synthetic database-only quick-zone initialization candidate.

This proves native PP storage/reload only, not original form initialization or
quick-zone action admission. Uses a temporary owned C-Gate and a closed-network
connection sentinel. Requires CBUS_CGATE_JAVA and CBUS_LOCAL_CGATE_VENDOR.
"""
import argparse, hashlib, json, os, socket
from pathlib import Path
from uuid import uuid4
from research.local_cgate import LocalCGate
from cbus_toolkit.cgate import CGateClient
from cbus_toolkit.native import NativeDatabase, NativeProjects
from cbus_toolkit.programming import Programmer, xml_text
parser=argparse.ArgumentParser(description=__doc__)
parser.add_argument('--output',type=Path,required=True)
args=parser.parse_args()
receipt=Path(__file__).resolve().parent/'experiments/2026-09-30/thermostat-quick-zone-initialization-static.json'
evidence=json.loads(receipt.read_text())
seed={k:v for k,v in evidence['graph_seed'].items() if type(v) is int and not k.startswith('all_')}
seed.update({n:v['raw_pp_byte'] for n,v in evidence['celsius_temperature_fixed_point_seed'].items()})
seed.update(ApplicationNumber=56,RemoteScheduleEnable=0,DisplayBacklightActiveBrightness=201,KeyBacklightActiveBrightness=201,RemoteSetbackOnGroup=30,RemoteSetbackOffGroup=31,RemoteScheduleOnGroup=32,RemoteScheduleOffGroup=33,RemoteScheduleOverrideGroup=34,MasterNetworkAddress=254,InstalledZones=3,ControlledZones=3,HeatingPlantType=0,CoolingPlantType=0,VentingPlantType=0,ZoneGroup=255)
for name in ('UIAllocatedZones','InternalPlantZones','MeasuredZones','HeatingPlantInstalledZones','CoolingPlantInstalledZones','VentingPlantInstalledZones','ScheduleControlledZones'):seed[name]=1
for name in ('CoolActivation','CoolStage1','CoolStage2','CoolStage3','CoolFanLow','CoolFanMedium','CoolFanHigh','HeatActivation','HeatStage1','HeatStage2','HeatStage3','HeatFanLow','HeatFanMedium','HeatFanHigh','DamperZone1','DamperZone2','DamperZone3','DamperZone4'):seed[name+'Output']=255
for i in range(1,6):seed[f'InternalRelay{i}GroupNumber']=255
service=LocalCGate(os.environ['CBUS_LOCAL_CGATE_VENDOR'])
sentinel=socket.socket();sentinel.bind(('127.0.0.1',0));sentinel.listen(1);sentinel.settimeout(.05)
(service.work/'config/access.txt').write_text('interface 127.0.0.1 Clipsal\n')
report={'format':'synthetic-thermostat-quick-zone-raw-seed-v1','original_form_executed':False,'physical_devices_accessed':False,'service':service.report,'toolkit_context':{'temperature_preference':'celsius','database_unit':True,'fresh_model':True}}
try:
 service.start()
 with CGateClient('127.0.0.1',service.port,timeout=30) as client:
  projects=NativeProjects(client);db=NativeDatabase(client);name='Q'+uuid4().hex[:7].upper();projects.operation('new',name)
  network='//'+name+'/254';unit=network+'/p/20'
  db.create_network(name,254,'SyntheticQuickZone','Cni','127.0.0.1:'+str(sentinel.getsockname()[1]))
  for address,tag in ((56,'Synthetic Output'),(115,'HVAC Actuator 1'),(116,'HVAC Actuator 2'),(172,'Synthetic AC'),(203,'Enable')):db.add(network,'application',address,tag)
  for app in (56,172,203):db.add(network+'/'+str(app),'group',255,'<Unused>')
  db.create_unit(network,20,'SyntheticThermostat','PC_TSA','5.4.01',catalog_number='5070THP,BK')
  with Programmer(client).load(network,'/db'+unit) as session:
   defaults=session.values()
   assert session.set('Application','56 255').code==200
   for key,value in seed.items():
    assert session.set(key,str(value)).code==200,key
   session.save_to_source()
  for action in ('save','close','load'):projects.operation(action,name)
  with Programmer(client).load(network,'/db'+unit) as session:report['pp']=session.values()
  report.update(seed=seed,default_pp=defaults,project_xml=xml_text(db.get('//'+name,xml=True)),unit_type='PC_TSA')
 try:
  connection,peer=sentinel.accept();connection.close();raise AssertionError('Unexpected CNI connection '+repr(peer))
 except socket.timeout:report['cni_connections']=[]
finally:
 service.close();sentinel.close()
report['checker_sha256']=hashlib.sha256(Path(__file__).read_bytes()).hexdigest()
report['initialization_receipt_sha256']=hashlib.sha256(receipt.read_bytes()).hexdigest()
with args.output.open('x') as output:output.write(json.dumps(report,indent=2,sort_keys=True)+'\n')
print(json.dumps({'parameters':len(report['pp']),'seed_parameters':len(seed),'cleanup_complete':report['service'].get('cleanup_complete'),'cni_connections':report.get('cni_connections')}))
