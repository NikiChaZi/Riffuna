using System;
using System.Diagnostics;
using System.Globalization;
using System.IO;
using System.Runtime.InteropServices;
using System.Reflection;
using System.Security.Cryptography;
using System.Text;
using System.Text.RegularExpressions;
using System.Threading;
using System.Windows.Forms;
using Windows.Foundation;
using Windows.Media;
using Windows.Media.Playback;
using Windows.Storage.Streams;

[assembly: AssemblyTitle("Riffuna")]
[assembly: AssemblyProduct("Riffuna")]

internal static class RiffunaWindows
{
    [DllImport("shell32.dll", CharSet = CharSet.Unicode)]
    private static extern int SetCurrentProcessExplicitAppUserModelID(string appId);

    [MTAThread]
    private static int Main(string[] args)
    {
        if (args.Length > 0 && args[0] == "--install")
            return RunInstaller(args);
        if (args.Length != 1 || args[0] != "--media")
            return 2;

        try
        {
            SetCurrentProcessExplicitAppUserModelID("Riffuna.Desktop");
            using (var player = new MediaPlayer())
            {
                player.CommandManager.IsEnabled = false;
                using (var session = new MediaSession(player.SystemMediaTransportControls))
                {
                    string line;
                    while ((line = Console.ReadLine()) != null)
                        session.Apply(line.Split('\t'));
                }
            }
            return 0;
        }
        catch (Exception error)
        {
            Console.Error.WriteLine(error.GetType().Name + ": " + error.Message);
            return 1;
        }
    }

    private static int RunInstaller(string[] args)
    {
        try
        {
            int playerPid;
            if (args.Length != 4 || !int.TryParse(args[1], out playerPid) || playerPid <= 0)
                return 2;
            var installer = Path.GetFullPath(args[2]);
            var expectedHash = args[3];
            if (!Regex.IsMatch(Path.GetFileName(installer), @"\ARiffuna-[0-9]+\.[0-9]+\.[0-9]+-windows-x64\.exe\z") ||
                !Regex.IsMatch(expectedHash, @"\A[0-9a-f]{64}\z") ||
                !String.Equals(Path.GetDirectoryName(installer),
                    Path.GetDirectoryName(typeof(RiffunaWindows).Assembly.Location),
                    StringComparison.OrdinalIgnoreCase))
                return 2;

            Process player = null;
            try { player = Process.GetProcessById(playerPid); }
            catch (ArgumentException) { }
            using (player)
            {
                if (player != null && !player.WaitForExit(120000))
                    throw new InvalidOperationException("Закрой Riffuna и повтори установку.");
            }

            Process installerProcess;
            using (var file = File.Open(installer, FileMode.Open, FileAccess.Read, FileShare.Read))
            using (var sha = SHA256.Create())
            {
                var actualHash = BitConverter.ToString(sha.ComputeHash(file)).Replace("-", "").ToLowerInvariant();
                if (!String.Equals(actualHash, expectedHash, StringComparison.Ordinal))
                    throw new InvalidDataException("Контрольная сумма установщика не совпала.");

                installerProcess = Process.Start(new ProcessStartInfo(installer)
                {
                    WorkingDirectory = Path.GetDirectoryName(installer),
                    UseShellExecute = true
                });
            }
            using (installerProcess)
            {
                if (installerProcess != null)
                {
                    installerProcess.WaitForExit();
                    if (installerProcess.ExitCode == 0)
                        try { File.Delete(installer); }
                        catch (IOException) { }
                        catch (UnauthorizedAccessException) { }
                }
            }
            return 0;
        }
        catch (Exception error)
        {
            MessageBox.Show("Не удалось открыть обновление Riffuna.\r\n" + error.Message,
                "Riffuna", MessageBoxButtons.OK, MessageBoxIcon.Error);
            return 1;
        }
    }

    private sealed class MediaSession : IDisposable
    {
        private readonly SystemMediaTransportControls controls;
        private InMemoryRandomAccessStream coverStream;

        public MediaSession(SystemMediaTransportControls controls)
        {
            this.controls = controls;
            controls.ButtonPressed += OnButton;
            controls.PlaybackPositionChangeRequested += OnPosition;
        }

