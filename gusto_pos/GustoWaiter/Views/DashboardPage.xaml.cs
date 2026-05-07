using System;
using System.Timers;
using Microsoft.Maui.Controls;
using Microsoft.Maui.Graphics;
using GustoWaiter.Services;

namespace GustoWaiter.Views;

public partial class DashboardPage : ContentPage {
    private readonly ApiService _api = new();
    private AlertsView?  _alerts;
    private OrderView?   _order;
    private TablesView?  _tables;
    private System.Timers.Timer? _timer;
    private Button[] _tabs = Array.Empty<Button>();

    public DashboardPage() {
        InitializeComponent();
        _tabs = new[] { TabAlerts, TabOrder, TabTables };
        _ = _api.SetGpsAsync();
        ShowAlerts();
        StartPolling();
    }

    private void ShowAlerts()  { _alerts ??= new AlertsView(_api, this); MainContent.Content = _alerts;  ActivateTab(TabAlerts); }
    private void ShowOrder()   { _order  ??= new OrderView(_api, this);  MainContent.Content = _order;   ActivateTab(TabOrder); }
    private void ShowTables()  { _tables ??= new TablesView(_api, this); MainContent.Content = _tables;  ActivateTab(TabTables); }

    private void ActivateTab(Button active) {
        foreach (var b in _tabs) { b.BackgroundColor = Colors.White; b.TextColor = Color.FromArgb("#333333"); }
        active.BackgroundColor = Color.FromArgb("#1B4332"); active.TextColor = Colors.White;
    }

    public void SetBadge(int count) {
        BadgeBorder.IsVisible = count > 0;
        BadgeLabel.Text = count.ToString();
    }

    private void StartPolling() {
        _timer = new System.Timers.Timer(3000);
        _timer.Elapsed += async (s, e) => {
            try {
                var notifs = await _api.GetNotificationsAsync();
                if (notifs == null) return;
                await MainThread.InvokeOnMainThreadAsync(() => {
                    try {
                        SetBadge(notifs.Count);
                        _alerts?.Refresh(notifs);
                    } catch (Exception uiEx) {
                        System.Diagnostics.Debug.WriteLine(
                            $"UI update error: {uiEx.Message}");
                        CrashLogger.Log(uiEx, "DashboardPage.StartPolling.UIUpdate");
                    }
                });
            } catch (Exception ex) {
                System.Diagnostics.Debug.WriteLine(
                    $"Polling error (backend unreachable?): {ex.Message}");
                CrashLogger.Log(ex, "DashboardPage.StartPolling");
            }
        };
        _timer.Start();
    }

    private void OnAlertsTab(object s, EventArgs e) => ShowAlerts();
    private void OnOrderTab(object s, EventArgs e)  => ShowOrder();
    private void OnTablesTab(object s, EventArgs e) => ShowTables();
}
