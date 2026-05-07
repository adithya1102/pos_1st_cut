using System;
using System.IO;

namespace GustoWaiter;

public static class CrashLogger
{
    private static readonly string LogPath = Path.Combine(
        AppDomain.CurrentDomain.BaseDirectory, "waiter_debug.log");

    public static void Log(Exception ex, string? context = null)
    {
        try
        {
            var entry = $"""
                [{DateTime.Now:yyyy-MM-dd HH:mm:ss}] {context ?? "unknown"}
                Type: {ex.GetType().FullName}
                Message: {ex.Message}
                Stack: {ex.StackTrace}
                Inner: {ex.InnerException?.Message ?? "none"}
                ---
                """;
            File.AppendAllText(LogPath, entry + Environment.NewLine);
        }
        catch { }
    }

    public static void Log(string message, string? context = null)
    {
        try
        {
            var entry = $"[{DateTime.Now:yyyy-MM-dd HH:mm:ss}] {context ?? "unknown"}: {message}";
            File.AppendAllText(LogPath, entry + Environment.NewLine);
        }
        catch { }
    }
}
