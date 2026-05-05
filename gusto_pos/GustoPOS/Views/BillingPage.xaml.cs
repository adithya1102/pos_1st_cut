using System;
using System.Collections.Generic;
using System.Diagnostics;
using System.Linq;
using Microsoft.Maui.Controls;
using Microsoft.Maui.Graphics;
using Microsoft.Maui.Layouts;
using Microsoft.Maui.Dispatching;
using GustoPOS.Models;
using GustoPOS.Services;

namespace GustoPOS.Views;

public partial class BillingPage : ContentView
{
    private readonly ApiService _api;
    private List<string> _allTableIds = new();
    private readonly Dictionary<string, bool> _tableHasOrders = new();
    private readonly Dictionary<string, Button> _tableButtons = new();
    private string? _selectedTable;
    private string _selectedZone = "";
    private bool _billGenerated;
    private IDispatcherTimer? _refreshTimer;
    private int _normalCount = 10;
    private int _acCount = 10;

    public BillingPage(ApiService api)
    {
        InitializeComponent();
        _api = api;
        LoadConfigAndBuildAsync();
        _refreshTimer = Application.Current!.Dispatcher.CreateTimer();
        _refreshTimer.Interval = TimeSpan.FromSeconds(30);
        _refreshTimer.Tick += (s, e) => LoadTableStatusParallelAsync();
        _refreshTimer.Start();
    }

    public void OnTabShown()
    {
        LoadConfigAndBuildAsync();
    }

    private async void LoadConfigAndBuildAsync()
    {
        var config = await _api.GetOutletConfigAsync();
        _normalCount = config.NormalTableCount;
        _acCount = config.AcTableCount;
        RebuildTableIds();
        BuildTableGrid();
        LoadTableStatusParallelAsync();
    }

    private void RebuildTableIds()
    {
        _allTableIds.Clear();
        for (int i = 1; i <= _normalCount; i++) _allTableIds.Add($"N-{i}");
        for (int i = 1; i <= _acCount; i++) _allTableIds.Add($"A-{i}");
    }

    private void BuildTableGrid()
    {
        TableGridContainer.Children.Clear();
        _tableButtons.Clear();

        // NORMAL DINING header
        TableGridContainer.Children.Add(new Border
        {
            BackgroundColor = Color.FromArgb("#F8F9FA"),
            StrokeShape = new Microsoft.Maui.Controls.Shapes.RoundRectangle { CornerRadius = 4 },
            Stroke = Colors.Transparent,
            Padding = new Thickness(8, 4),
            Content = new Label
            {
                Text = "NORMAL DINING",
                FontSize = 12,
                FontAttributes = FontAttributes.Bold,
                TextColor = Color.FromArgb("#495057")
            }
        });

        // Normal table buttons
        var normalFlex = new FlexLayout { Wrap = FlexWrap.Wrap, JustifyContent = FlexJustify.Start, AlignItems = FlexAlignItems.Start };
        for (int i = 1; i <= _normalCount; i++)
        {
            var tid = $"N-{i}";
            var btn = CreateTableButton(tid);
            _tableButtons[tid] = btn;
            normalFlex.Children.Add(btn);
        }
        TableGridContainer.Children.Add(normalFlex);

        // AC DINING header
        TableGridContainer.Children.Add(new Border
        {
            BackgroundColor = Color.FromArgb("#D1ECF1"),
            StrokeShape = new Microsoft.Maui.Controls.Shapes.RoundRectangle { CornerRadius = 4 },
            Stroke = Colors.Transparent,
            Padding = new Thickness(8, 4),
            Margin = new Thickness(0, 8, 0, 0),
            Content = new Label
            {
                Text = "AC DINING ❄️",
                FontSize = 12,
                FontAttributes = FontAttributes.Bold,
                TextColor = Color.FromArgb("#0C5460")
            }
        });

        // AC table buttons
        var acFlex = new FlexLayout { Wrap = FlexWrap.Wrap, JustifyContent = FlexJustify.Start, AlignItems = FlexAlignItems.Start };
        for (int i = 1; i <= _acCount; i++)
        {
            var tid = $"A-{i}";
            var btn = CreateTableButton(tid);
            _tableButtons[tid] = btn;
            acFlex.Children.Add(btn);
        }
        TableGridContainer.Children.Add(acFlex);
    }

