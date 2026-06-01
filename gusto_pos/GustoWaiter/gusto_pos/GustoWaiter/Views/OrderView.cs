using System.Diagnostics;
using GustoWaiter.Models;
using GustoWaiter.Services;

namespace GustoWaiter.Views;

public class OrderView : ContentView {
    private readonly ApiService _api;
    private readonly DashboardPage _dash;

    // Zone + table
    private string _currentZone = "normal";
    private string _table = "";
    private Button _regularBtn = new();
    private Button _acBtn      = new();
    private readonly HorizontalStackLayout _normalTablesRow = new() { Spacing = 6 };
    private readonly HorizontalStackLayout _acTablesRow     = new() { Spacing = 6, IsVisible = false };
    private readonly List<Button> _normalTableButtons = new();
    private readonly List<Button> _acTableButtons     = new();

    // Menu cache
    private ZoneMenuResponse? _normalMenuCache;
    private ZoneMenuResponse? _acMenuCache;
    private List<MenuCategory> _categories = new();

    // Menu UI
    private readonly StackLayout _menuStack = new() { Spacing = 0 };
    private readonly SearchBar _searchBar = new();
    private readonly Button _vegAll = new(), _vegVeg = new(), _vegNon = new();
    private readonly HorizontalStackLayout _catRow = new() { Spacing = 6, Padding = new Thickness(12, 0) };
    private readonly List<Button> _catBtns = new();
    private string _searchText = "";
    private string _vegFilter = "All";
    private string _selectedCat = "All";
    private bool _isRendering;
    private CancellationTokenSource? _debounceCts;

    // Cart
    private readonly List<CartItem> _cart = new();
    private readonly Label _cartBadge = new();
    private readonly Button _placeBtn = new();

    // Pending stack (local manual fulfillment tracker — waiter clears items as served)
    private readonly VerticalStackLayout _pendingStack = new() { Spacing = 0 };
    private readonly Label _pendingEmptyLabel = new();

    // Canvas visibility
    private readonly Grid _menuCanvas = new();
    private Grid _floatingPendingPanel = new();
    private Button _viewActiveBtn = new();
    private readonly Label _emptyLabel = new() {
        HorizontalOptions = LayoutOptions.Center, VerticalOptions = LayoutOptions.Center,
        HorizontalTextAlignment = TextAlignment.Center,
        FontSize = 15, TextColor = Color.FromArgb("#9E9E9E"),
        Margin = new Thickness(24)
    };

    private bool _loaded;

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
            await PreloadMenusAsync();
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
            if (!string.IsNullOrEmpty(_table))
                await MainThread.InvokeOnMainThreadAsync(ShowMenuCanvas);
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

        BuildMenuCanvas();
        _menuCanvas.IsVisible = false;

        _emptyLabel.Text = "Select a table above to start an order.";
        _emptyLabel.IsVisible = true;

        var root = new Grid {
            RowDefinitions = { new(GridLength.Auto), new(GridLength.Star) },
            BackgroundColor = Colors.White
        };
        root.Add(header,      0, 0);
        root.Add(_emptyLabel, 0, 1);
        root.Add(_menuCanvas, 0, 1);  // overlaid on same row

