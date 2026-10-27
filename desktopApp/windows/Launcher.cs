using System;
using System.Diagnostics;
using System.IO;
using System.Reflection;
using System.Windows.Forms;
[assembly: AssemblyTitle("Riffuna")]
[assembly: AssemblyProduct("Riffuna")]
[assembly: AssemblyVersion("0.2.0.0")]
[assembly: AssemblyFileVersion("0.2.0.0")]
internal static class Launcher {
    [STAThread]
    private static int Main() {
        var executable=Path.Combine(AppDomain.CurrentDomain.BaseDirectory,"Riffuna.runtime","Riffuna.exe");
        if(!File.Exists(executable)) {
            MessageBox.Show("Не найдены файлы Riffuna. Папка Riffuna.runtime должна находиться рядом с Riffuna.exe.","Riffuna",MessageBoxButtons.OK,MessageBoxIcon.Information);
            return 1;
        }
        try {
            var start=new ProcessStartInfo(executable) { WorkingDirectory=Path.GetDirectoryName(executable),UseShellExecute=false,CreateNoWindow=true };
            foreach(var name in new[]{"MUSICDESK_DATA_DIR","MUSICDESK_UI_REPORT","MUSICDESK_AUTOCLOSE_MS"})start.EnvironmentVariables.Remove(name);
            Process.Start(start);
            return 0;
        } catch(Exception) {
            MessageBox.Show("Не удалось запустить Riffuna. Проверь, что приложение распаковано полностью.","Riffuna",MessageBoxButtons.OK,MessageBoxIcon.Error);
            return 1;
        }
    }
}
