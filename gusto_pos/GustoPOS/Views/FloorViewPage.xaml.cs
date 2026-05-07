using System;
using System.Collections.Generic;
using System.Net.Http;
using System.Net.WebSockets;
using System.Text;
using System.Text.Json;
using System.Threading;
using Microsoft.Maui.Controls;
using Microsoft.Maui.Graphics;
using GustoPOS.Models;
using GustoPOS.Services;
using Microsoft.Maui.Dispatching;

namespace GustoPOS.Views;

public partial class FloorViewPage : ContentView
{
    private const string BackendBase = "http://127.0.0.1:8000/api/v1";
    private const string OutletId = "0b8a8349-6144-41a8-b028-b9089bd8eaea";
    private const string CustomerBase = "http://localhost:3000/menu";
    private readonly HttpClient _http = new();
    private readonly ApiService _api;
    private IDispatcherTimer? _refreshTimer;
    private ClientWebSocket? _floorWs;
    private CancellationTokenSource? _floorWsCts;

    private List<Table> _normalTables = new();
    private List<Table> _acTables = new();
    private int _normalCount = 10;
    private int _acCount = 10;

    private Dictionary<string, string> _tableTokens = new();

    public FloorViewPage(ApiService api)
    {
        InitializeComponent();
        _api = api;
        LoadConfigAndBuildAsync();
        _refreshTimer = Application.Current!.Dispatcher.CreateTimer();
        _refreshTimer.Interval = TimeSpan.FromSeconds(30);
        _refreshTimer.Tick += (s, e) => RefreshTableStatusFromDbAsync();
        _refreshTimer.Start();
        _ = ConnectFloorWsAsync();
    }

    public void OnTabShown()
    {
        LoadConfigAndBuildAsync();
        _ = ConnectFloorWsAsync();
    }

    private async Task ConnectFloorWsAsync()
    {
        _floorWsCts?.Cancel();
        _floorWsCts = new CancellationTokenSource();
        _floorWs = new ClientWebSocket();
        try
        {
            await _floorWs.ConnectAsync(new Uri(_api.GetPosWsUrl()), _floorWsCts.Token);
            _ = Task.Run(() => ReceiveFloorEventsAsync(_floorWsCts.Token));
        }
        catch (Exception ex)
        {
            System.Diagnostics.Debug.WriteLine($"Floor WS connect failed: {ex.Message}");
        }
    }

    private async Task ReceiveFloorEventsAsync(CancellationToken ct)
    {
        var buf = new byte[4096];
        while (_floorWs?.State == WebSocketState.Open && !ct.IsCancellationRequested)
        {
            try
            {
                var result = await _floorWs.ReceiveAsync(buf, ct);
                if (result.MessageType == WebSocketMessageType.Close) break;
                var msg = Encoding.UTF8.GetString(buf, 0, result.Count);
                using var doc = JsonDocument.Parse(msg);
                var evt = doc.RootElement.TryGetProperty("event", out var ep) ? ep.GetString() : null;
                if (evt is "NEW_ORDER" or "ORDER_CONFIRMED" or "ORDER_STATUS_UPDATED")
                    MainThread.BeginInvokeOnMainThread(() => RefreshTableStatusFromDbAsync());
            }
            catch (OperationCanceledException) { break; }
            catch (Exception ex)
            {
                System.Diagnostics.Debug.WriteLine($"Floor WS recv: {ex.Message}");
                break;
            }
        }
    }

    private async void LoadConfigAndBuildAsync()
    {
        var config = await _api.GetOutletConfigAsync();
        _normalCount = config.NormalTableCount;
        _acCount = config.AcTableCount;
        BuildTablesFromConfig();
        BuildGrid();
        RefreshTableStatusFromDbAsync();
    }

    private void BuildTablesFromConfig()
    {
        _normalTables.Clear();
        _acTables.Clear();
        for (int i = 1; i <= _normalCount; i++)
            _normalTables.Add(new Table { Id = $"N-{i}", Name = $"N-{i}", Capacity = 4, Status = "free" });
        for (int i = 1; i <= _acCount; i++)
            _acTables.Add(new Table { Id = $"A-{i}", Name = $"A-{i}", Capacity = 4, Status = "free" });
    }

