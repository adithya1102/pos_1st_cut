using Microsoft.Maui.Controls.Hosting;
using Microsoft.Maui.Hosting;
using System;
using System.Threading.Tasks;
using GustoWaiter.Services;

namespace GustoWaiter;
public static class MauiProgram {
    public static MauiApp CreateMauiApp() =>
        MauiApp.CreateBuilder().UseMauiApp<App>()
            .ConfigureFonts(f => f.AddFont("OpenSans-Regular.ttf", "OpenSansRegular"))
            .Build();

    static MauiProgram() {
        // Global exception handlers
        AppDomain.CurrentDomain.UnhandledException += (s, e) => {
            if (e.ExceptionObject is Exception ex) CrashLogger.Log(ex, "AppDomain.UnhandledException");
            else CrashLogger.Log("Unhandled exception object: " + e.ExceptionObject?.ToString(), "AppDomain.UnhandledException");
        };
        TaskScheduler.UnobservedTaskException += (s, e) => {
            CrashLogger.Log(e.Exception, "TaskScheduler.UnobservedTaskException");
        };
    }
}

