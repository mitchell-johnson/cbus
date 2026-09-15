import java.io.*;
import java.lang.reflect.*;
import java.nio.charset.StandardCharsets;
import java.nio.file.*;
import java.security.Permission;
import java.util.*;
import sun.misc.Unsafe;

/** Constructor-bypassed cache fixture; original cj methods remain unchanged. */
public final class NativeIncomingRouteProbe {
  private static Unsafe unsafe;
  private static Class<?> networkClass, baseNetworkClass, unitClass, bridgeClass, dlClass, messageClass;
  private static Field cacheField, bridgeLink;
  private static Constructor<?> constructor, overload;
  private static Method privateCRC, publicCRC;
  private static final Base64.Decoder DECODER = Base64.getDecoder();
  private static final IdentityHashMap<Object,String> labels = new IdentityHashMap<>();
  private static final class Guard extends SecurityManager {
    private final Path owned;
    Guard(Path owned) throws IOException { this.owned=owned.toRealPath(); }
    @Override public void checkPermission(Permission permission) { }
    @Override public void checkConnect(String host,int port) { throw new SecurityException("Owned probe forbids network connect"); }
    @Override public void checkListen(int port) { throw new SecurityException("Owned probe forbids network listen"); }
    @Override public void checkAccept(String host,int port) { throw new SecurityException("Owned probe forbids network accept"); }
    @Override public void checkExec(String command) { throw new SecurityException("Owned probe forbids child execution"); }
    @Override public void checkWrite(String file) {
      Path requested=Paths.get(file).toAbsolutePath().normalize(), ancestor=requested;
      if(!requested.startsWith(owned))throw new SecurityException("Owned probe forbids external file write");
      try {
        while(!Files.exists(ancestor,LinkOption.NOFOLLOW_LINKS))ancestor=ancestor.getParent();
        Path resolved=ancestor.toRealPath().resolve(ancestor.relativize(requested)).normalize();
        if(!resolved.startsWith(owned))throw new SecurityException("Owned probe forbids linked external file write");
      } catch(IOException error) { throw new SecurityException("Owned probe could not verify write path",error); }
    }
    @Override public void checkDelete(String file) { checkWrite(file); }
  }
  private static String quote(String value) {
    if(value==null) return "null";
    StringBuilder out=new StringBuilder("\"");
    for(char c:value.toCharArray()) {
      if(c=='"'||c=='\\') out.append('\\').append(c);
      else if(c<32||c>126) out.append(String.format(Locale.ROOT,"\\u%04x",(int)c));
      else out.append(c);
    }
    return out.append('"').toString();
  }
  private static String json(Object value) {
    if(value==null) return "null";
    if(value instanceof String) return quote((String)value);
    if(value instanceof Number || value instanceof Boolean) return value.toString();
    if(value instanceof Map) {
      StringJoiner out=new StringJoiner(",","{","}");
      for(Object item:((Map<?,?>)value).entrySet()) {
        Map.Entry<?,?> row=(Map.Entry<?,?>)item; out.add(quote((String)row.getKey())+":"+json(row.getValue()));
      }
      return out.toString();
    }
    if(value instanceof Iterable) {
      StringJoiner out=new StringJoiner(",","[","]"); for(Object item:(Iterable<?>)value)out.add(json(item));return out.toString();
    }
    throw new IllegalArgumentException("Unknown JSON value "+value.getClass().getName());
  }
  private static Throwable actual(Throwable error) { return error instanceof InvocationTargetException ? ((InvocationTargetException)error).getCause() : error; }
  private static Map<String,Object> failure(Throwable error) {
    error=actual(error); Map<String,Object> out=new LinkedHashMap<>();
    out.put("class",error.getClass().getName());out.put("message",error.getMessage());return out;
  }
  private static Object allocate(Class<?> type,String label) throws Exception {
    Object value=unsafe.allocateInstance(type);labels.put(value,label);return value;
  }
  private static Object view(Object value) {
    if(value==null||value instanceof String||value instanceof Number||value instanceof Boolean) return value;
    if(labels.containsKey(value)) return labels.get(value);
    if(value.getClass().isArray()) {
      List<Object> result=new ArrayList<>();for(int i=0;i<Array.getLength(value);i++)result.add(view(Array.get(value,i)));return result;
    }
    return value.getClass().getName()+"#unlabelled";
  }
  private static Map<String,Object> fields(Object value) throws Exception {
    Map<String,Object> out=new TreeMap<>();
    for(Class<?> type=value.getClass();type!=Object.class;type=type.getSuperclass()) {
      for(Field field:type.getDeclaredFields()) {
        if(Modifier.isStatic(field.getModifiers()))continue;
        field.setAccessible(true);out.put(type.getName()+"."+field.getName(),view(field.get(value)));
      }
    }
    return out;
  }
  private static Map<String,Object> fixtureState(Object[] networks,List<Object> units) throws Exception {
    Map<String,Object> result=new LinkedHashMap<>();
    for(Object network:networks)result.put(labels.get(network),fields(network));
    for(Object unit:units)result.put(labels.get(unit),fields(unit));
    return result;
  }
  private static Map<String,Object> run(String[] input) throws Exception {
    if(input.length!=7) throw new IllegalArgumentException("Expected seven columns");
    String id=input[0], raw=input[1].equals("-")?null:new String(DECODER.decode(input[1]),StandardCharsets.UTF_8);
    if(raw!=null && raw.length()>2048)throw new IllegalArgumentException("Oversize fixture");
    int derived=raw==null?0:(raw.length()-4)/2;
    int count=input[5].equals("derived")?derived:Integer.parseInt(input[5]);
    if(input[6].equals("h") && count!=derived)throw new IllegalArgumentException("Public CRC requires the exact derived count before fixture construction");
    labels.clear(); Object[] networks=new Object[7]; List<Object> units=new ArrayList<>();
    for(int i=0;i<7;i++) { networks[i]=allocate(networkClass,"N"+i);cacheField.set(networks[i],Array.newInstance(unitClass,256)); }
    if(!input[2].equals("-"))for(String item:input[2].split(";")) {
      String[] pair=item.split("=",-1), key=pair[0].split(":",-1);
      int net=Integer.parseInt(key[0]),address=Integer.parseInt(key[1]);
      if(net<0||net>6||address<0||address>255)throw new IllegalArgumentException("Bad fixture cache key");
      Object unit;
      if(pair[1].equals("W"))unit=allocate(unitClass,"N"+net+":"+address+"/plain");
      else if(pair[1].equals("D"))unit=allocate(dlClass,"N"+net+":"+address+"/dl");
      else if(pair[1].matches("B[0-6N]")) {
        unit=allocate(bridgeClass,"N"+net+":"+address+"/bridge");
        bridgeLink.set(unit,pair[1].equals("BN")?null:networks[Integer.parseInt(pair[1].substring(1))]);
      } else throw new IllegalArgumentException("Bad fixture kind");
      Object cache=cacheField.get(networks[net]);
      if(Array.get(cache,address)!=null)throw new IllegalArgumentException("Duplicate fixture key");
      Array.set(cache,address,unit);units.add(unit);
    }
    Map<String,Object> before=fixtureState(networks,units), result=new LinkedHashMap<>();
    result.put("id",id);result.put("raw",raw);result.put("fixture",input[2]);result.put("root_context",input[3]);
    Object root=input[3].equals("null")?null:networks[Integer.parseInt(input[3])];
    Object message=null;
    try {
      if(input[4].equals("plain"))message=constructor.newInstance(raw,root,null);
      else if(input[4].equals("true")||input[4].equals("false"))message=overload.newInstance(raw,root,Boolean.parseBoolean(input[4]),null);
      else throw new IllegalArgumentException("Bad constructor selector");
      result.put("constructor_complete",true);result.put("fields",fields(message));
    } catch(InvocationTargetException error) { result.put("constructor_complete",false);result.put("constructor_error",failure(error)); }
    result.put("crc_count_argument",count);
    boolean privateValid=false;
    try { privateCRC.invoke(null,raw,count);privateValid=true;result.put("private_crc_complete",true); }
    catch(InvocationTargetException error){result.put("private_crc_complete",false);result.put("private_crc_error",failure(error));}
    if(input[6].equals("h")) {
      if(message==null||!privateValid)throw new IllegalStateException("Refusing public CRC logging path");
      Map<String,Object> old=fields(message);
      result.put("public_crc",publicCRC.invoke(message));
      result.put("public_crc_fields_unchanged",old.equals(fields(message)));
    } else if(!input[6].equals("-"))throw new IllegalArgumentException("Bad CRC selector");
    Map<String,Object> after=fixtureState(networks,units);
    result.put("cache_and_objects_unchanged",before.equals(after));
    if(!before.equals(after))throw new IllegalStateException("Original mutated fixture");
    return result;
  }
  public static void main(String[] args) throws Exception {
    if(args.length!=2)throw new IllegalArgumentException("Input TSV and owned root required");
    Path owned=Paths.get(args[1]).toAbsolutePath().normalize();
    System.setSecurityManager(new Guard(owned));
    Field singleton=Unsafe.class.getDeclaredField("theUnsafe");singleton.setAccessible(true);unsafe=(Unsafe)singleton.get(null);
    baseNetworkClass=Class.forName("com.clipsal.cgate.cbus.core.CBusBaseNetwork");
    networkClass=Class.forName("com.clipsal.cgate.cbus.core.CBusNetwork");
    unitClass=Class.forName("com.clipsal.cgate.cbus.core.CBusUnit");
    bridgeClass=Class.forName("com.clipsal.cgate.cbus.dev.CBus1Bridge");
    dlClass=Class.forName("com.clipsal.cgate.cbus.dev.CBusOEMUnit");
    messageClass=Class.forName("cj");
    cacheField=baseNetworkClass.getDeclaredField("d");cacheField.setAccessible(true);
    bridgeLink=bridgeClass.getDeclaredField("V");bridgeLink.setAccessible(true);
    constructor=messageClass.getConstructor(String.class,baseNetworkClass,Class.forName("[LBW;"));
    overload=messageClass.getConstructor(String.class,baseNetworkClass,boolean.class,Class.forName("[LBW;"));
    privateCRC=messageClass.getDeclaredMethod("a",String.class,int.class);privateCRC.setAccessible(true);
    publicCRC=messageClass.getMethod("h");
    Map<String,Object> meta=new LinkedHashMap<>();meta.put("kind","runtime");meta.put("java",System.getProperty("java.version"));
    meta.put("arch",System.getProperty("os.arch"));meta.put("fixture_constructors_bypassed",true);meta.put("original_receiver_sender_invoked",false);
    meta.put("network_security_manager",true);System.out.println(json(meta));
    int cases=0;
    try(BufferedReader reader=Files.newBufferedReader(Paths.get(args[0]),StandardCharsets.UTF_8)) {
      String line;while((line=reader.readLine())!=null) {
        if(++cases>2048)throw new IllegalArgumentException("Case count bound");
        if(line.length()>8192)throw new IllegalArgumentException("Line bound");
        System.out.println(json(run(line.split("\t",-1))));
      }
    }
    System.out.println("{\"kind\":\"complete\",\"cases\":"+cases+"}");
  }
}
