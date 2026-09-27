import java.lang.reflect.Method;
import java.util.Arrays;
public final class CbusKfiDecoderProbe {
 public static void main(String[] args) throws Exception {
  Method decode=Class.forName("kv").getMethod("m",String.class);
  String[] samples={null,"","0000000000000001234567","0000000000000010325476","00000000000000FFFFFFFF"};
  for(int i=0;i<samples.length;i++) System.out.println(i+":"+Arrays.toString((int[])decode.invoke(null,(Object)samples[i])));
 }
}