        Content = root;
    }

    private void BuildMenuCanvas() {
        // Search bar + veg filter + category strip
        _searchBar.Placeholder = "Search dishes...";
        _searchBar.PlaceholderColor = Color.FromArgb("#AAAAAA");
        _searchBar.BackgroundColor = Colors.White;
        _searchBar.TextColor = Colors.Black;
        _searchBar.Margin = new Thickness(12, 8, 12, 4);
        _searchBar.TextChanged += OnSearchTextChanged;

        ConfigureVegBtn(_vegAll, "All");
        ConfigureVegBtn(_vegVeg, "Veg");
        ConfigureVegBtn(_vegNon, "Non-Veg");
        _vegAll.Clicked += (_, _) => ApplyVegFilter("All");
        _vegVeg.Clicked += (_, _) => ApplyVegFilter("Veg");
        _vegNon.Clicked += (_, _) => ApplyVegFilter("Non-Veg");
        UpdateVegBtnStyles();

        _viewActiveBtn = new Button {
            Text = "📋 Active Items", FontSize = 11, CornerRadius = 8, HeightRequest = 34,
            Padding = new Thickness(12, 0),
            BackgroundColor = Color.FromArgb("#1B4332"), TextColor = Colors.White
        };
        _viewActiveBtn.Clicked += (_, _) => {
            _floatingPendingPanel.IsVisible = true;
            _ = LoadPendingItemsAsync();
        };

        var vegBtnRow = new HorizontalStackLayout {
            Spacing = 8, VerticalOptions = LayoutOptions.Center,
            Children = { _vegAll, _vegVeg, _vegNon }
        };

        var filterBarGrid = new Grid {
            Margin = new Thickness(12, 4, 12, 8), ColumnSpacing = 8,
            ColumnDefinitions = { new(GridLength.Star), new(GridLength.Auto) }
        };
        filterBarGrid.Add(vegBtnRow, 0, 0);
        filterBarGrid.Add(_viewActiveBtn, 1, 0);

        var catScroll = new ScrollView {
            Orientation = ScrollOrientation.Horizontal,
            HorizontalScrollBarVisibility = ScrollBarVisibility.Never,
            HeightRequest = 44, Margin = new Thickness(0, 0, 0, 4),
            Content = _catRow
        };

        var searchPanel = new VerticalStackLayout {
            BackgroundColor = Colors.White, Spacing = 0,
            Children = { _searchBar, filterBarGrid, catScroll }
        };
        searchPanel.Shadow = new Shadow { Brush = Brush.Black, Offset = new Point(0, 2), Radius = 6, Opacity = 0.06f };

        // Menu scroll (fluid left column)
        var menuScroll = new ScrollView {
            Content = new StackLayout { Padding = new Thickness(12, 4, 12, 12), Children = { _menuStack } }
        };

        // Cart footer (scoped to the fluid column, not spanning full width)
        _cartBadge.Text = "0 items in cart";
        _cartBadge.FontSize = 12;
        _cartBadge.TextColor = Color.FromArgb("#6C757D");
        _cartBadge.HorizontalOptions = LayoutOptions.Center;
        _cartBadge.Margin = new Thickness(0, 0, 0, 4);

        _placeBtn.Text = "Place Order";
        _placeBtn.BackgroundColor = Color.FromArgb("#28A745");
        _placeBtn.TextColor = Colors.White;
        _placeBtn.FontSize = 16;
        _placeBtn.FontAttributes = FontAttributes.Bold;
        _placeBtn.CornerRadius = 10;
        _placeBtn.HeightRequest = 52;
        _placeBtn.IsEnabled = false;
        _placeBtn.Clicked += OnPlaceOrder;

        var footer = new Grid {
            BackgroundColor = Colors.White,
            Padding = new Thickness(16, 10, 16, 16),
            RowDefinitions = { new(GridLength.Auto), new(GridLength.Auto) }
        };
        footer.Shadow = new Shadow { Brush = Brush.Black, Offset = new Point(0, -2), Radius = 8, Opacity = 0.08f };
        footer.Add(_cartBadge, 0, 0);
        footer.Add(_placeBtn,  0, 1);

        // Left fluid column: search panel + scrollable menu list + cart footer stacked vertically
        var leftColumn = new Grid {
            BackgroundColor = Colors.White,
            RowDefinitions = {
                new(GridLength.Auto),
                new(GridLength.Star),
                new(GridLength.Auto)
            }
        };
        leftColumn.Add(searchPanel, 0, 0);
        leftColumn.Add(menuScroll,  0, 1);
        leftColumn.Add(footer,      0, 2);

        // Build the floating pending overlay (anchored right, overlaid on menu)
        BuildFloatingPendingPanel();

        // Single fluid column: full-width menu browser with floating overlay on top
        _menuCanvas.ColumnDefinitions.Add(new ColumnDefinition(GridLength.Star));
        _menuCanvas.RowDefinitions.Add(new RowDefinition(GridLength.Star));
        _menuCanvas.BackgroundColor = Color.FromArgb("#F8F9FA");
        _menuCanvas.Add(leftColumn,            0, 0);
        _menuCanvas.Add(_floatingPendingPanel, 0, 0); // overlay: same cell, anchored right
    }

    private void BuildFloatingPendingPanel() {
        var closeBtn = new Button {
            Text = "✕", FontSize = 14, BackgroundColor = Colors.Transparent,
            TextColor = Colors.White, Padding = new Thickness(0),
            WidthRequest = 32, HeightRequest = 32
        };
        closeBtn.Clicked += (_, _) => { _floatingPendingPanel.IsVisible = false; };

        var refreshBtn = new Button {
            Text = "↻", FontSize = 16, BackgroundColor = Colors.Transparent,
            TextColor = Colors.White, Padding = new Thickness(0),
            WidthRequest = 32, HeightRequest = 32
        };
        refreshBtn.Clicked += async (_, _) => {
            try { await LoadPendingItemsAsync(); }
            catch (Exception ex) { CrashLogger.Log(ex, "OrderView.PendingRefresh"); }
        };

        var panelHeader = new Grid {
            BackgroundColor = Color.FromArgb("#1B4332"), Padding = new Thickness(12, 8),
            ColumnDefinitions = { new(GridLength.Star), new(GridLength.Auto), new(GridLength.Auto) }
        };
        panelHeader.Add(new Label {
            Text = "📋 Pending Items", FontSize = 13, FontAttributes = FontAttributes.Bold,
            TextColor = Colors.White, VerticalOptions = LayoutOptions.Center
        }, 0, 0);
        panelHeader.Add(refreshBtn, 1, 0);
        panelHeader.Add(closeBtn,   2, 0);

        _pendingEmptyLabel.Text = "No active orders";
        _pendingEmptyLabel.FontSize = 12;
        _pendingEmptyLabel.TextColor = Color.FromArgb("#9E9E9E");
        _pendingEmptyLabel.HorizontalOptions = LayoutOptions.Center;
        _pendingEmptyLabel.Margin = new Thickness(0, 24);
        _pendingEmptyLabel.IsVisible = true;

        var pendingContent = new StackLayout {
            Padding = new Thickness(0, 4),
            Children = { _pendingEmptyLabel, _pendingStack }
        };

        var pendingScroll = new ScrollView { Content = pendingContent };

        var innerGrid = new Grid {
            BackgroundColor = Colors.White,
            RowDefinitions = { new(GridLength.Auto), new(GridLength.Star) }
        };
        innerGrid.Add(panelHeader,   0, 0);
        innerGrid.Add(pendingScroll, 0, 1);

        var panelBorder = new Border {
            StrokeThickness = 1, Stroke = Color.FromArgb("#DEE2E6"),
            StrokeShape = new Microsoft.Maui.Controls.Shapes.RoundRectangle { CornerRadius = 0 },
            Content = innerGrid
        };
        panelBorder.Shadow = new Shadow { Brush = Brush.Black, Offset = new Point(-4, 0), Radius = 16, Opacity = 0.15f };

        _floatingPendingPanel.WidthRequest = 280;
        _floatingPendingPanel.HorizontalOptions = LayoutOptions.End;
        _floatingPendingPanel.VerticalOptions = LayoutOptions.Fill;
        _floatingPendingPanel.IsVisible = false;
        _floatingPendingPanel.Children.Add(panelBorder);
    }

    // ── Pending items ─────────────────────────────────────────────────────────

    private async Task LoadPendingItemsAsync() {
        if (string.IsNullOrEmpty(_table)) return;
        try {
            var order = await _api.GetTableActiveOrderSummaryAsync(_table);
            await MainThread.InvokeOnMainThreadAsync(() =>
                RebuildPendingStack(order?.Items ?? new List<OrderItemInfo>()));
        } catch (Exception ex) {
            CrashLogger.Log(ex, "OrderView.LoadPendingItems");
        }
    }

    private void RebuildPendingStack(List<OrderItemInfo> items) {
        _pendingStack.Children.Clear();
        _pendingEmptyLabel.IsVisible = !items.Any();

        foreach (var item in items) {
            var nameLbl = new Label {
                Text = $"{item.Quantity}×  {item.Name}",
                FontSize = 12, TextColor = Color.FromArgb("#212529"),
                VerticalOptions = LayoutOptions.Center,
                LineBreakMode = LineBreakMode.TailTruncation,
                HorizontalOptions = LayoutOptions.Fill
            };
            var priceLbl = new Label {
                Text = $"₹{item.UnitPrice * item.Quantity:F0}",
                FontSize = 11, TextColor = Color.FromArgb("#6C757D"),
                VerticalOptions = LayoutOptions.Center
            };
            var clearBtn = new Button {
                Text = "✓", FontSize = 13, FontAttributes = FontAttributes.Bold,
                BackgroundColor = Color.FromArgb("#28A745"), TextColor = Colors.White,
                CornerRadius = 6, WidthRequest = 36, HeightRequest = 36,
                Padding = new Thickness(0), VerticalOptions = LayoutOptions.Center,
                Margin = new Thickness(6, 0, 0, 0)
            };

            var rowGrid = new Grid {
                Padding = new Thickness(10, 8),
                ColumnDefinitions = {
                    new(GridLength.Star),
                    new(GridLength.Auto),
                    new(GridLength.Auto)
                }
            };
            rowGrid.Add(nameLbl,  0, 0);
            rowGrid.Add(priceLbl, 1, 0);
            rowGrid.Add(clearBtn, 2, 0);

            var rowBorder = new Border {
                BackgroundColor = Colors.White, StrokeThickness = 0,
                StrokeShape = new Microsoft.Maui.Controls.Shapes.RoundRectangle { CornerRadius = 0 },
                Content = rowGrid
            };

            var captured = rowBorder;
            clearBtn.Clicked += (_, _) => {
                // Strike through + fade, then remove after brief visual pause
                nameLbl.TextDecorations = TextDecorations.Strikethrough;
                nameLbl.TextColor = Color.FromArgb("#AAAAAA");
                captured.Opacity = 0.35;
                clearBtn.IsEnabled = false;
                Task.Delay(500).ContinueWith(_ =>
                    MainThread.BeginInvokeOnMainThread(() =>
                        _pendingStack.Children.Remove(captured)));
            };

            var sep = new BoxView {
                HeightRequest = 1, BackgroundColor = Color.FromArgb("#F0F0F0"),
                Margin = new Thickness(10, 0)
            };
            _pendingStack.Children.Add(rowBorder);
            _pendingStack.Children.Add(sep);
        }
    }

    // ── Table selection → show inline menu ───────────────────────────────────

    private async Task OnTableSelected() {
        _cart.Clear();
        UpdateCartBadge();
        ShowMenuCanvas();

        var cache = _currentZone == "normal" ? _normalMenuCache : _acMenuCache;
        _selectedCat = "All";
        _searchText = "";
        _searchBar.Text = "";
        RebuildCategoryBar(cache);

        if (cache != null) {
            RenderMenu(cache);
        } else {
            _menuStack.Children.Clear();
            _menuStack.Children.Add(new ActivityIndicator {
                IsRunning = true, Color = Color.FromArgb("#1B4332"),
                HeightRequest = 40, WidthRequest = 40,
                HorizontalOptions = LayoutOptions.Center, Margin = new Thickness(0, 32)
            });
            _ = LoadMenuFromApiAsync();
        }
        _ = LoadPendingItemsAsync();
    }

    private async Task LoadMenuFromApiAsync() {
        try {
            var response = await _api.GetMenuByZoneAsync(_currentZone);
            if (_currentZone == "normal") _normalMenuCache = response;
            else _acMenuCache = response;
            await MainThread.InvokeOnMainThreadAsync(() => {
                RebuildCategoryBar(response);
                RenderMenu(response);
            });
        } catch (Exception ex) {
            CrashLogger.Log(ex, "OrderView.LoadMenuFromApi");
            await MainThread.InvokeOnMainThreadAsync(() => {
                _menuStack.Children.Clear();
                _menuStack.Children.Add(new Label {
                    Text = "Could not load menu", FontSize = 14,
                    TextColor = Color.FromArgb("#6C757D"),
                    HorizontalOptions = LayoutOptions.Center, Margin = new Thickness(0, 24)
                });
            });
        }
    }

    private void ShowMenuCanvas() {
        _emptyLabel.IsVisible = false;
        _menuCanvas.IsVisible = true;
    }

    // ── Menu render ───────────────────────────────────────────────────────────

    private void RenderMenu(ZoneMenuResponse? response) {
        if (_isRendering) return;
        _isRendering = true;
        try {
            _menuStack.Children.Clear();
            if (response == null) {
                _menuStack.Children.Add(new Label {
                    Text = "Could not load menu", FontSize = 14,
                    TextColor = Color.FromArgb("#6C757D"),
                    HorizontalOptions = LayoutOptions.Center, Margin = new Thickness(0, 24)
                });
                return;
            }

            _categories = response.Categories;
            bool any = false;

            foreach (var cat in _categories) {
                if (_selectedCat != "All" && cat.Name != _selectedCat) continue;
                var items = cat.Items
                    .Where(i => i.IsAvailable)
                    .Where(i => string.IsNullOrWhiteSpace(_searchText) ||
                        i.Name.Contains(_searchText, StringComparison.OrdinalIgnoreCase))
                    .Where(i => _vegFilter == "All" ||
                        (_vegFilter == "Veg" && i.IsVeg) ||
                        (_vegFilter == "Non-Veg" && !i.IsVeg))
                    .ToList();

                if (!items.Any()) continue;
                any = true;

                _menuStack.Children.Add(new Label {
                    Text = cat.Name, FontSize = 13, FontAttributes = FontAttributes.Bold,
                    TextColor = Color.FromArgb("#1B4332"),
                    BackgroundColor = Color.FromArgb("#F0F7F0"),
                    Padding = new Thickness(16, 10, 16, 8)
                });
                foreach (var item in items)
                    _menuStack.Children.Add(BuildMenuItemCard(item, cat.Name));
            }

            if (!any)
                _menuStack.Children.Add(new Label {
                    Text = "No dishes match the current filters.",
                    FontSize = 14, TextColor = Color.FromArgb("#6C757D"),
                    HorizontalOptions = LayoutOptions.Center, Margin = new Thickness(0, 24)
                });
        } finally {
            _isRendering = false;
        }
    }

    private View BuildMenuItemCard(Models.MenuItem item, string categoryName = "") {
        var vegBadge = new Border {
            BackgroundColor = item.IsVeg ? Color.FromArgb("#28A745") : Color.FromArgb("#DC3545"),
            StrokeThickness = 0,
            StrokeShape = new Microsoft.Maui.Controls.Shapes.RoundRectangle { CornerRadius = 4 },
            Padding = new Thickness(6, 2),
            Content = new Label {
                Text = item.IsVeg ? "VEG" : "NON",
                TextColor = Colors.White, FontSize = 9, FontAttributes = FontAttributes.Bold
            }
        };

        var nameLbl = new Label {
            Text = item.Name, FontSize = 14, FontAttributes = FontAttributes.Bold,
            TextColor = Color.FromArgb("#212529"), VerticalOptions = LayoutOptions.Center,
            HorizontalOptions = LayoutOptions.Fill,
            LineBreakMode = LineBreakMode.TailTruncation, MaxLines = 1,
            Margin = new Thickness(8, 0, 0, 0)
        };

        var priceLbl = new Label {
            Text = $"₹{item.DisplayPrice:F0}", FontSize = 14, FontAttributes = FontAttributes.Bold,
            TextColor = Color.FromArgb("#1B4332"), VerticalOptions = LayoutOptions.Center,
            HorizontalOptions = LayoutOptions.End
        };

        var nameRow = new Grid {
            ColumnDefinitions = { new(GridLength.Auto), new(GridLength.Star), new(GridLength.Auto) }
        };
        nameRow.Add(vegBadge, 0, 0);
        nameRow.Add(nameLbl,  1, 0);
        nameRow.Add(priceLbl, 2, 0);

        // Permanent stationary stepper [−] 0 [+] pinned to right
        var minus = new Button {
            Text = "−", WidthRequest = 32, HeightRequest = 32, FontSize = 16,
            CornerRadius = 8, BackgroundColor = Color.FromArgb("#E0E0E0"),
            TextColor = Color.FromArgb("#AAAAAA"), Padding = new Thickness(0)
        };
        var qtyLbl = new Label {
            Text = "0", FontSize = 14, FontAttributes = FontAttributes.Bold, TextColor = Colors.Black,
            VerticalOptions = LayoutOptions.Center, MinimumWidthRequest = 24,
            HorizontalTextAlignment = TextAlignment.Center
        };
        var plus = new Button {
            Text = "+", WidthRequest = 32, HeightRequest = 32, FontSize = 16,
            CornerRadius = 8, BackgroundColor = Color.FromArgb("#1B4332"),
            TextColor = Colors.White, Padding = new Thickness(0)
        };
        var stepper = new HorizontalStackLayout {
            Spacing = 6, VerticalOptions = LayoutOptions.Center,
            Children = { minus, qtyLbl, plus }
        };

        var actionRow = new Grid {
            ColumnDefinitions = { new(GridLength.Star), new(GridLength.Auto) }
        };
        actionRow.Add(stepper, 1, 0);

        // Whipped cream modifier — created here so both plus/minus handlers can reference it
        Button? wcBtn = null;
        bool wcSelected = false;

        plus.Clicked += (_, _) => {
            var ci = _cart.FirstOrDefault(c => c.MenuItemId == item.Id);
            if (ci == null) {
                ci = new CartItem { MenuItemId = item.Id, Name = item.Name, BasePrice = item.DisplayPrice, Quantity = 1 };
                _cart.Add(ci);
            } else {
                ci.Quantity++;
            }
            qtyLbl.Text = ci.Quantity.ToString();
            minus.BackgroundColor = Color.FromArgb("#F0F0F0");
            minus.TextColor = Colors.Black;
            if (wcBtn != null) { wcBtn.IsEnabled = true; wcBtn.Opacity = 1.0; }
            UpdateCartBadge();
        };

        minus.Clicked += (_, _) => {
            var ci = _cart.FirstOrDefault(c => c.MenuItemId == item.Id);
            if (ci == null || ci.Quantity <= 0) return;
            ci.Quantity--;
            if (ci.Quantity <= 0) {
                _cart.Remove(ci);
                qtyLbl.Text = "0";
                minus.BackgroundColor = Color.FromArgb("#E0E0E0");
                minus.TextColor = Color.FromArgb("#AAAAAA");
                if (wcBtn != null) {
                    wcBtn.IsEnabled = false;
                    wcBtn.Opacity = 0.45;
                    if (wcSelected) {
                        wcSelected = false;
                        wcBtn.BackgroundColor = Colors.White;
                        wcBtn.TextColor = Color.FromArgb("#6C757D");
                        wcBtn.BorderColor = Color.FromArgb("#DEE2E6");
                        wcBtn.Text = "+ Add Whipped Cream  ₹40";
                    }
                }
            } else {
                qtyLbl.Text = ci.Quantity.ToString();
            }
            UpdateCartBadge();
        };

        var cardChildren = new List<View> { nameRow, actionRow };

        // Only show whipped cream option for drink/dessert categories
        if (IsWhippedCreamCategory(categoryName)) {
            wcBtn = new Button {
                Text = "+ Add Whipped Cream  ₹40",
                FontSize = 11, CornerRadius = 6,
                HeightRequest = 30, Padding = new Thickness(10, 0),
                BackgroundColor = Colors.White, TextColor = Color.FromArgb("#6C757D"),
                BorderColor = Color.FromArgb("#DEE2E6"), BorderWidth = 1,
                HorizontalOptions = LayoutOptions.Start,
                IsEnabled = false, Opacity = 0.45
            };
            wcBtn.Clicked += (_, _) => {
                var ci = _cart.FirstOrDefault(c => c.MenuItemId == item.Id);
                if (ci == null) return;
                wcSelected = !wcSelected;
                if (wcSelected) {
                    ci.ModifierPrice = 40m;
                    if (!ci.Customizations.Contains("Whipped Cream +₹40"))
                        ci.Customizations.Add("Whipped Cream +₹40");
                    wcBtn.BackgroundColor = Color.FromArgb("#E8F5E9");
                    wcBtn.TextColor = Color.FromArgb("#1B4332");
                    wcBtn.BorderColor = Color.FromArgb("#28A745");
                    wcBtn.Text = "✓ Whipped Cream  +₹40";
                } else {
                    ci.ModifierPrice = 0m;
                    ci.Customizations.Remove("Whipped Cream +₹40");
                    wcBtn.BackgroundColor = Colors.White;
                    wcBtn.TextColor = Color.FromArgb("#6C757D");
                    wcBtn.BorderColor = Color.FromArgb("#DEE2E6");
                    wcBtn.Text = "+ Add Whipped Cream  ₹40";
                }
                UpdateCartBadge();
            };
            cardChildren.Add(wcBtn);
        }

        var contentStack = new StackLayout { Spacing = 8 };
        foreach (var child in cardChildren) contentStack.Children.Add(child);

        return new Border {
            BackgroundColor = Colors.White,
            StrokeThickness = 1, Stroke = Color.FromArgb("#DEE2E6"),
            StrokeShape = new Microsoft.Maui.Controls.Shapes.RoundRectangle { CornerRadius = 8 },
            Padding = new Thickness(12, 8), Margin = new Thickness(0, 2),
            Content = contentStack
        };
    }

    private static bool IsWhippedCreamCategory(string name) {
        var lower = name.ToLowerInvariant();
        return lower.Contains("drink") || lower.Contains("beverage") ||
               lower.Contains("dessert") || lower.Contains("sweet") ||
               lower.Contains("coffee") || lower.Contains("juice") ||
               lower.Contains("shake")  || lower.Contains("smoothie");
    }

    // ── Cart ──────────────────────────────────────────────────────────────────

    private void UpdateCartBadge() {
        var totalItems = _cart.Sum(c => c.Quantity);
        var total = _cart.Sum(c => c.ItemTotal);
        _cartBadge.Text = totalItems > 0 ? $"{totalItems} item{(totalItems > 1 ? "s" : "")} · ₹{total:F0}" : "0 items in cart";
        _placeBtn.Text = totalItems > 0 ? $"Place Order · ₹{total:F0}" : "Place Order";
        _placeBtn.IsEnabled = totalItems > 0;
    }

    // ── Category bar ──────────────────────────────────────────────────────────

    private void RebuildCategoryBar(ZoneMenuResponse? response) {
        _catRow.Children.Clear();
        _catBtns.Clear();
        _selectedCat = "All";
        var allBtn = MakeCatBtn("All", true);
        _catBtns.Add(allBtn);
        _catRow.Children.Add(allBtn);
        if (response != null)
            foreach (var cat in response.Categories.Where(c => c.Items.Any(i => i.IsAvailable))) {
                var btn = MakeCatBtn(cat.Name, false);
                _catBtns.Add(btn);
                _catRow.Children.Add(btn);
            }
    }

    private Button MakeCatBtn(string name, bool active) {
        var btn = new Button {
            Text = name, FontSize = 12, CornerRadius = 16, HeightRequest = 32,
            Padding = new Thickness(14, 0),
            BackgroundColor = active ? Color.FromArgb("#1B4332") : Colors.White,
            TextColor = active ? Colors.White : Color.FromArgb("#1B4332"),
            BorderColor = Color.FromArgb("#1B4332"), BorderWidth = 1
        };
        btn.Clicked += (_, _) => ApplyCategoryFilter(name);
        return btn;
    }

    private void ApplyCategoryFilter(string cat) {
        _selectedCat = cat;
        foreach (var b in _catBtns) {
            bool sel = b.Text == cat;
            b.BackgroundColor = sel ? Color.FromArgb("#1B4332") : Colors.White;
            b.TextColor = sel ? Colors.White : Color.FromArgb("#1B4332");
        }
        var cache = _currentZone == "normal" ? _normalMenuCache : _acMenuCache;
        RenderMenu(cache != null ? new ZoneMenuResponse { Zone = _currentZone, Categories = _categories } : null);
    }

    // ── Search + veg filter ───────────────────────────────────────────────────

    private async void OnSearchTextChanged(object? sender, TextChangedEventArgs e) {
        _searchText = e.NewTextValue ?? "";
        _debounceCts?.Cancel();
        _debounceCts = new CancellationTokenSource();
        var token = _debounceCts.Token;
        try {
            await Task.Delay(250, token);
            if (!token.IsCancellationRequested) {
                var cache = _currentZone == "normal" ? _normalMenuCache : _acMenuCache;
                RenderMenu(cache != null ? new ZoneMenuResponse { Zone = _currentZone, Categories = _categories } : null);
            }
        } catch (TaskCanceledException) { }
    }

    private void ApplyVegFilter(string filter) {
        _vegFilter = filter;
        UpdateVegBtnStyles();
        var cache = _currentZone == "normal" ? _normalMenuCache : _acMenuCache;
        RenderMenu(cache != null ? new ZoneMenuResponse { Zone = _currentZone, Categories = _categories } : null);
    }

    private void UpdateVegBtnStyles() {
        SetVegStyle(_vegAll, _vegFilter == "All");
        SetVegStyle(_vegVeg, _vegFilter == "Veg");
        SetVegStyle(_vegNon, _vegFilter == "Non-Veg");
    }

    private static void SetVegStyle(Button btn, bool active) {
        btn.BackgroundColor = active ? Color.FromArgb("#1B4332") : Colors.White;
        btn.TextColor       = active ? Colors.White : Color.FromArgb("#1B4332");
    }

    private static void ConfigureVegBtn(Button btn, string text) {
        btn.Text = text; btn.FontSize = 12; btn.CornerRadius = 8;
        btn.HeightRequest = 38; btn.HorizontalOptions = LayoutOptions.Fill;
        btn.BorderColor = Color.FromArgb("#DEE2E6"); btn.BorderWidth = 1;
    }

    // ── Place order ───────────────────────────────────────────────────────────

    private async void OnPlaceOrder(object? sender, EventArgs e) {
        if (!_cart.Any()) return;
        _placeBtn.IsEnabled = false;
        _placeBtn.Text = "Placing…";
        try {
            var (ok, msg) = await _api.PlaceOrderAsync(_cart, _table, "dine_in");
            if (ok) {
                _cart.Clear();
                UpdateCartBadge();
                var cache = _currentZone == "normal" ? _normalMenuCache : _acMenuCache;
                RenderMenu(cache != null ? new ZoneMenuResponse { Zone = _currentZone, Categories = _categories } : null);
                await LoadPendingItemsAsync();
                await Application.Current!.Windows[0].Page!.DisplayAlertAsync(
                    "Order Placed!", $"Order for {_table} sent to kitchen.", "OK");
            } else {
                var total = _cart.Sum(c => c.ItemTotal);
                _placeBtn.Text = $"Place Order · ₹{total:F0}";
                _placeBtn.IsEnabled = true;
                await Application.Current!.Windows[0].Page!.DisplayAlertAsync(
                    "Order Failed", msg ?? "Something went wrong. Please try again.", "OK");
            }
        } catch (Exception ex) {
            CrashLogger.Log(ex, "OrderView.OnPlaceOrder");
            var total = _cart.Sum(c => c.ItemTotal);
            _placeBtn.Text = _cart.Any() ? $"Place Order · ₹{total:F0}" : "Place Order";
            _placeBtn.IsEnabled = _cart.Any();
            await Application.Current!.Windows[0].Page!.DisplayAlertAsync(
                "Network Error", "Could not connect to server. Your selections are still saved.", "OK");
        }
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
            try { await OnTableSelected(); }
            catch (Exception ex) { CrashLogger.Log(ex, "OrderView.TableBtn"); }
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
        _cart.Clear();
        UpdateCartBadge();
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
            _emptyLabel.Text = "Select a table above to start an order.";
            _emptyLabel.IsVisible = true;
            _menuCanvas.IsVisible = false;
        });
    }
}
