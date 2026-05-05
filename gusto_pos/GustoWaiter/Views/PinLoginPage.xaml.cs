using System.Text;
using GustoWaiter.Services;
using Microsoft.Maui.Controls.Shapes;

namespace GustoWaiter.Views;

public partial class PinLoginPage : ContentPage {
    private readonly ApiService _api = new();
    private readonly StringBuilder _pin = new();
    private readonly Ellipse[] _dots;

    public PinLoginPage() {
        InitializeComponent();
        _dots = [Dot1, Dot2, Dot3, Dot4];
    }

    private void OnDigit(object sender, EventArgs e) {
        if (_pin.Length >= 4) return;
        if (sender is Button btn) _pin.Append(btn.CommandParameter);
        RefreshDots();
        if (_pin.Length == 4) _ = SubmitPin();
    }

    private void OnBackspace(object sender, EventArgs e) {
        if (_pin.Length == 0) return;
        _pin.Remove(_pin.Length - 1, 1);
        HideError();
        RefreshDots();
    }

    private void OnEnter(object sender, EventArgs e) {
        if (_pin.Length == 0) return;
        _ = SubmitPin();
    }

    private void RefreshDots() {
        var filled = Color.FromArgb("#ac99ea");
        var empty  = Color.FromArgb("#404040");
        for (int i = 0; i < _dots.Length; i++)
            _dots[i].Fill = new SolidColorBrush(i < _pin.Length ? filled : empty);
    }

    private async Task SubmitPin() {
        var (response, error) = await _api.PinLoginAsync(_pin.ToString());
        if (response is null) {
            ShowError(error ?? "Invalid PIN. Please try again.");
            _pin.Clear();
            RefreshDots();
            return;
        }

        await SecureStorage.SetAsync("auth_token", response.AccessToken);
        await SecureStorage.SetAsync("staff_name", response.Staff.Name);
        await SecureStorage.SetAsync("staff_role", response.Staff.Role);
        await SecureStorage.SetAsync("staff_id",   response.Staff.Id);

        var window = Application.Current?.Windows.FirstOrDefault();
        if (window is not null)
            window.Page = new DashboardPage();
    }

    private void ShowError(string message) {
        ErrorLabel.Text      = message;
        ErrorLabel.IsVisible = true;
    }

    private void HideError() {
        ErrorLabel.IsVisible = false;
    }
}
