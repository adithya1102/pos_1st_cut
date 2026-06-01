using System;
using System.Net.WebSockets;
using System.Text;
using System.Text.Json;
using System.Threading;
using Microsoft.Maui.Controls;
using Microsoft.Maui.Graphics;
using GustoPOS.Services;
namespace GustoPOS.Views;
public partial class MainPage : ContentPage {
    private readonly ApiService _api;
    private PosTerminalPage? _pos;
    private FloorViewPage? _floor;
    private BillingPage? _billing;
    private AskGustoPage? _askGusto;
    private ManagementPage? _mgmt;
    private ClientWebSocket? _ws;
    private CancellationTokenSource? _wsCts;

    public MainPage(ApiService api) {
        InitializeComponent();
        _api = api;
        ShowPOS();
        _wsCts = new CancellationTokenSource();
        _ = Task.Run(() => ReceiveEventsAsync(_wsCts.Token));
    }

    private async Task ReceiveEventsAsync(CancellationToken ct) {
        var buf = new byte[4096];
        while (!ct.IsCancellationRequested) {
            _ws?.Dispose();
            _ws = new ClientWebSocket();
            try {
                await _ws.ConnectAsync(new Uri(_api.GetPosWsUrl()), ct);
                while (_ws.State == WebSocketState.Open && !ct.IsCancellationRequested) {
                    var result = await _ws.ReceiveAsync(buf, ct);
                    if (result.MessageType == WebSocketMessageType.Close) break;
                    var msg = Encoding.UTF8.GetString(buf, 0, result.Count);
                    using var doc = JsonDocument.Parse(msg);
                    var evt = doc.RootElement.TryGetProperty("event", out var ep) ? ep.GetString() : null;
                    if (evt is "NEW_ORDER" or "ORDER_CONFIRMED" or "TABLE_STATUS_CHANGED"
                            or "TABLE_OPENED" or "TABLE_CLOSED")
                        MainThread.BeginInvokeOnMainThread(() => _pos?.TriggerTableRefresh());
                }
            } catch (OperationCanceledException) {
                break;
            } catch (Exception ex) {
                System.Diagnostics.Debug.WriteLine($"MainPage WS: {ex.Message}, reconnecting in 5s");
            }
            if (!ct.IsCancellationRequested)
                try { await Task.Delay(5000, ct); } catch (OperationCanceledException) { break; }
        }
    }
    private void ShowPOS() { _pos ??= new PosTerminalPage(_api); ContentArea.Content = _pos; _pos.OnTabShown(); SetActive(BtnPOS); }
    private void ShowFloor() { _floor ??= new FloorViewPage(_api); ContentArea.Content = _floor; _floor.OnTabShown(); SetActive(BtnFloor); }
    private void ShowBilling() { _billing ??= new BillingPage(_api); ContentArea.Content = _billing; _billing.OnTabShown(); SetActive(BtnBilling); }
    private void ShowAskGusto() { _askGusto ??= new AskGustoPage(_api); ContentArea.Content = _askGusto; _askGusto.OnTabShown(); SetActive(BtnAskGusto); }
    private void ShowMgmt() { _mgmt ??= new ManagementPage(_api); ContentArea.Content = _mgmt; SetActive(BtnMgmt); }
    private void SetActive(Button active) {
        foreach (var b in new[] { BtnPOS, BtnFloor, BtnBilling, BtnAskGusto, BtnMgmt })
            b.BackgroundColor = Color.FromArgb("#00000000");
        active.BackgroundColor = Color.FromArgb("#28A745");
    }
    private void OnPosClicked(object s, EventArgs e) => ShowPOS();
    private void OnFloorClicked(object s, EventArgs e) => ShowFloor();
    private void OnBillingClicked(object s, EventArgs e) => ShowBilling();
    private void OnAskGustoClicked(object s, EventArgs e) => ShowAskGusto();
    private void OnMgmtClicked(object s, EventArgs e) => ShowMgmt();

    private void OnLogoutClicked(object s, EventArgs e)
    {
        SecureStorage.Remove("auth_token");
        SecureStorage.Remove("staff_name");
        SecureStorage.Remove("staff_role");
        SecureStorage.Remove("staff_id");

        var window = Application.Current?.Windows.FirstOrDefault();
        if (window is not null)
            window.Page = new PinLoginPage(_api);
    }
}
