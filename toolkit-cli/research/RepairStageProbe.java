import java.io.*;
import java.nio.charset.StandardCharsets;
import java.nio.file.*;
import java.util.Base64;
import com.clipsal.cgate.cmd.Response;

// Runs the unmodified C-Gate repair stages on generated files only.
public final class RepairStageProbe {
  public static void main(String[] args) throws Exception {
    Path work = Paths.get(args[0]);
    Path transforms = Paths.get(args[1]);
    BufferedReader input = new BufferedReader(new InputStreamReader(System.in, StandardCharsets.UTF_8));
    String line;
    int count = 0;
    while ((line = input.readLine()) != null) {
      String[] fields = line.split("\t", -1);
      if (fields.length != 3) throw new IllegalArgumentException("Three fields required");
      String op = fields[0];
      String id = fields[1];
      if (!id.matches("[a-zA-Z0-9_-]+")) throw new IllegalArgumentException("Invalid id");
      Path path = work.resolve("case-" + count++ + ".xml");
      Files.write(path, Base64.getDecoder().decode(fields[2]));
      StringWriter messages = new StringWriter();
      Response response = new Response(messages);
      String status = "OK";
      String error = "";
      try {
        if (op.equals("manual") || op.equals("full")) dD.a(path.toFile());
        if (op.equals("repair") || op.equals("full"))
          dD.a(path.toFile(), transforms.resolve("repair.xslt").toString(), response);
        if (op.equals("tidy") || op.equals("full"))
          dD.a(path.toFile(), transforms.resolve("tidyduplicategroups.xslt").toString(), response);
        if (!op.matches("manual|repair|tidy|full")) throw new IllegalArgumentException("Invalid operation");
      } catch (Throwable caught) {
        status = "ERROR";
        error = caught.getClass().getName() + ": " + caught.getMessage();
      }
      System.out.println("RESULT\t" + id + "\t" + status + "\t" +
        Base64.getEncoder().encodeToString(Files.readAllBytes(path)) + "\t" +
        Base64.getEncoder().encodeToString(error.getBytes(StandardCharsets.UTF_8)) + "\t" +
        Base64.getEncoder().encodeToString(messages.toString().getBytes(StandardCharsets.UTF_8)));
      Files.deleteIfExists(path);
    }
  }
}