    private async void RefreshTableStatusFromDbAsync()
    {
        var allTables = new List<Table>();
        allTables.AddRange(_normalTables);
        allTables.AddRange(_acTables);

        foreach (var table in allTables)
        {
            try
            {
                var orders = await _api.GetTableOrdersAsync(table.Id);
                bool hasOrders = orders.Count > 0;
                bool hasToken = _tableTokens.ContainsKey(table.Id);
                table.Status = (hasOrders || hasToken) ? "occupied" : "free";
            }
            catch { /* backend unreachable */ }
        }
        MainThread.BeginInvokeOnMainThread(() => BuildGrid());
    }

    private void BuildGrid()
    {
        FloorContainer.Children.Clear();

        // NORMAL DINING section
        FloorContainer.Children.Add(new Border
        {
            BackgroundColor = Color.FromArgb("#F8F9FA"),
            StrokeShape = new Microsoft.Maui.Controls.Shapes.RoundRectangle { CornerRadius = 6 },
            Stroke = Colors.Transparent,
            Padding = new Thickness(12, 8),
            Content = new Label
            {
                Text = "NORMAL DINING",
                FontSize = 14,
                FontAttributes = FontAttributes.Bold,
                TextColor = Color.FromArgb("#495057")
            }
        });

        int normalCols = 5;
        int normalRows = (int)Math.Ceiling(_normalTables.Count / (double)normalCols);
        var normalGrid = new Grid { ColumnSpacing = 16, RowSpacing = 16 };
        for (int c = 0; c < normalCols; c++)
            normalGrid.ColumnDefinitions.Add(new ColumnDefinition(GridLength.Star));
        for (int r = 0; r < normalRows; r++)
            normalGrid.RowDefinitions.Add(new RowDefinition(GridLength.Auto));
        for (int i = 0; i < _normalTables.Count; i++)
        {
            var card = BuildTableCard(_normalTables[i], false);
            normalGrid.Add(card, i % normalCols, i / normalCols);
        }
        FloorContainer.Children.Add(normalGrid);

        // AC DINING section
        FloorContainer.Children.Add(new Border
        {
            BackgroundColor = Color.FromArgb("#D1ECF1"),
            StrokeShape = new Microsoft.Maui.Controls.Shapes.RoundRectangle { CornerRadius = 6 },
            Stroke = Colors.Transparent,
            Padding = new Thickness(12, 8),
            Margin = new Thickness(0, 8, 0, 0),
            Content = new Label
            {
                Text = "AC DINING ❄️",
                FontSize = 14,
                FontAttributes = FontAttributes.Bold,
                TextColor = Color.FromArgb("#0C5460")
            }
        });

        int acCols = 5;
        int acRows = (int)Math.Ceiling(_acTables.Count / (double)acCols);
        var acGrid = new Grid { ColumnSpacing = 16, RowSpacing = 16 };
        for (int c = 0; c < acCols; c++)
            acGrid.ColumnDefinitions.Add(new ColumnDefinition(GridLength.Star));
        for (int r = 0; r < acRows; r++)
            acGrid.RowDefinitions.Add(new RowDefinition(GridLength.Auto));
        for (int i = 0; i < _acTables.Count; i++)
        {
            var card = BuildTableCard(_acTables[i], true);
            acGrid.Add(card, i % acCols, i / acCols);
        }
        FloorContainer.Children.Add(acGrid);
    }