        public void Apply(string[] fields)
        {
            switch (fields[0])
            {
                case "clear":
                    controls.PlaybackStatus = MediaPlaybackStatus.Closed;
                    controls.IsEnabled = false;
                    controls.DisplayUpdater.ClearAll();
                    controls.DisplayUpdater.Update();
                    if (coverStream != null) coverStream.Dispose();
                    coverStream = null;
                    break;
                case "metadata":
                    if (fields.Length == 4)
                        SetMetadata(Decode(fields[1]), Decode(fields[2]), fields[3]);
                    break;
                case "state":
                    if (fields.Length == 5)
                        SetState(fields);
                    break;
            }
        }

        private void SetMetadata(string title, string artist, string cover)
        {
            var display = controls.DisplayUpdater;
            display.ClearAll();
            if (coverStream != null) coverStream.Dispose();
            coverStream = null;
            display.Type = MediaPlaybackType.Music;
            display.MusicProperties.Title = title;
            display.MusicProperties.Artist = artist;
            if (cover.Length > 0)
            {
                try
                {
                    var bytes = Convert.FromBase64String(cover);
                    if (bytes.Length <= 4 * 1024 * 1024)
                    {
                        using (var writer = new DataWriter())
                        {
                            writer.WriteBytes(bytes);
                            coverStream = new InMemoryRandomAccessStream();
                            var write = coverStream.WriteAsync(writer.DetachBuffer());
                            try
                            {
                                var stopwatch = Stopwatch.StartNew();
                                while (write.Status == AsyncStatus.Started &&
                                    stopwatch.ElapsedMilliseconds < 1500) Thread.Sleep(5);
                                if (write.Status == AsyncStatus.Completed)
                                {
                                    coverStream.Seek(0);
                                    display.Thumbnail = RandomAccessStreamReference.CreateFromStream(coverStream);
                                }
                                else
                                    write.Cancel();
                            }
                            finally { write.Close(); }
                        }
                    }
                }
                catch (Exception error)
                {
                    Console.Error.WriteLine("Cover: " + error.GetType().Name);
                }
            }
            display.Update();
        }

        private void SetState(string[] fields)
        {
            long duration;
            long position;
            if (!long.TryParse(fields[2], NumberStyles.None, CultureInfo.InvariantCulture, out position) ||
                !long.TryParse(fields[3], NumberStyles.None, CultureInfo.InvariantCulture, out duration))
                return;

            controls.IsEnabled = true;
            controls.IsPlayEnabled = true;
            controls.IsPauseEnabled = true;
            controls.IsNextEnabled = true;
            controls.IsPreviousEnabled = true;
            switch (fields[1])
            {
                case "playing": controls.PlaybackStatus = MediaPlaybackStatus.Playing; break;
                case "changing": controls.PlaybackStatus = MediaPlaybackStatus.Changing; break;
                default: controls.PlaybackStatus = MediaPlaybackStatus.Paused; break;
            }
            if (duration > 0)
            {
                // WinRT's timeline API can show position even before the stream is seekable.
                controls.UpdateTimelineProperties(new SystemMediaTransportControlsTimelineProperties
                {
                    StartTime = TimeSpan.Zero,
                    MinSeekTime = TimeSpan.Zero,
                    MaxSeekTime = TimeSpan.FromMilliseconds(fields[4] == "1" ? duration : 0),
                    EndTime = TimeSpan.FromMilliseconds(duration),
                    Position = TimeSpan.FromMilliseconds(Math.Min(position, duration))
                });
            }
        }

        private void OnButton(SystemMediaTransportControls sender, SystemMediaTransportControlsButtonPressedEventArgs args)
        {
            switch (args.Button)
            {
                case SystemMediaTransportControlsButton.Play: Console.WriteLine("play"); break;
                case SystemMediaTransportControlsButton.Pause: Console.WriteLine("pause"); break;
                case SystemMediaTransportControlsButton.Next: Console.WriteLine("next"); break;
                case SystemMediaTransportControlsButton.Previous: Console.WriteLine("previous"); break;
            }
        }

        private void OnPosition(SystemMediaTransportControls sender, PlaybackPositionChangeRequestedEventArgs args)
        {
            Console.WriteLine("seek\t" + ((long)args.RequestedPlaybackPosition.TotalMilliseconds)
                .ToString(CultureInfo.InvariantCulture));
        }

        private static string Decode(string encoded)
        {
            return Encoding.UTF8.GetString(Convert.FromBase64String(encoded));
        }

        public void Dispose()
        {
            controls.ButtonPressed -= OnButton;
            controls.PlaybackPositionChangeRequested -= OnPosition;
            controls.PlaybackStatus = MediaPlaybackStatus.Closed;
            controls.IsEnabled = false;
            if (coverStream != null) coverStream.Dispose();
        }
    }
}