    private Button CreateTableButton(string tid)
    {
        var btn = new Button
        {
            Text = tid,
            WidthRequest = 100,
            HeightRequest = 60,
            CornerRadius = 10,
            FontSize = 14,
            FontAttributes = FontAttributes.Bold,
            BackgroundColor = Colors.White,
            TextColor = Color.FromArgb("#212529"),
            BorderColor = Color.FromArgb("#DEE2E6"),
            BorderWidth = 1,
            Margin = new Thickness(4),
        };
        btn.Clicked += OnTableButtonClicked;
        return btn;
    }

    private async void LoadTableStatusParallelAsync()
    {
        var tasks = _allTableIds.Select(async tid =>
        {
            try
            {
                var orders = await _api.GetTableOrdersAsync(tid);
                return (tid, hasOrders: orders.Count > 0);
            }
            catch
            {
                return (tid, hasOrders: false);
            }
        });

        var results = await Task.WhenAll(tasks);

        MainThread.BeginInvokeOnMainThread(() =>
        {
            foreach (var (tid, hasOrders) in results)
            {
                _tableHasOrders[tid] = hasOrders;
                if (_tableButtons.TryGetValue(tid, out var btn))
                {
                    bool isSelected = _selectedTable == tid;
                    if (hasOrders)
                    {
                        btn.BackgroundColor = Color.FromArgb("#E8F5E9");
                        btn.TextColor = Color.FromArgb("#212529");
                        btn.BorderColor = Color.FromArgb("#28A745");
                        btn.BorderWidth = isSelected ? 2 : 1.5;
                    }
                    else
                    {
                        btn.BackgroundColor = Colors.White;
                        btn.TextColor = Color.FromArgb("#212529");
                        btn.BorderColor = isSelected ? Colors.Black : Color.FromArgb("#DEE2E6");
                        btn.BorderWidth = isSelected ? 2 : 1;
                    }
                }
            }
        });
    }

    private async void OnTableButtonClicked(object? sender, EventArgs e)
    {
        if (sender is not Button btn) return;
        _selectedTable = btn.Text;
        _billGenerated = false;

        if (_selectedTable.StartsWith("N-"))
            _selectedZone = "normal";
        else if (_selectedTable.StartsWith("A-"))
            _selectedZone = "ac";
        else
            _selectedZone = "";

        foreach (var kvp in _tableButtons)
        {
            var b = kvp.Value;
            bool has = _tableHasOrders.TryGetValue(kvp.Key, out var v) && v;
            bool isSel = kvp.Key == _selectedTable;
            if (has)
            {
                b.BackgroundColor = Color.FromArgb("#E8F5E9");
                b.TextColor = Color.FromArgb("#212529");
                b.BorderColor = isSel ? Colors.Black : Color.FromArgb("#28A745");
                b.BorderWidth = isSel ? 2.5 : 1.5;
            }
            else
            {
                b.BackgroundColor = Colors.White;
                b.TextColor = Color.FromArgb("#212529");
                b.BorderColor = isSel ? Colors.Black : Color.FromArgb("#DEE2E6");
                b.BorderWidth = isSel ? 2.5 : 1;
            }
        }

        await LoadOrdersForTable(_selectedTable);
    }

