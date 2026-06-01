using System.Diagnostics;
using GustoWaiter.Models;
using GustoWaiter.Services;

namespace GustoWaiter.Views;

public class OrderView : ContentView {
    private readonly ApiService _api;
    private readonly DashboardPage _dash;

    // Zone + table selectors
    private string _currentZone = "normal";
    private string _table = "";
    private Button _regularBtn = new();
    private Button _acBtn      = new();
    private readonly HorizontalStackLayout _normalTablesRow = new() { Spacing = 6 };
    private readonly HorizontalStackLayout _acTablesRow     = new() { Spacing = 6, IsVisible = false };
    private readonly List<Button> _normalTableButtons = new();
    private readonly List<Button> _acTableButtons     = new();

    // Menu cache for MenuPickerPage (preloaded in background)
    private ZoneMenuResponse? _normalMenuCache;
    private ZoneMenuResponse? _acMenuCache;

    // Canvas views
    private readonly Label _emptyLabel = new() {
        HorizontalOptions = LayoutOptions.Center, VerticalOptions = LayoutOptions.Center,
        HorizontalTextAlignment = TextAlignment.Center,
        FontSize = 15, TextColor = Color.FromArgb("#9E9E9E"),
        Margin = new Thickness(24)
    };
    private readonly CollectionView _orderCv = new();

    private bool _loaded;
    private bool _refreshing;

    // ── Constructor ───────────────────────────────────────────────────────────

    public OrderView(ApiService api, DashboardPage dash) {
        _api = api; _dash = dash;
        BuildLayout();
        Loaded += OnLoaded;
    }

    // ── First load ────────────────────────────────────────────────────────────

    private async void OnLoaded(object? sender, EventArgs e) {
        if (_loaded) return;
        _loaded = true;
        try {
            var config = await _api.GetOutletConfigAsync();
            await MainThread.InvokeOnMainThreadAsync(() => BuildTableButtons(config));
            ShowEmptyState("Select a table above\nto view its live order.");
            _ = PreloadMenusAsync();
        } catch (Exception ex) {
            CrashLogger.Log(ex, "OrderView.OnLoaded");
        }
    }

    private async Task PreloadMenusAsync() {
        try {
            var normal = await _api.GetMenuByZoneAsync("normal");
            if (normal != null) _normalMenuCache = normal;
            var ac = await _api.GetMenuByZoneAsync("ac");
            if (ac != null) _acMenuCache = ac;
        } catch (Exception ex) {
            CrashLogger.Log(ex, "OrderView.PreloadMenus");
        }
    }

    // ── Layout ────────────────────────────────────────────────────────────────

    private void BuildLayout() {
        _regularBtn = new Button {
            Text = "REGULAR", FontSize = 13, FontAttributes = FontAttributes.Bold,
            BackgroundColor = Color.FromArgb("#495057"), TextColor = Colors.White,
            CornerRadius = 20, HeightRequest = 40, Padding = new Thickness(20, 0)
        };
        _acBtn = new Button {
            Text = "AC ❄️", FontSize = 13, FontAttributes = FontAttributes.Bold,
            BackgroundColor = Colors.White, TextColor = Color.FromArgb("#212529"),
            CornerRadius = 20, HeightRequest = 40, Padding = new Thickness(20, 0),
            BorderColor = Color.FromArgb("#DEE2E6"), BorderWidth = 1
        };
        _regularBtn.Clicked += async (_, _) => { try { await SwitchZone("normal"); } catch (Exception ex) { CrashLogger.Log(ex, "OrderView.RegularBtn"); } };
        _acBtn.Clicked      += async (_, _) => { try { await SwitchZone("ac");     } catch (Exception ex) { CrashLogger.Log(ex, "OrderView.AcBtn"); } };

        var zoneRow = new HorizontalStackLayout {
            Spacing = 10, Margin = new Thickness(16, 10, 16, 6),
            Children = { _regularBtn, _acBtn }
        };

        var tableScroll = new ScrollView {
            Orientation = ScrollOrientation.Horizontal,
            HorizontalScrollBarVisibility = ScrollBarVisibility.Never,
            HeightRequest = 54, Margin = new Thickness(16, 0, 16, 8),
            Content = new Grid { Children = { _normalTablesRow, _acTablesRow } }
        };

        var header = new VerticalStackLayout {
            BackgroundColor = Colors.White, Spacing = 0,
            Children = { zoneRow, tableScroll }
        };
        header.Shadow = new Shadow { Brush = Brush.Black, Offset = new Point(0, 2), Radius = 8, Opacity = 0.06f };

        // CollectionView — 2-column grid layout, no nested scroll
        _orderCv.ItemsLayout = new GridItemsLayout(2, ItemsLayoutOrientation.Vertical) {
            VerticalItemSpacing = 10, HorizontalItemSpacing = 10
        };
        _orderCv.ItemTemplate = new DataTemplate(() => BuildOrderItemCell());
        _orderCv.BackgroundColor = Colors.White;
        _orderCv.Margin = new Thickness(12);

        // Canvas area: white background, both empty label and CV overlaid via Grid
        var canvas = new Grid {
            BackgroundColor = Colors.White,
            Children = { _emptyLabel, _orderCv }
        };
        _emptyLabel.IsVisible = true;
        _orderCv.IsVisible = false;

        // FAB — floats in same grid cell as canvas (Grid stacks children)
        var fab = new Button {
            Text = "+", FontSize = 28, FontAttributes = FontAttributes.Bold,
            BackgroundColor = Color.FromArgb("#28A745"), TextColor = Colors.White,
            CornerRadius = 32, WidthRequest = 64, HeightRequest = 64,
            HorizontalOptions = LayoutOptions.End, VerticalOptions = LayoutOptions.End,
            Margin = new Thickness(0, 0, 24, 24),
            Shadow = new Shadow { Brush = Brush.Black, Offset = new Point(0, 4), Radius = 12, Opacity = 0.3f }
        };
        fab.Clicked += OnFabClicked;

        var root = new Grid {
            RowDefinitions = { new(GridLength.Auto), new(GridLength.Star) },
            BackgroundColor = Colors.White
        };
        root.Add(header, 0, 0);
        root.Add(canvas,  0, 1);
        root.Add(fab,     0, 1);  // overlaid on the same row as canvas

        Content = root;
    }

