using System;
using System.IO;
using System.Text;

namespace GustoWaiter.Services;

public static class CrashLogger {
    private static readonly string LogPath = Path.Combine(AppContext.BaseDirectory, "waiter_debug.log");

    public static void Log(Exception ex, string? context = null) {
        try {
            var sb = new StringBuilder();
            sb.AppendLine("====");
            sb.AppendLine(DateTime.UtcNow.ToString("o") + (context != null ? $" [{context}]" : ""));
            sb.AppendLine(ex.GetType().FullName + ": " + ex.Message);
            sb.AppendLine(ex.StackTrace ?? "");
            if (ex.InnerException != null) {
                sb.AppendLine("-- Inner Exception --");
                sb.AppendLine(ex.InnerException.GetType().FullName + ": " + ex.InnerException.Message);
                sb.AppendLine(ex.InnerException.StackTrace ?? "");
            }
            File.AppendAllText(LogPath, sb.ToString());
        } catch {
            // best-effort logging, swallow any errors
        }
    }

    public static void Log(string message, string? context = null) {
        try {
            var text = DateTime.UtcNow.ToString("o") + (context != null ? $" [{context}] " : " ") + message + Environment.NewLine;
            File.AppendAllText(Path.Combine(AppContext.BaseDirectory, "waiter_debug.log"), text);
        } catch { }
    }
}
