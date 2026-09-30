/* Original C-Gate class invocation only; no vendor implementation is copied. */
import java.util.Arrays;
import java.util.LinkedHashMap;
import java.util.Map;
import java.lang.reflect.Array;
import java.lang.reflect.Method;
import java.nio.file.Paths;
import com.fasterxml.jackson.databind.JsonNode;
import com.fasterxml.jackson.databind.ObjectMapper;
import com.clipsal.cgate.cbus.dali.model.DaliGatewayExtParamMap;
import com.clipsal.cgate.cbus.dali.model.ext.ExtProxy;

public final class NativeDaliExtProxyProbe {
    private static Object read(Object bean, String name) throws Exception {
        if (bean instanceof ExtProxy && name.equals("line")) {
            ExtProxy proxy = (ExtProxy) bean;
            return new Object[]{proxy.getLine(0), proxy.getLine(1)};
        }
        if (bean.getClass().isArray()) return Array.get(bean, Integer.parseInt(name));
        for (Method method : bean.getClass().getMethods()) {
            if (method.getParameterCount() == 0 && method.getName().equalsIgnoreCase("get" + name)) {
                return method.invoke(bean);
            }
        }
        throw new IllegalArgumentException("Unreadable original property " + name);
    }

    private static void edit(ExtProxy proxy, JsonNode edit, ObjectMapper mapper) throws Exception {
        String prefix = "/cdg/extParams/proxy/";
        String path = edit.get("path").asText();
        if (!path.startsWith(prefix)) throw new IllegalArgumentException("Invalid edit prefix");
        String[] parts = path.substring(prefix.length()).split("/");
        Object current = proxy;
        for (int index = 0; index < parts.length - 1; index++) current = read(current, parts[index]);
        String leaf = parts[parts.length - 1];
        if (current.getClass().isArray()) {
            Array.set(current, Integer.parseInt(leaf), edit.get("value").intValue());
            return;
        }
        for (Method method : current.getClass().getMethods()) {
            if (method.getParameterCount() == 1 && method.getName().equalsIgnoreCase("set" + leaf)) {
                Object value = mapper.convertValue(edit.get("value"),
                    mapper.getTypeFactory().constructType(method.getGenericParameterTypes()[0]));
                method.invoke(current, value);
                return;
            }
        }
        throw new IllegalArgumentException("Unwritable original property " + leaf);
    }

    public static void main(String[] args) throws Exception {
        ObjectMapper mapper = new ObjectMapper();
        JsonNode input = mapper.readTree(Paths.get(args[0]).toFile());
        DaliGatewayExtParamMap memory = new DaliGatewayExtParamMap();
        Arrays.fill(memory.values, input.get("default_current_byte").intValue());
        for (java.util.Iterator<Map.Entry<String, JsonNode>> entries = input.get("current_overrides").fields(); entries.hasNext();) {
            Map.Entry<String, JsonNode> entry = entries.next();
            memory.setValue(Integer.parseInt(entry.getKey()), entry.getValue().intValue());
        }
        memory.getProxy().a();
        Map<String, Object> result = new LinkedHashMap<>();
        result.put("model_before", mapper.valueToTree(memory.getProxy()));
        result.put("line_before", mapper.valueToTree(new Object[]{memory.getProxy().getLine(0), memory.getProxy().getLine(1)}));
        for (JsonNode edit : input.get("edits")) edit(memory.getProxy(), edit, mapper);
        result.put("model_staged", mapper.valueToTree(memory.getProxy()));
        result.put("line_staged", mapper.valueToTree(new Object[]{memory.getProxy().getLine(0), memory.getProxy().getLine(1)}));
        memory.getProxy().b();
        Map<String, Integer> targets = new LinkedHashMap<>();
        for (int address = 256; address < 11376; address++) {
            if (memory.getTargetValue(address) >= 0) targets.put(Integer.toString(address), memory.getTargetValue(address));
        }
        result.put("target_bytes", targets);
        memory.c();
        result.put("dirty_chunks", memory.getDirtyWriteChunks());
        System.out.println(mapper.writeValueAsString(result));
    }
}