    // ── Table buttons ─────────────────────────────────────────────────────────

    private void BuildTableButtons(OutletConfig config) {
        _normalTablesRow.Children.Clear();
        _normalTableButtons.Clear();
        for (int i = 1; i <= config.NormalTableCount; i++)
            AddTableButton($"N-{i}", _normalTablesRow, _normalTableButtons);

        _acTablesRow.Children.Clear();
        _acTableButtons.Clear();
        for (int i = 1; i <= config.AcTableCount; i++)
            AddTableButton($"A-{i}", _acTablesRow, _acTableButtons);
    }

    private void AddTableButton(string tableId, HorizontalStackLayout row, List<Button> list) {
        var btn = new Button {
            Text = tableId, FontSize = 12,
            Padding = new Thickness(10, 6), Margin = new Thickness(3, 0),
            CornerRadius = 8,
            BackgroundColor = Color.FromArgb("#FFFFFF"),
            TextColor = Color.FromArgb("#212529"),
            BorderColor = Color.FromArgb("#DEE2E6"), BorderWidth = 1
        };
        btn.Clicked += async (_, _) => {
            _table = tableId;
            HighlightTableBtn(btn, list);
            await RefreshOrderCanvasAsync();
        };
        list.Add(btn);
        row.Children.Add(btn);
    }

    private static void HighlightTableBtn(Button active, List<Button> list) {
        foreach (var b in list) {
            b.BackgroundColor = Color.FromArgb("#FFFFFF");
            b.TextColor = Color.FromArgb("#212529");
        }
        active.BackgroundColor = Color.FromArgb("#1B4332");
        active.TextColor = Colors.White;
    }

    // ── Zone switch ───────────────────────────────────────────────────────────

    private async Task SwitchZone(string zone) {
        _currentZone = zone;
        _table = "";
        await MainThread.InvokeOnMainThreadAsync(() => {
            if (zone == "normal") {
                _regularBtn.BackgroundColor = Color.FromArgb("#495057");
                _regularBtn.TextColor = Colors.White;
                _regularBtn.BorderWidth = 0;
                _acBtn.BackgroundColor = Colors.White;
                _acBtn.TextColor = Color.FromArgb("#212529");
                _acBtn.BorderColor = Color.FromArgb("#DEE2E6");
                _acBtn.BorderWidth = 1;
                _normalTablesRow.IsVisible = true;
                _acTablesRow.IsVisible = false;
            } else {
                _acBtn.BackgroundColor = Color.FromArgb("#0C5460");
                _acBtn.TextColor = Colors.White;
                _acBtn.BorderWidth = 0;
                _regularBtn.BackgroundColor = Colors.White;
                _regularBtn.TextColor = Color.FromArgb("#212529");
                _regularBtn.BorderColor = Color.FromArgb("#DEE2E6");
                _regularBtn.BorderWidth = 1;
                _normalTablesRow.IsVisible = false;
                _acTablesRow.IsVisible = true;
            }
            ShowEmptyState("Select a table above\nto view its live order.");
        });
    }

    // ── Order canvas ──────────────────────────────────────────────────────────

