import com.clipsal.cgate.cbus.pp.unitspec.Param;
import java.net.InetAddress;
import java.net.InetSocketAddress;
import java.net.Socket;
import java.net.SocketException;
import java.nio.charset.StandardCharsets;
import java.util.ArrayList;
import java.util.Base64;

/**
 * Exercise the original C-Gate encoder for two layouts that exist only in the
 * vendor's internal I_DLTF fragment.  No command service or network sender is
 * constructed.  The parent runner supplies a listening witness that this
 * process must be unable to reach under its network-denied sandbox.
 */
public final class NativeMemoryFragmentProbe {
    private static int[] seed(int value, int count) {
        int[] result = new int[count];
        for (int index = 0; index < count; index++) result[index] = value;
        return result;
    }

    private static String b64(String value) {
        return Base64.getEncoder().encodeToString(value.getBytes(StandardCharsets.UTF_8));
    }

    private static void witness(String value) throws Exception {
        try (Socket socket = new Socket()) {
            socket.connect(new InetSocketAddress(
                InetAddress.getByAddress(new byte[]{127, 0, 0, 1}),
                Integer.parseInt(value)), 1000);
            throw new IllegalStateException("Network sandbox failed: owned witness connected");
        } catch (SocketException error) {
            String message = error.getMessage();
            if (!"Operation not permitted".equals(message)
                    && !"Permission denied".equals(message)
                    && !"Operation not permitted (connect failed)".equals(message)) {
                throw error;
            }
            System.out.println("WITNESS\t" + error.getClass().getName() + "\t" + b64(message));
        }
    }

    private static String field(String value) {
        return value == null ? "" : value;
    }

    public static void main(String[] args) throws Exception {
        if (args.length != 1) throw new IllegalArgumentException("Owned witness port required");
        witness(args[0]);

        md specification = new md("I_DLTF.xml");
        specification.a();
        lP session = new lP("memory-fragment-probe", "memory-fragment-lock", "owned");
        session.c = specification;
        session.c();

        String[] names = {"LabelFlavourLSB", "LabelFlavourMSB"};
        String[] values = {"1 0 1 0 1 0 1 0", "0 1 0 1 0 1 0 1"};
        int[] seeds = {0xA5, 0x5A};
        int cases = 0;
        for (String name : names) {
            Param parameter = specification.a(name);
            if (parameter == null) {
                throw new IllegalStateException("Missing original parameter " + name);
            }
            System.out.println("LAYOUT\t" + name + "\t" + field(parameter.getType()) + "\t"
                + field(parameter.getAddress()) + "\t" + field(parameter.getArraySize()) + "\t"
                + field(parameter.getBitSize()) + "\t" + field(parameter.getBitAddress()) + "\t"
                + field(parameter.getArraySkip()) + "\t" + field(parameter.getEndian()));
            for (int trial = 0; trial < seeds.length; trial++) {
                session.a(0x60, seed(seeds[trial], 8));
                session.a(name, values[trial], new ArrayList<String>());
                String raw = session.a(0x60, 8);
                String decoded = session.a(parameter, 0, new ArrayList<String>());
                System.out.println("CASE\t" + name + "\t" + trial + "\t" + seeds[trial] + "\t"
                    + values[trial] + "\t" + raw + "\t" + decoded);
                cases++;
            }
        }
        System.out.println("COMPLETE\t2\t" + cases
            + "\toriginal_encoder_invoked=true\tcommand_service_started=false\tphysical_io=false");
    }
}
