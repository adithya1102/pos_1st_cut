using System;
using System.Net.WebSockets;
using System.Text;
using System.Text.Json;
using System.Threading;
using Microsoft.Maui.Controls;
using Microsoft.Maui.Graphics;
using GustoWaiter.Services;

namespace GustoWaiter.Views;

public partial class DashboardPage : ContentPage {
    private readonly ApiService _api = new();
    private AlertsView?  _alerts;
    private OrderView?   _order;
    private TablesView?  _tables;
    private Button[] _tabs = Array.Empty<Button>();
    private ClientWebSocket? _waiterWs;
    private CancellationTokenSource? _waiterWsCts;
    private readonly HashSet<string> _pendingApprovals = new();

    public DashboardPage() {
        InitializeComponent();
        _tabs = new[] { TabAlerts, TabOrder, TabTables };
        _ = _api.SetGpsAsync();
        ShowAlerts();
        ConnectWaiterWs();
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

    private void OnAlertsTab(object s, EventArgs e) => ShowAlerts();
    private void OnOrderTab(object s, EventArgs e)  => ShowOrder();
    private void OnTablesTab(object s, EventArgs e) => ShowTables();

    private void ConnectWaiterWs() {
        _waiterWsCts?.Cancel();
        _waiterWsCts = new CancellationTokenSource();
        _ = Task.Run(() => ReceiveWaiterEventsAsync(_waiterWsCts.Token));
    }

    private async Task ReceiveWaiterEventsAsync(CancellationToken ct) {
        var buf = new byte[4096];
        while (!ct.IsCancellationRequested) {
            _waiterWs?.Dispose();
            _waiterWs = new ClientWebSocket();
            try {
                await _waiterWs.ConnectAsync(new Uri(_api.GetWaiterWsUrl()), ct);
                while (_waiterWs.State == WebSocketState.Open && !ct.IsCancellationRequested) {
                    var result = await _waiterWs.ReceiveAsync(buf, ct);
                    if (result.MessageType == WebSocketMessageType.Close) break;
                    var msg = Encoding.UTF8.GetString(buf, 0, result.Count);
                    using var doc = JsonDocument.Parse(msg);
                    var evt = doc.RootElement.TryGetProperty("event", out var ep) ? ep.GetString() : null;
                    if (evt == "NEW_ORDER") {
                        var orderId  = doc.RootElement.TryGetProperty("id",           out var oid) ? oid.GetString() ?? "" : "";
                        var tableId  = doc.RootElement.TryGetProperty("table_id",     out var tid) ? tid.GetString() ?? "" : "";
                        decimal total = 0m;
                        if (doc.RootElement.TryGetProperty("total_amount", out var ta))
                            ta.TryGetDecimal(out total);
                        if (!string.IsNullOrEmpty(orderId))
                            _ = ShowApprovalPopupAsync(orderId, tableId, total);
                        else
                            _ = RefreshNotificationsFromWsAsync();
                    } else if (evt == "ORDER_CONFIRMED") {
                        _ = RefreshNotificationsFromWsAsync();
                    } else if (evt is "TABLE_OPENED" or "TABLE_CLOSED" or "TABLE_STATUS_CHANGED")
                        if (_tables != null) _ = _tables.TriggerRefreshAsync();
                }
            } catch (OperationCanceledException) {
                break;
            } catch (Exception ex) {
                System.Diagnostics.Debug.WriteLine($"Waiter WS: {ex.Message}, reconnecting in 5s");
                CrashLogger.Log(ex, "DashboardPage.ReceiveWaiterEventsAsync");
            }
            if (!ct.IsCancellationRequested)
                try { await Task.Delay(5000, ct); } catch (OperationCanceledException) { break; }
        }
    }

    protected override void OnAppearing() {
        base.OnAppearing();
        _ = RefreshNotificationsFromWsAsync();
    }

    private async Task RefreshNotificationsFromWsAsync() {
        try {
            var notifs = await _api.GetNotificationsAsync();
            await MainThread.InvokeOnMainThreadAsync(() => {
                try {
                    SetBadge(notifs.Count);
                    _alerts?.Refresh(notifs);
                } catch (Exception ex) {
                    CrashLogger.Log(ex, "DashboardPage.RefreshNotificationsFromWsAsync.UI");
                }
            });
        } catch (Exception ex) {
            System.Diagnostics.Debug.WriteLine($"WS notification refresh error: {ex.Message}");
            CrashLogger.Log(ex, "DashboardPage.RefreshNotificationsFromWsAsync");
        }
    }

    private async Task ShowApprovalPopupAsync(string orderId, string tableId, decimal totalAmount) {
        // Deduplicate: only one popup per order at a time.
        bool added;
        lock (_pendingApprovals) { added = _pendingApprovals.Add(orderId); }
        if (!added) return;

        try {
            await MainThread.InvokeOnMainThreadAsync(async () => {
                try {
                    var popup = new OrderApprovalPage(_api, orderId, tableId, totalAmount);
                    popup.Dismissed += () => _ = RefreshNotificationsFromWsAsync();
                    await Application.Current!.Windows[0].Page!.Navigation.PushModalAsync(popup, animated: false);
                } catch (Exception ex) {
                    CrashLogger.Log(ex, "DashboardPage.ShowApprovalPopupAsync.Push");
                    _ = RefreshNotificationsFromWsAsync();
                }
            });
        } finally {
            lock (_pendingApprovals) { _pendingApprovals.Remove(orderId); }
        }
    }
}