    private async Task RefreshOrderCanvasAsync() {
        if (_refreshing) return;
        _refreshing = true;
        try {
            if (string.IsNullOrEmpty(_table)) {
                await MainThread.InvokeOnMainThreadAsync(() =>
                    ShowEmptyState("Select a table above\nto view its live order."));
                return;
            }

            TableActiveOrder? order = null;
            try { order = await _api.GetTableActiveOrderSummaryAsync(_table); }
            catch (Exception ex) { Debug.WriteLine($"RefreshOrderCanvas fetch: {ex.Message}"); }

            await MainThread.InvokeOnMainThreadAsync(() => {
                if (order == null || !order.Items.Any()) {
                    ShowEmptyState($"No active orders for {_table}.\nTap  +  to place a new order.");
                    return;
                }

                var displays = order.Items
                    .Select((item, idx) => new OrderItemDisplay {
                        Serial = idx + 1,
                        Name   = item.Name,
                        Price  = item.UnitPrice,
                        OrderStatus = order.OrderStatus
                    })
                    .ToList();

                _orderCv.ItemsSource = displays;
                _emptyLabel.IsVisible  = false;
                _orderCv.IsVisible     = true;
            });
        } catch (Exception ex) {
            CrashLogger.Log(ex, "OrderView.RefreshOrderCanvas");
        } finally {
            _refreshing = false;
        }
    }

    private void ShowEmptyState(string message) {
        _emptyLabel.Text = message;
        _emptyLabel.IsVisible  = true;
        _orderCv.IsVisible     = false;
        _orderCv.ItemsSource   = null;
    }

    // ── FAB ───────────────────────────────────────────────────────────────────

    private async void OnFabClicked(object? sender, EventArgs e) {
        if (string.IsNullOrEmpty(_table)) {
            await Application.Current!.Windows[0].Page!.DisplayAlertAsync(
                "No Table Selected", "Please select a table before placing an order.", "OK");
            return;
        }
        var cache = _currentZone == "normal" ? _normalMenuCache : _acMenuCache;
        var modal = new MenuPickerPage(_api, _currentZone, _table, cache);
        modal.OrderPlaced += async () => await RefreshOrderCanvasAsync();
        await Application.Current!.Windows[0].Page!.Navigation.PushModalAsync(modal, animated: true);
    }

    // ── CollectionView DataTemplate ───────────────────────────────────────────

    private static object BuildOrderItemCell() {
        var serialLbl = new Label {
            FontSize = 11, FontAttributes = FontAttributes.Bold,
            TextColor = Color.FromArgb("#1B4332"),
            VerticalOptions = LayoutOptions.Center
        };
        serialLbl.SetBinding(Label.TextProperty, nameof(OrderItemDisplay.SerialDisplay));

        var nameLbl = new Label {
            FontSize = 13, FontAttributes = FontAttributes.Bold,
            TextColor = Color.FromArgb("#212529"),
            LineBreakMode = LineBreakMode.TailTruncation,
            VerticalOptions = LayoutOptions.Center,
            Margin = new Thickness(6, 0, 0, 0)
        };
        nameLbl.SetBinding(Label.TextProperty, nameof(OrderItemDisplay.Name));

        var dotsLbl = new Label {
            Text = "·  ·  ·  ·  ·  ·  ·  ·  ·  ·",
            TextColor = Color.FromArgb("#CCCCCC"), FontSize = 10,
            HorizontalOptions = LayoutOptions.Fill,
            LineBreakMode = LineBreakMode.NoWrap, MaxLines = 1
        };

        var statusDot = new Label {
            FontSize = 16, VerticalOptions = LayoutOptions.Center,
            Margin = new Thickness(6, 0)
        };
        statusDot.SetBinding(Label.TextProperty, nameof(OrderItemDisplay.StatusDot));

        var priceLbl = new Label {
            FontSize = 12, FontAttributes = FontAttributes.Bold,
            TextColor = Color.FromArgb("#1B4332"),
            VerticalOptions = LayoutOptions.Center
        };
        priceLbl.SetBinding(Label.TextProperty, nameof(OrderItemDisplay.PriceDisplay));

        // Row 1: serial + name
        var row1 = new Grid {
            ColumnDefinitions = { new(GridLength.Auto), new(GridLength.Star) }
        };
        row1.Add(serialLbl, 0, 0);
        row1.Add(nameLbl,   1, 0);

        // Row 2: dots + status dot + price
        var row2 = new Grid {
            ColumnDefinitions = { new(GridLength.Star), new(GridLength.Auto), new(GridLength.Auto) }
        };
        row2.Add(dotsLbl,   0, 0);
        row2.Add(statusDot, 1, 0);
        row2.Add(priceLbl,  2, 0);

        var border = new Border {
            BackgroundColor = Colors.White,
            StrokeShape = new Microsoft.Maui.Controls.Shapes.RoundRectangle { CornerRadius = 10 },
            StrokeThickness = 1, Stroke = Color.FromArgb("#ECECEC"),
            Padding = new Thickness(10, 8),
            Content = new StackLayout { Spacing = 6, Children = { row1, row2 } }
        };

        return border;
    }
}