    private async Task LoadOrdersForTable(string tableId)
    {
        var orders = await _api.GetTableOrdersAsync(tableId);
        SummaryPanel.Children.Clear();
        EmptyState.IsVisible = false;

        if (!orders.Any())
        {
            SummaryPanel.Children.Add(new StackLayout
            {
                HorizontalOptions = LayoutOptions.Center,
                VerticalOptions = LayoutOptions.Center,
                Spacing = 8,
                Children =
                {
                    new Label { Text = "✅", FontSize = 36, HorizontalOptions = LayoutOptions.Center, Margin = new Thickness(0,30,0,0) },
                    new Label { Text = "No pending orders", FontSize = 16, FontAttributes = FontAttributes.Bold, HorizontalOptions = LayoutOptions.Center },
                    new Label { Text = $"Table {tableId} has no unpaid orders.", TextColor = Color.FromArgb("#6C757D"), HorizontalOptions = LayoutOptions.Center },
                }
            });
            return;
        }

        // Header with zone info
        var zoneInfo = _selectedZone == "ac" ? "❄️ AC Table" : "Table";
        SummaryPanel.Children.Add(new Label
        {
            Text = $"{zoneInfo} {tableId} — Current Orders",
            FontSize = 18, FontAttributes = FontAttributes.Bold, TextColor = Colors.Black,
        });

        // Merge all items from all orders
        var mergedItems = new List<(string Name, int Qty, decimal Amount)>();
        foreach (var order in orders)
        {
            if (order.Items.Any())
            {
                foreach (var item in order.Items)
                {
                    var name = item.NameSnap ?? "Item";
                    var qty = item.Quantity;
                    var amt = (item.PriceSnap ?? 0) * qty;
                    var existing = mergedItems.FindIndex(x => x.Name == name);
                    if (existing >= 0)
                    {
                        var ex = mergedItems[existing];
                        mergedItems[existing] = (ex.Name, ex.Qty + qty, ex.Amount + amt);
                    }
                    else
                        mergedItems.Add((name, qty, amt));
                }
            }
            else
            {
                mergedItems.Add(($"Order #{order.ReadableId}", 1, order.TotalAmount));
            }
        }

        // Item list
        foreach (var item in mergedItems)
        {
            var row = new Border
            {
                BackgroundColor = Colors.White,
                Stroke = Color.FromArgb("#EEEEEE"),
                StrokeShape = new Microsoft.Maui.Controls.Shapes.RoundRectangle { CornerRadius = 8 },
                Padding = new Thickness(12, 8),
                Content = new Grid
                {
                    ColumnDefinitions = { new ColumnDefinition(GridLength.Star), new ColumnDefinition(GridLength.Auto), new ColumnDefinition(GridLength.Auto) },
                    Children =
                    {
                        new Label { Text = item.Name, FontSize = 13, TextColor = Colors.Black, VerticalOptions = LayoutOptions.Center },
                        new Label { Text = $"x{item.Qty}", FontSize = 12, TextColor = Color.FromArgb("#6C757D"), VerticalOptions = LayoutOptions.Center, Margin = new Thickness(12,0) }.Apply(l => Grid.SetColumn(l, 1)),
                        new Label { Text = $"₹{item.Amount:F0}", FontSize = 13, FontAttributes = FontAttributes.Bold, TextColor = Colors.Black, VerticalOptions = LayoutOptions.Center }.Apply(l => Grid.SetColumn(l, 2)),
                    }
                }
            };
            SummaryPanel.Children.Add(row);
        }

        // Divider
        SummaryPanel.Children.Add(new BoxView { Color = Color.FromArgb("#DEE2E6"), HeightRequest = 1, Margin = new Thickness(0, 8) });

        // Totals
        var subtotal = mergedItems.Sum(i => i.Amount);
        var gst = Math.Round(subtotal * 0.05m, 2);
        var grandTotal = subtotal + gst;

        SummaryPanel.Children.Add(CreateTotalRow("Subtotal:", $"₹{subtotal:F0}", 13, false));
        SummaryPanel.Children.Add(CreateTotalRow("GST 5%:", $"₹{gst:F0}", 13, false));

        SummaryPanel.Children.Add(new BoxView { Color = Color.FromArgb("#DEE2E6"), HeightRequest = 1, Margin = new Thickness(0, 4) });

        var grandLabel = CreateTotalRow("GRAND TOTAL:", $"₹{grandTotal:F0}", 18, true);
        SummaryPanel.Children.Add(grandLabel);

        // Generate Bill button
        var billBtn = new Button
        {
            Text = "Generate Bill & Save PDF",
            BackgroundColor = Color.FromArgb("#1B4332"),
            TextColor = Colors.White,
            FontAttributes = FontAttributes.Bold,
            FontSize = 14,
            CornerRadius = 10,
            HeightRequest = 48,
            Margin = new Thickness(0, 12, 0, 0),
        };
        billBtn.Clicked += OnGenerateBillClicked;
        SummaryPanel.Children.Add(billBtn);

        // Settle button (hidden until bill generated)
        var settleBtn = new Button
        {
            Text = "Settle & Close Table",
            BackgroundColor = Color.FromArgb("#28A745"),
            TextColor = Colors.White,
            FontAttributes = FontAttributes.Bold,
            FontSize = 14,
            CornerRadius = 10,
            HeightRequest = 48,
            IsVisible = false,
            Margin = new Thickness(0, 4, 0, 0),
            AutomationId = "SettleBtn",
        };
        settleBtn.Clicked += OnSettleClicked;
        SummaryPanel.Children.Add(settleBtn);
    }