    private Border BuildTableCard(Table table, bool isAc)
    {
        bool occupied = table.Status == "occupied";
        bool hasToken = _tableTokens.ContainsKey(table.Id);

        Color cardBg;
        Color borderColor;
        if (occupied)
        {
            cardBg = Color.FromArgb("#FFEBEE");
            borderColor = Color.FromArgb("#DC3545");
        }
        else
        {
            cardBg = isAc ? Color.FromArgb("#E3F2FD") : Colors.White;
            borderColor = Color.FromArgb("#DEE2E6");
        }

        var statusLbl = new Label
        {
            Text = occupied ? "OCCUPIED" : "FREE",
            FontSize = 10, FontAttributes = FontAttributes.Bold,
            TextColor = occupied ? Color.FromArgb("#DC3545") : Color.FromArgb("#28A745"),
            HorizontalOptions = LayoutOptions.Center
        };

        var tokenLbl = new Label
        {
            Text = hasToken ? $"Token: {_tableTokens[table.Id]}" : "",
            FontSize = 11, FontAttributes = FontAttributes.Bold,
            TextColor = Color.FromArgb("#1B4332"),
            HorizontalOptions = LayoutOptions.Center
        };

        var openBtn = new Button
        {
            Text = occupied ? "Close Table" : "Open Table",
            BackgroundColor = occupied ? Color.FromArgb("#DC3545") : Color.FromArgb("#1B4332"),
            TextColor = Colors.White,
            CornerRadius = 6, FontSize = 11, HeightRequest = 32,
            Margin = new Thickness(0, 4, 0, 0)
        };
        openBtn.Clicked += async (s, e) =>
        {
            if (!occupied)
                await OpenTableAsync(table);
            else
                await CloseTableAsync(table);
        };

        var qrBtn = new Button
        {
            Text = "Show QR",
            BackgroundColor = Color.FromArgb("#28A745"),
            TextColor = Colors.White,
            CornerRadius = 6, FontSize = 11, HeightRequest = 32,
            IsVisible = hasToken && occupied,
            Margin = new Thickness(0, 4, 0, 0)
        };
        qrBtn.Clicked += (s, e) =>
        {
            if (_tableTokens.TryGetValue(table.Id, out var token))
                ShowQrCode(table, token);
        };

        var card = new Border
        {
            BackgroundColor = cardBg,
            Stroke = borderColor,
            StrokeThickness = occupied ? 2 : 1,
            StrokeShape = new Microsoft.Maui.Controls.Shapes.RoundRectangle { CornerRadius = 12 },
            Padding = new Thickness(14)
        };

        card.Content = new StackLayout
        {
            Spacing = 4, HorizontalOptions = LayoutOptions.Center,
            Children =
            {
                new Label { Text = "🪑", FontSize = 24, HorizontalOptions = LayoutOptions.Center },
                new Label { Text = table.Name, FontSize = 18, FontAttributes = FontAttributes.Bold,
                            TextColor = Color.FromArgb("#212529"), HorizontalOptions = LayoutOptions.Center },
                new Label { Text = $"{table.Capacity} seats", FontSize = 10,
                            TextColor = Color.FromArgb("#555555"), HorizontalOptions = LayoutOptions.Center },
                statusLbl, tokenLbl, openBtn, qrBtn
            }
        };

        return card;
    }

    private async System.Threading.Tasks.Task OpenTableAsync(Table table)
    {
        try
        {
            var body = JsonSerializer.Serialize(new
            {
                outlet_id = OutletId,
                table_id = table.Id
            });
            var res = await _http.PostAsync($"{BackendBase}/tables/open",
                new StringContent(body, Encoding.UTF8, "application/json"));

            if (res.IsSuccessStatusCode)
            {
                var json = await res.Content.ReadAsStringAsync();
                using var doc = JsonDocument.Parse(json);
                var token = doc.RootElement.GetProperty("token").GetString() ?? "";

                _tableTokens[table.Id] = token;
                table.Status = "occupied";
                BuildGrid();

                ShowQrCode(table, token);
            }
            else
            {
                await Application.Current!.Windows[0].Page!.DisplayAlertAsync(
                    "Error", "Could not open table. Is backend running?", "OK");
            }
        }
        catch (Exception ex)
        {
            await Application.Current!.Windows[0].Page!.DisplayAlertAsync(
                "Error", $"Backend not reachable: {ex.Message}", "OK");
        }
    }

    private async System.Threading.Tasks.Task CloseTableAsync(Table table)
    {
        bool confirm = await Application.Current!.Windows[0].Page!.DisplayAlertAsync(
            "Close Table",
            $"Close {table.Name}? The QR code will stop working immediately.",
            "Close Table", "Cancel");

        if (!confirm) return;

        try
        {
            await _http.PostAsync(
                $"{BackendBase}/tables/close/{table.Id}?outlet_id={OutletId}",
                new StringContent("", Encoding.UTF8, "application/json"));
        }
        catch { /* best effort */ }

        _tableTokens.Remove(table.Id);
        table.Status = "free";
        BuildGrid();
    }

    private async void ShowQrCode(Table table, string token)
    {
        var menuUrl = $"{CustomerBase}?token={token}";
        var qrUrl = $"https://api.qrserver.com/v1/create-qr-code/?size=300x300&data={Uri.EscapeDataString(menuUrl)}";

        bool openQr = await Application.Current!.Windows[0].Page!.DisplayAlertAsync(
            $"✅ {table.Name} is Open!",
            $"Token: {token}\n\n" +
            $"Customer URL:\n{menuUrl}\n\n" +
            $"Show this QR on a screen or print it for the table.\n" +
            $"Token expires in 4 hours.\n\n" +
            $"Open QR code in browser?",
            "Open QR", "Close");

        if (openQr)
        {
            await Microsoft.Maui.ApplicationModel.Launcher.OpenAsync(
                new Uri(qrUrl));
        }
    }
}
