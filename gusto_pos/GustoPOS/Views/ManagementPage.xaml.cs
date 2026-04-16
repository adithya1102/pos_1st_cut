using GustoPOS.Services;

namespace GustoPOS.Views;

public partial class ManagementPage : ContentView
{
    private readonly ApiService _api;

    public ManagementPage(ApiService api)
    {
        InitializeComponent();
        _api = api;
        LoadConfigAsync();
    }

    private async void LoadConfigAsync()
    {
        var config = await _api.GetOutletConfigAsync();
        NormalCountEntry.Text = config.NormalTableCount.ToString();
        AcCountEntry.Text = config.AcTableCount.ToString();
    }

    private async void OnSaveNormalClicked(object? s, EventArgs e)
    {
        var value = NormalCountEntry.Text?.Trim();
        if (string.IsNullOrEmpty(value) || !int.TryParse(value, out var count) || count < 1)
        {
            NormalSaveStatus.Text = "Invalid ❌";
            NormalSaveStatus.TextColor = Microsoft.Maui.Graphics.Colors.Red;
            return;
        }

        BtnSaveNormal.IsEnabled = false;
        NormalSaveStatus.Text = "Saving...";
        NormalSaveStatus.TextColor = Microsoft.Maui.Graphics.Colors.Gray;

        var ok = await _api.UpdateOutletConfigAsync("normal_table_count", value);
        if (ok)
        {
            NormalSaveStatus.Text = "Saved! ✅";
            NormalSaveStatus.TextColor = Microsoft.Maui.Graphics.Color.FromArgb("#28A745");
            await Task.Delay(2000);
            NormalSaveStatus.Text = "";
        }
        else
        {
            NormalSaveStatus.Text = "Failed ❌";
            NormalSaveStatus.TextColor = Microsoft.Maui.Graphics.Colors.Red;
        }

        BtnSaveNormal.IsEnabled = true;
    }

    private async void OnSaveAcClicked(object? s, EventArgs e)
    {
        var value = AcCountEntry.Text?.Trim();
        if (string.IsNullOrEmpty(value) || !int.TryParse(value, out var count) || count < 1)
        {
            AcSaveStatus.Text = "Invalid ❌";
            AcSaveStatus.TextColor = Microsoft.Maui.Graphics.Colors.Red;
            return;
        }

        BtnSaveAc.IsEnabled = false;
        AcSaveStatus.Text = "Saving...";
        AcSaveStatus.TextColor = Microsoft.Maui.Graphics.Colors.Gray;

        var ok = await _api.UpdateOutletConfigAsync("ac_table_count", value);
        if (ok)
        {
            AcSaveStatus.Text = "Saved! ✅";
            AcSaveStatus.TextColor = Microsoft.Maui.Graphics.Color.FromArgb("#28A745");
            await Task.Delay(2000);
            AcSaveStatus.Text = "";
        }
        else
        {
            AcSaveStatus.Text = "Failed ❌";
            AcSaveStatus.TextColor = Microsoft.Maui.Graphics.Colors.Red;
        }

        BtnSaveAc.IsEnabled = true;
    }
}
