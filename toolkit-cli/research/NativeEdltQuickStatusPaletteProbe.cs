// Original EDLT model + actual Windows nested BindingSource/ComboBox behavior.
// No network/controller construction; declared model fixture fields only.
using System;
using System.Linq;
using System.ComponentModel;
using System.Reflection;
using System.Runtime.Serialization;
using System.Windows.Forms;
using CBusLogicModel;
using CBusLogicModel.Utilities;
using CBusLogicModel.Units.EDLT;
class WindowsQuickStatusPaletteProbe {
 static EDLTUnit Unit(int mode,int colour) {
  var u=(EDLTUnit)FormatterServices.GetUninitializedObject(typeof(EDLTUnit));u.PPAttributes=new BindingList<PPAttribute>();
  typeof(EDLTUnit).GetField("commonConstants",BindingFlags.Instance|BindingFlags.NonPublic).SetValue(u,new CommonConstants());
  foreach(var pair in new[]{new object[]{"QuickStatusMode",mode},new object[]{"QuickStatusColour1",colour},new object[]{"QuickStatusColour2",colour},new object[]{"QuickStatusColour3",colour}})
   u.PPAttributes.Add(new PPAttribute{Name=(string)pair[0],Value=pair[1].ToString()});
  return u;
 }
 static string Values(EDLTUnit u,ComboBox[] boxes) {
  return u.QuickStatusMode+";"+string.Join("|",boxes.Select((box,index)=>u.GetPPAttribute("QuickStatusColour"+(index+1)).ValueAsInt+","+box.SelectedIndex+","+(box.SelectedValue==null?"null":box.SelectedValue.ToString())+",choices="+string.Join(",",box.Items.Cast<DataStore>().Select(d=>d.ValueAsInt))));
 }
 [STAThread] static void Main(string[] args) {
  int batch=int.Parse(args[0]);if(batch<0||batch>3)throw new ArgumentOutOfRangeException("batch");
  Console.WriteLine("runtime:"+Environment.OSVersion+":"+Environment.Version+":pointer-size="+IntPtr.Size);
  PPAttribute.bInitialiseMode=false;
  foreach(int initial in new[]{batch*2,batch*2+1})foreach(int target in new[]{0,1,2,3})foreach(int colour in new[]{0,1,2,3,4,5,6,7,8,9,39,254,255}) {
   var u=Unit(initial,colour);
   using(var form=new Form())using(var parent=new BindingSource()) {
    var sources=new[]{new BindingSource(),new BindingSource(),new BindingSource()};
    var boxes=new[]{new ComboBox(),new ComboBox(),new ComboBox()};
    try {
     ((ISupportInitialize)parent).BeginInit();foreach(var source in sources)((ISupportInitialize)source).BeginInit();
     parent.DataSource=typeof(EDLTUnit);
     foreach(var source in sources){source.DataMember="QuickStatusColours";source.DataSource=parent;}
     // Original form constructs colour2, then colour1, then colour3 bindings.
     foreach(int index in new[]{1,0,2}) {
      var box=boxes[index];box.DataBindings.Add(new Binding("SelectedValue",parent,"QuickStatusColour"+(index+1),true));
      box.DataSource=sources[index];box.DisplayMember="FormattedDisplay";box.DropDownStyle=ComboBoxStyle.DropDownList;
      box.FormattingEnabled=true;box.ValueMember="ValueAsInt";box.Top=index*30;form.Controls.Add(box);
     }
     ((ISupportInitialize)parent).EndInit();foreach(var source in sources)((ISupportInitialize)source).EndInit();
     parent.DataSource=u;form.Show();Application.DoEvents();string before=Values(u,boxes);
     u.QuickStatusMode=target;Application.DoEvents();string after=Values(u,boxes);
     bool validation=form.Validate();foreach(int index in new[]{1,0,2})boxes[index].DataBindings["SelectedValue"].WriteValue();Application.DoEvents();
     Console.WriteLine("palette3:"+initial+","+target+","+colour+":"+before+":"+after+":"+Values(u,boxes)+":validation="+validation);
     form.Close();
    } finally {foreach(var box in boxes)box.Dispose();foreach(var source in sources)source.Dispose();}
   }
  }
 }
}