    private Grid CreateTotalRow(string label, string value, int size, bool bold)
    {
        var g = new Grid { ColumnDefinitions = { new ColumnDefinition(GridLength.Star), new ColumnDefinition(GridLength.Auto) } };
        g.Children.Add(new Label { Text = label, FontSize = size, FontAttributes = bold ? FontAttributes.Bold : FontAttributes.None, TextColor = Colors.Black });
        var valLabel = new Label { Text = value, FontSize = size, FontAttributes = FontAttributes.Bold, TextColor = bold ? Color.FromArgb("#28A745") : Colors.Black };
        Grid.SetColumn(valLabel, 1);
        g.Children.Add(valLabel);
        return g;
    }

    private async void OnGenerateBillClicked(object? sender, EventArgs e)
    {
        if (_selectedTable == null) return;
        if (sender is Button btn) btn.IsEnabled = false;

        var result = await _api.GenerateBillAsync(_selectedTable);
        if (result != null)
        {
            _billGenerated = true;
            var zoneLabel = _selectedZone == "ac" ? "AC Dining ❄️" : "Regular Dining";
            await Application.Current!.Windows[0].Page!.DisplayAlertAsync(
                "Bill Saved!",
                $"{zoneLabel}\nPDF saved. Total: ₹{result.Total:F0}\nOpening PDF...",
                "OK");

            try
            {
                Process.Start(new ProcessStartInfo(result.PdfPath) { UseShellExecute = true });
            }
            catch { /* PDF viewer not available */ }

            var settleBtn = SummaryPanel.Children.OfType<Button>().FirstOrDefault(b => b.AutomationId == "SettleBtn");
            if (settleBtn != null) settleBtn.IsVisible = true;
        }
        else
        {
            await Application.Current!.Windows[0].Page!.DisplayAlertAsync("Error", "Could not generate bill.", "OK");
        }

        if (sender is Button b2) b2.IsEnabled = true;
    }

    private async void OnSettleClicked(object? sender, EventArgs e)
    {
        if (_selectedTable == null) return;
        if (sender is Button btn) btn.IsEnabled = false;

        var result = await _api.SettleTableAsync(_selectedTable);
        if (result != null)
        {
            await Application.Current!.Windows[0].Page!.DisplayAlertAsync(
                "Table Settled",
                $"Table {_selectedTable} settled.\nTotal collected: ₹{result.TotalAmount:F0}",
                "OK");

            _billGenerated = false;
            LoadTableStatusParallelAsync();
            await LoadOrdersForTable(_selectedTable);
        }
        else
        {
            await Application.Current!.Windows[0].Page!.DisplayAlertAsync("Error", "Could not settle table.", "OK");
            if (sender is Button b2) b2.IsEnabled = true;
        }
    }
}

internal static class ViewExtensions
{
    public static T Apply<T>(this T view, Action<T> action) where T : View
    {
        action(view);
        return view;
    }
}
