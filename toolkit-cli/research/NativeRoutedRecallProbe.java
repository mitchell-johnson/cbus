import java.io.*;
import java.lang.reflect.*;
import java.nio.charset.StandardCharsets;
import java.nio.file.*;
import java.security.Permission;
import java.util.*;
import sun.misc.Unsafe;
import com.clipsal.cgate.cbus.core.CBusBaseNetwork;

/** Owned constructed-cache fixture. No sender, receiver or network dispatch. */
public final class NativeRoutedRecallProbe {
  private static Unsafe unsafe;
  private static Class<?> networkClass,unitClass,bridgeClass,dlClass;
  private static Field cacheField,bridgeLink,tFlag;
  private static Method privateCRC;
  private static final IdentityHashMap<Object,String> labels=new IdentityHashMap<>();
  private static int autoLabel;
  private static final class Guard extends SecurityManager {
    private final Path owned;
    Guard(Path root)throws IOException{owned=root.toRealPath();}
    @Override public void checkPermission(Permission p){}
    @Override public void checkConnect(String h,int p){throw new SecurityException("Network connect forbidden");}
    @Override public void checkListen(int p){throw new SecurityException("Network listen forbidden");}
    @Override public void checkAccept(String h,int p){throw new SecurityException("Network accept forbidden");}
    @Override public void checkExec(String c){throw new SecurityException("Child execution forbidden");}
    @Override public void checkWrite(String file){
      Path requested=Paths.get(file).toAbsolutePath().normalize(),ancestor=requested;
      if(!requested.startsWith(owned))throw new SecurityException("External write forbidden");
      try{
        while(!Files.exists(ancestor,LinkOption.NOFOLLOW_LINKS))ancestor=ancestor.getParent();
        if(!ancestor.toRealPath().resolve(ancestor.relativize(requested)).normalize().startsWith(owned))
          throw new SecurityException("Linked external write forbidden");
      }catch(IOException e){throw new SecurityException("Write path not verified",e);}
    }
    @Override public void checkDelete(String f){checkWrite(f);}
  }
  private static String quote(String s){
    if(s==null)return "null";
    StringBuilder b=new StringBuilder("\"");
    for(char c:s.toCharArray()){
      if(c=='"'||c=='\\')b.append('\\').append(c);
      else if(c<32||c>126)b.append(String.format(Locale.ROOT,"\\u%04x",(int)c));else b.append(c);
    }
    return b.append('"').toString();
  }
  private static String json(Object value){
    if(value==null)return "null";
    if(value instanceof String)return quote((String)value);
    if(value instanceof Number||value instanceof Boolean)return value.toString();
    if(value instanceof Map){StringJoiner b=new StringJoiner(",","{","}");
      for(Map.Entry<?,?> row:((Map<?,?>)value).entrySet())b.add(quote((String)row.getKey())+":"+json(row.getValue()));return b.toString();}
    if(value instanceof Iterable){StringJoiner b=new StringJoiner(",","[","]");for(Object v:(Iterable<?>)value)b.add(json(v));return b.toString();}
    throw new IllegalArgumentException("Unsupported JSON object");
  }
  private static Map<String,Object> map(Object... pairs){
    Map<String,Object> result=new LinkedHashMap<>();for(int i=0;i<pairs.length;i+=2)result.put((String)pairs[i],pairs[i+1]);return result;
  }
  private static String label(Object v){
    if(v==null)return null;
    if(!labels.containsKey(v))labels.put(v,v.getClass().getName()+"#"+(autoLabel++));return labels.get(v);
  }
  private static Object view(Object v){
    if(v==null||v instanceof String||v instanceof Number||v instanceof Boolean)return v;
    if(v instanceof Character)return (int)(Character)v;
    if(v.getClass().isArray()){
      List<Object> items=new ArrayList<>();for(int i=0;i<Array.getLength(v);i++)items.add(view(Array.get(v,i)));
      return map("identity",label(v),"items",items);
    }
    return label(v);
  }
  private static Map<String,Object> fields(Object obj)throws Exception{
    Map<String,Object> result=new TreeMap<>();
    for(Class<?> c=obj.getClass();c!=Object.class;c=c.getSuperclass())for(Field f:c.getDeclaredFields()){
      if(Modifier.isStatic(f.getModifiers()))continue;f.setAccessible(true);result.put(c.getName()+"."+f.getName(),view(f.get(obj)));
    }
    return result;
  }
  private static Map<String,Object> error(Throwable e){
    if(e instanceof InvocationTargetException)e=((InvocationTargetException)e).getCause();
    return map("class",e.getClass().getName(),"message",e.getMessage());
  }
  private static int number(String s,int high){
    if(!s.matches("0|[1-9][0-9]{0,2}"))throw new IllegalArgumentException("Noncanonical unsigned input");
    int n=Integer.parseInt(s);if(n>high)throw new IllegalArgumentException("Out of input range");return n;
  }
  private static boolean bool(String s){if(!s.equals("0")&&!s.equals("1"))throw new IllegalArgumentException("Boolean input");return s.equals("1");}
  private static final class Entry{
    int network,address,destination;char kind;
    Entry(String s){
      if(!s.matches("[0-7]:[0-9]{1,3}=(?:[WD]|B[0-7N])"))throw new IllegalArgumentException("Cache grammar");
      String[] p=s.split("[:=]");network=number(p[0],7);address=number(p[1],255);kind=p[2].charAt(0);
      destination=kind=='B'?(p[2].charAt(1)=='N'?-1:number(p[2].substring(1),7)):-1;
    }
  }
  private static final class Plan{
    String id;int unit,parameter,count,root,context;int[] bridges;boolean needsConfirmation,hashSuccess,active;char tag;
    List<Entry> cache=new ArrayList<>();List<String> raws=new ArrayList<>();List<String> operations=new ArrayList<>();
    Plan(String line){
      if(line.length()>8192)throw new IllegalArgumentException("Line bound");
      String[] p=line.split("\t",-1);if(p.length!=14)throw new IllegalArgumentException("14 columns required");
      id=p[0];if(!id.matches("[a-z0-9-]{1,80}"))throw new IllegalArgumentException("Case id");
      unit=number(p[1],255);parameter=number(p[2],255);count=number(p[3],30);if(count==0)throw new IllegalArgumentException("Positive count required");
      String[] bs=p[4].equals("-")?new String[0]:p[4].split(",",-1);if(bs.length>6)throw new IllegalArgumentException("Bridge bound");
      bridges=new int[bs.length];for(int i=0;i<bs.length;i++)bridges[i]=number(bs[i],255);
      root=number(p[5],7);context=number(p[6],7);
      Set<String> seen=new HashSet<>();
      if(!p[7].equals("-"))for(String item:p[7].split(";",-1)){
        if(cache.size()>=12)throw new IllegalArgumentException("Cache bound");Entry e=new Entry(item);
        if(!seen.add(e.network+":"+e.address))throw new IllegalArgumentException("Duplicate cache key");cache.add(e);
      }
      needsConfirmation=bool(p[8]);hashSuccess=bool(p[9]);active=bool(p[10]);
      if(!p[11].matches("[g-z]"))throw new IllegalArgumentException("Tag grammar");tag=p[11].charAt(0);
      for(String item:p[12].split(",",-1)){
        if(raws.size()>=4||item.length()>2732)throw new IllegalArgumentException("Raw input bound");
        byte[] raw=Base64.getDecoder().decode(item);if(raw.length>2048)throw new IllegalArgumentException("Decoded raw bound");
        for(byte b:raw)if(b<0||b==0)throw new IllegalArgumentException("ASCII/noNUL raw profile");
        raws.add(new String(raw,StandardCharsets.US_ASCII));
      }
      if(!p[13].equals("-"))for(String op:p[13].split(";",-1)){
        if(operations.size()>=12)throw new IllegalArgumentException("Operation bound");
        if(op.matches("R[0-3][LS]")){if(op.charAt(1)-'0'>=raws.size())throw new IllegalArgumentException("Missing raw index");}
        else if(!op.matches("C[g-z][.#$%&'!]"))throw new IllegalArgumentException("Operation grammar");
        operations.add(op);
      }
    }
  }
  private static Object allocate(Class<?> c,String name)throws Exception{Object o=unsafe.allocateInstance(c);labels.put(o,name);return o;}
  private static Map<String,Object> fixture(CBusBaseNetwork[] ns,List<Object> units)throws Exception{
    Map<String,Object> result=new LinkedHashMap<>();
    for(Object n:ns)result.put(label(n),fields(n));for(Object u:units)result.put(label(u),fields(u));return result;
  }
  private static void commandGuard(cg c,CBusBaseNetwork near,CBusBaseNetwork context,cr counter){
    if(c.getClass()!=cg.class||c.o||c.g!=near||c.h!=context||near.T!=counter||c.d!=null||c.m!=null)
      throw new IllegalStateException("Original command escaped bounded fixture flags/references");
  }
  private static Map<String,Object> run(Plan p)throws Exception{
    labels.clear();autoLabel=0;
    CBusBaseNetwork[] networks=new CBusBaseNetwork[8];List<Object> units=new ArrayList<>();
    for(int i=0;i<networks.length;i++){
      networks[i]=(CBusBaseNetwork)allocate(networkClass,"N"+i);
      cacheField.set(networks[i],Array.newInstance(unitClass,256));
    }
    for(Entry e:p.cache){
      Object unit=allocate(e.kind=='W'?unitClass:e.kind=='D'?dlClass:bridgeClass,"N"+e.network+":"+e.address+"/"+e.kind);
      if(e.kind=='B')bridgeLink.set(unit,e.destination<0?null:networks[e.destination]);
      Array.set(cacheField.get(networks[e.network]),e.address,unit);units.add(unit);
    }
    cr counter=new cr();labels.put(counter,"owned-counter");networks[0].T=counter;
    Map<String,Object> fixtureBefore=fixture(networks,units);
    cg command=new cg();labels.put(command,"command");Map<String,Object> constructed=fields(command);
    command.a(p.unit,p.parameter,p.count);command.a(networks[p.context]);command.b(networks[0]);
    command.d(p.needsConfirmation);tFlag.setBoolean(command,p.hashSuccess);command.a(p.active);command.a(p.tag);
    List<Object> prepend=new ArrayList<>();
    for(int address:p.bridges){String before=command.l();boolean accepted=command.k(address);prepend.add(map("address",address,"before",before,"accepted",accepted,"after",command.l()));}
    commandGuard(command,networks[0],networks[p.context],counter);
    Map<String,Object> initial=fields(command);List<cj> messages=new ArrayList<>();List<Object> messageEvidence=new ArrayList<>();
    for(int i=0;i<p.raws.size();i++){
      String raw=p.raws.get(i);cj message=null;Map<String,Object> row=map("raw",raw);
      try{message=new cj(raw,networks[p.root],null);labels.put(message,"message"+i);row.put("constructor_complete",true);row.put("fields",fields(message));}
      catch(RuntimeException e){row.put("constructor_complete",false);row.put("constructor_error",error(e));}
      try{privateCRC.invoke(null,raw,(raw.length()-4)/2);row.put("private_crc_complete",true);}
      catch(InvocationTargetException e){row.put("private_crc_complete",false);row.put("private_crc_error",error(e));}
      messages.add(message);messageEvidence.add(row);
    }
    List<Object> actions=new ArrayList<>();
    for(String op:p.operations){
      commandGuard(command,networks[0],networks[p.context],counter);
      if(op.charAt(0)=='R'&&messages.get(op.charAt(1)-'0')==null)
        throw new IllegalStateException("Harness refuses matcher with failed constructor");
      Map<String,Object> before=fields(command),row=map("operation",op,"before",before,"counter_before",new TreeMap<>(counter.a));
      long start=System.currentTimeMillis();
      try{
        boolean result;
        if(op.charAt(0)=='C')result=command.a(new char[]{op.charAt(1),op.charAt(2)});
        else{cj message=messages.get(op.charAt(1)-'0');result=command.a(message,op.charAt(2)=='L');}
        row.put("completed",true);row.put("result",result);
      }catch(RuntimeException e){row.put("completed",false);row.put("error",error(e));}
      row.put("utc_milliseconds_before",start);row.put("utc_milliseconds_after",System.currentTimeMillis());
      commandGuard(command,networks[0],networks[p.context],counter);
      Map<String,Object> after=fields(command);List<String> changed=new ArrayList<>();
      Set<String> allowed=new HashSet<>(Arrays.asList("aW.F","aW.G","aW.K","aW.M","aW.N","aW.P","aO.b","aW.ah","aW.ai"));
      for(String key:before.keySet())if(!Objects.equals(before.get(key),after.get(key))){
        changed.add(key);if(!allowed.contains(key))throw new IllegalStateException("Unexpected original command mutation: "+key);
      }
      row.put("after",after);row.put("changed_fields",changed);row.put("counter_after",new TreeMap<>(counter.a));actions.add(row);
    }
    boolean unchanged=fixtureBefore.equals(fixture(networks,units));
    if(!unchanged)throw new IllegalStateException("Original mutated cached network/unit fields");
    for(int i=0;i<messages.size();i++)if(messages.get(i)!=null){
      Map<?,?> old=(Map<?,?>)messageEvidence.get(i);if(!old.get("fields").equals(fields(messages.get(i))))throw new IllegalStateException("Original matcher mutated received message");
    }
    return map("id",p.id,"constructor",constructed,"initial",initial,"prepend",prepend,"messages",messageEvidence,
               "actions",actions,"final",fields(command),"counter",new TreeMap<>(counter.a),"fixture_fields_unchanged",unchanged,
               "message_fields_unchanged",true,"final_response_objects",view(command.p()));
  }
  public static void main(String[] args)throws Exception{
    if(args.length!=2)throw new IllegalArgumentException("Input TSV and owned output root required");
    Path root=Paths.get(args[1]).toRealPath(),input=Paths.get(args[0]).toRealPath();
    if(!input.startsWith(root)||!Files.isRegularFile(input)||Files.size(input)>262144)throw new IllegalArgumentException("Owned input file/bound required");
    List<Plan> plans=new ArrayList<>();Set<String> ids=new HashSet<>();
    for(String line:Files.readAllLines(input,StandardCharsets.UTF_8)){
      if(plans.size()>=512)throw new IllegalArgumentException("Case count bound");Plan p=new Plan(line);
      if(!ids.add(p.id))throw new IllegalArgumentException("Duplicate case id");plans.add(p);
    }
    if(plans.isEmpty())throw new IllegalArgumentException("Empty input");
    System.setSecurityManager(new Guard(root));
    Field singleton=Unsafe.class.getDeclaredField("theUnsafe");singleton.setAccessible(true);unsafe=(Unsafe)singleton.get(null);
    networkClass=Class.forName("com.clipsal.cgate.cbus.core.CBusNetwork");unitClass=Class.forName("com.clipsal.cgate.cbus.core.CBusUnit");
    bridgeClass=Class.forName("com.clipsal.cgate.cbus.dev.CBus1Bridge");dlClass=Class.forName("com.clipsal.cgate.cbus.dev.CBusOEMUnit");
    cacheField=CBusBaseNetwork.class.getDeclaredField("d");cacheField.setAccessible(true);bridgeLink=bridgeClass.getDeclaredField("V");bridgeLink.setAccessible(true);
    tFlag=aW.class.getDeclaredField("t");tFlag.setAccessible(true);privateCRC=cj.class.getDeclaredMethod("a",String.class,int.class);privateCRC.setAccessible(true);
    System.out.println(json(map("kind","runtime","java",System.getProperty("java.version"),"arch",System.getProperty("os.arch"),
      "network_constructors_bypassed",true,"original_cg_and_cr_constructors",true,"sender_receiver_dispatch_invoked",false,
      "network_security_manager",true,"preflight_case_count",plans.size())));
    for(Plan p:plans)System.out.println(json(run(p)));
    System.out.println(json(map("kind","complete","cases",plans.size())));
  }
}
