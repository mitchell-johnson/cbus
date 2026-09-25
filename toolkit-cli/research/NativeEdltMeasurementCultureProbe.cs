// Execute Toolkit 1.18 Measurement parsing, storage and final validation under
// explicit Windows cultures.  Vendor assemblies are supplied separately.
using System;
using System.ComponentModel;
using System.Globalization;
using System.Reflection;
using System.Runtime.Serialization;
using System.Text;
using System.Windows.Forms;
using CBusLogicModel;
using CBusLogicModel.CBusObjects;
using CBusLogicModel.EDLT.WidgetData;
using CBusLogicModel.Units.EDLT;
using CBusLogicModel.Units.EDLT.WidgetData;
using CBusLogicModel.Utilities;
using eDLT.WidgetPanels;

class NativeEdltMeasurementCultureProbe {
 static T Bare<T>() { return (T)FormatterServices.GetUninitializedObject(typeof(T)); }
 static string B(string value) { return Convert.ToBase64String(Encoding.UTF8.GetBytes(value)); }
 static string I(double value) { return value.ToString("R", CultureInfo.InvariantCulture); }
 static string Chars(string value) {
  string[] codes=new string[value.Length];
  for(int i=0;i<value.Length;i++)codes[i]=((int)value[i]).ToString("X4");
  return String.Join(",",codes);
 }
 static EDLTUnit Unit() {
  var unit=Bare<EDLTUnit>();
  unit.PPAttributes=new BindingList<PPAttribute>();
  unit.Widgets=new BindingList<EDLTWidget>();
  unit.Scenes=new BindingList<EDLTScene>();
  for(int index=1;index<32;index++)
   unit.PPAttributes.Add(new PPAttribute{Name="Widget6WidgetByteValue"+index,Value="0"});
  unit.PPAttributes.Add(new PPAttribute{Name="Widget6RestoreLevel",Value="0"});
  unit.PPAttributes.Add(new PPAttribute{Name="PrimaryApplication",Value="56"});
  unit.PPAttributes.Add(new PPAttribute{Name="SecondaryApplication",Value="57"});
  unit.PPAttributes.Add(new PPAttribute{Name="NavWidgetVariant",Value="0"});
  var network=Bare<CBusNetwork>();network.Applications=new BindingList<CBusApplication>();unit.Network=network;
  unit.StaticLabels=new BindingList<DataStore>();unit.StaticTextSuggest=new BindingList<DataStore>();
  for(int index=0;index<64;index++) {
   var attribute=new PPAttribute{Name="StaticTextString"+index};attribute.ValueAsUtf8String="";
   unit.PPAttributes.Add(attribute);unit.StaticLabels.Add(new DataStore("",index));
  }
  return unit;
 }
 static MeasurementData Measurement() {
  var unit=Unit();var widget=new EDLTWidget{Unit=unit,Attributes=unit.PPAttributes,WidgetNumber=6};
  var data=new MeasurementData(widget,"Widget6",unit.PPAttributes);widget.WidgetData=data;unit.Widgets.Add(widget);
  data.SetToDefault();return data;
 }
 static string Bytes(MeasurementData data) {
  byte[] bytes=new byte[10];bytes[0]=12;
  for(int index=1;index<10;index++)bytes[index]=(byte)data.WidgetByte(index).ValueAsInt;
  return BitConverter.ToString(bytes).Replace("-","");
 }
 static void ParseCases(string cultureName) {
  CultureInfo culture=cultureName=="invariant"?CultureInfo.InvariantCulture:new CultureInfo(cultureName);
  CultureInfo.CurrentCulture=culture;CultureInfo.CurrentUICulture=culture;
  Console.WriteLine("culture:"+cultureName+":"+Chars(culture.NumberFormat.NumberDecimalSeparator)+":"+Chars(culture.NumberFormat.NumberGroupSeparator));
  string[] inputs={"1.5","1,5","1,234.5","1.234,5","1,,2",",1","1.2,3","1,.2",".5",",5","1,25e2"," 1,5 ","1\u202f234,5","1_0","NaN","Infinity","1e-50","1e-51","1e-130","1e-300","1e127","1e128","1e300","1e309"};
  foreach(string input in inputs) {
   try {
    double number=Double.Parse(input);
    if(Double.IsNaN(number)||Double.IsInfinity(number)) {
     Console.WriteLine("parse:"+B(input)+":nonfinite:"+I(number));continue;
    }
    double adjusted;int integer,exponent;
    bool exact=PPHelper.BreakNumberIntoIntegerAndExponent(number,out adjusted,out integer,out exponent);
    Console.WriteLine("parse:"+B(input)+":ok:"+I(number)+":"+exact+":"+integer+":"+exponent+":"+PPHelper.FormatDoubleWithoutE(adjusted));
   } catch(Exception error) {
    Console.WriteLine("parse:"+B(input)+":error:"+error.GetType().Name);
   }
  }
 }
 static void StorageCases(string cultureName) {
  CultureInfo.CurrentCulture=cultureName=="invariant"?CultureInfo.InvariantCulture:new CultureInfo(cultureName);
  foreach(string input in new[]{"1.5","1,5","1e-51","1e-130","1e128","1e300"}) {
   var gain=Measurement();gain.GainComposite=input;
   Console.WriteLine("storage:"+cultureName+":gain:"+B(input)+":"+Bytes(gain)+":"+gain.Gain+":"+gain.GainExponent+":"+gain.GainComposite);
   var offset=Measurement();offset.OffsetComposite=input;
   Console.WriteLine("storage:"+cultureName+":offset:"+B(input)+":"+Bytes(offset)+":"+offset.Offset+":"+offset.OffsetExponent+":"+offset.OffsetComposite);
  }
 }
 static string FinalText(string cultureName,string field,string previous,string input) {
  CultureInfo.CurrentCulture=cultureName=="invariant"?CultureInfo.InvariantCulture:new CultureInfo(cultureName);
  var panel=Bare<MeasurementWidget>();
  typeof(MeasurementWidget).GetField("previousString",BindingFlags.NonPublic|BindingFlags.Instance).SetValue(panel,previous);
  var box=new TextBox();box.Text=input;box.SelectionStart=box.TextLength;
  if(field=="gain")typeof(MeasurementWidget).GetField("textBox1",BindingFlags.NonPublic|BindingFlags.Instance).SetValue(panel,box);
  typeof(MeasurementWidget).GetMethod("ValidateTextDouble",BindingFlags.NonPublic|BindingFlags.Instance).Invoke(panel,new object[]{box,EventArgs.Empty});
  var validating=typeof(MeasurementWidget).GetMethod(field=="gain"?"textBox1_Validating":"textBox2_Validating",BindingFlags.NonPublic|BindingFlags.Instance);
  validating.Invoke(panel,new object[]{box,new CancelEventArgs()});
  return box.Text;
 }
 [STAThread]
 static void Main() {
  PPAttribute.bInitialiseMode=true;
  foreach(string culture in new[]{"invariant","en-NZ","de-DE","fr-FR"})ParseCases(culture);
  foreach(string culture in new[]{"invariant","de-DE"})StorageCases(culture);
  foreach(string culture in new[]{"invariant","de-DE"})
   foreach(string field in new[]{"gain","offset"})
    foreach(string input in new[]{"","0","1.5","1,5","x","-","."})
     Console.WriteLine("validation:"+culture+":"+field+":"+B(input)+":"+B(FinalText(culture,field,"2",input)));
 }
}
