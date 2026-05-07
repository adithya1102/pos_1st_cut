using GustoWaiter.Views;
namespace GustoWaiter;
public partial class App : Application {
    public App() { InitializeComponent(); }
        protected override Window CreateWindow(IActivationState? s)
        {
            var win = new Window(new PinLoginPage()) { Title = "Gusto Waiter", Width = 420, Height = 860 };
            _ = CheckBackendConnectivity();
            return win;
        }

        private async Task CheckBackendConnectivity() {
            try {
                using var http = new System.Net.Http.HttpClient() { Timeout = TimeSpan.FromSeconds(3) };
                var resp = await http.GetAsync("http://127.0.0.1:8000/");
                if (!resp.IsSuccessStatusCode) {
                    await ShowBackendAlert();
                }
            } catch (Exception ex) {
                CrashLogger.Log(ex, "App.CheckBackendConnectivity");
                try { await ShowBackendAlert(); } catch { }
            }
        }

        private async Task ShowBackendAlert() {
            await MainThread.InvokeOnMainThreadAsync(async () => {
                try {
                    var page = Current?.Windows.FirstOrDefault()?.Page;
                    if (page != null)
                        await page.DisplayAlertAsync("Backend unreachable", "Backend unreachable. Make sure the server is running on port 8000.", "OK");
                } catch { }
            });
        }
    }
