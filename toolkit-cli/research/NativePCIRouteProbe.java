import java.io.BufferedReader;
import java.io.InputStreamReader;
import java.lang.reflect.Field;
import java.lang.reflect.Modifier;
import java.net.InetAddress;
import java.net.InetSocketAddress;
import java.net.Socket;
import java.net.SocketException;
import java.nio.charset.StandardCharsets;
import java.util.Base64;
import java.util.LinkedHashMap;
import java.util.Map;

/** Owned fixture: only original cq/aW constructors, field setter/getter,
 * route prepend and checksum utility. No sender/network method is invoked. */
public final class NativePCIRouteProbe {
    private static String b64(String value) {
        return Base64.getEncoder().encodeToString(value.getBytes(StandardCharsets.UTF_8));
    }
    private static Map<Field,Object> fields(aW command) throws Exception {
        Map<Field,Object> result = new LinkedHashMap<>();
        for (Field field : aW.class.getDeclaredFields()) {
            if (Modifier.isStatic(field.getModifiers())) continue;
            field.setAccessible(true);
            result.put(field, field.get(command));
        }
        return result;
    }
    private static void unchanged(Map<Field,Object> before, aW command) throws Exception {
        for (Map.Entry<Field,Object> row : before.entrySet()) {
            if (row.getKey().getName().equals("e")) continue;
            Object after = row.getKey().get(command), value = row.getValue();
            if (row.getKey().getType().isPrimitive() ? !value.equals(after) : value != after)
                throw new IllegalStateException("Unexpected original mutation: " + row.getKey().getName());
        }
    }
    public static void main(String[] args) throws Exception {
        if (args.length != 1) throw new IllegalArgumentException("Owned denied-network witness port required");
        try (Socket witness = new Socket()) {
            try {
                witness.connect(new InetSocketAddress(InetAddress.getByAddress(new byte[]{127,0,0,1}),
                                                       Integer.parseInt(args[0])), 1000);
                throw new IllegalStateException("Network sandbox failed: owned witness connected");
            } catch (SocketException error) {
                String message = error.getMessage();
                if (!"Operation not permitted".equals(message) && !"Permission denied".equals(message) &&
                    !"Operation not permitted (connect failed)".equals(message)) throw error;
                System.out.println("WITNESS\t" + error.getClass().getName() + "\t" + b64(message));
            }
        }
        BufferedReader input = new BufferedReader(new InputStreamReader(System.in, StandardCharsets.US_ASCII));
        int count = 0, operations = 0;
        String line;
        while ((line = input.readLine()) != null) {
            String[] cols = line.split("\t", -1);
            if (cols.length != 3 || !cols[0].matches("[a-z0-9-]{1,80}"))
                throw new IllegalArgumentException("Invalid owned fixture row");
            cq command = new cq(null);
            if (command.e != null || command.f != null || command.h != null || command.g != null ||
                command.d != null || command.m != null)
                throw new IllegalStateException("Unexpected original constructor network or command state");
            String seed = new String(Base64.getDecoder().decode(cols[1]), StandardCharsets.US_ASCII);
            command.k(seed);
            if (!seed.equals(command.l())) throw new IllegalStateException("Original setter/getter mismatch");
            System.out.println("SEED\t" + cols[0] + "\t" + b64(command.l()));
            if (!cols[2].isEmpty()) {
                int step = 0;
                for (String item : cols[2].split(",", -1)) {
                    String before = command.l(), status;
                    Map<Field,Object> snapshot = fields(command);
                    try { status = Boolean.toString(command.k(Integer.parseInt(item))); }
                    catch (RuntimeException error) { status = error.getClass().getName(); }
                    unchanged(snapshot, command);
                    String after = command.l();
                    String checksum = "";
                    if (after.matches("\\\\[0-9A-Fa-f]+") && (after.length() & 1) == 1)
                        checksum = aW.f(after.substring(1));
                    System.out.println("STEP\t" + cols[0] + "\t" + step++ + "\t" + status + "\t" +
                                       b64(before) + "\t" + b64(after) + "\t" + checksum);
                    operations++;
                }
            }
            count++;
        }
        System.out.println("COMPLETE\t" + count + "\t" + operations + "\toriginal_send_methods_invoked=false");
    }
}
