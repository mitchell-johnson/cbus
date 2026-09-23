import java.io.File;
import java.lang.reflect.Field;
import java.lang.reflect.Method;
import java.util.Vector;

/** Invoke the user's unmodified native scene parser and serializer.
 * This is an offline differential oracle, not a replacement server entrypoint.
 */
public final class NativeSceneFileProbe {
    private static Object field(Object value, String name) throws Exception {
        Field field = value.getClass().getDeclaredField(name);
        field.setAccessible(true);
        return field.get(value);
    }
    public static void main(String[] arguments) throws Exception {
        if (arguments.length != 1) throw new IllegalArgumentException("One scene file required");
        File file = new File(arguments[0]);
        AY sceneSet = new AY(file.getParentFile());
        AU scene = new AU(sceneSet, file.getName());
        scene.a(file);
        for (Object action : (Vector<?>) field(scene, "i")) {
            int operation = (Integer) field(action, "c");
            int level = operation == 1 ? 255 : operation == 2 ? 0 : (Integer) field(action, "d");
            int time = (Integer) field(action, "e");
            System.out.println("ACTION\t" + field(action, "a") + "\t" + level + "\t" + time);
        }
        // Native serializer writes the recorder's format. No groups, device
        // connections, or server command ports are opened by this harness.
        Method write = AU.class.getDeclaredMethod("h");
        write.setAccessible(true);
        write.invoke(scene);
    }
}
