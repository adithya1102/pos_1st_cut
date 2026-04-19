using System;
using System.Collections.Generic;
using System.Diagnostics;
using System.Linq;
using System.Threading.Tasks;
using Microsoft.Maui.Controls;
using Microsoft.Maui.Graphics;
using GustoWaiter.Models;
using GustoWaiter.Services;

namespace GustoWaiter.Views;

public class OrderView : ContentView {
    private readonly ApiService _api;
    private readonly DashboardPage _dash;
    private List<MenuCategory> _categories = new();
    private readonly List<CartItem> _cart = new();
    private string _table = "N-1";
    private string _currentZone = "normal";
    private readonly StackLayout _filterContainer = new() { Spacing = 0 };
    private readonly StackLayout _menuContainer = new() { Spacing = 0 };
    private readonly HorizontalStackLayout _normalTablesRow = new() { Spacing = 6 };
    private readonly HorizontalStackLayout _acTablesRow = new() { Spacing = 6, IsVisible = false };
    private readonly StackLayout _cartStack = new() { Spacing = 8 };
    private readonly Label _totalLbl = new() {
        FontSize = 18, FontAttributes = FontAttributes.Bold,
        TextColor = Color.FromArgb("#28A745"), HorizontalOptions = LayoutOptions.End, Text = "\u20B90"
    };
    private readonly List<Button> _normalTableButtons = new();
    private readonly List<Button> _acTableButtons = new();
    private Label _zoneBanner = new();
    private Button _regularBtn = new(), _acBtn = new();
    private bool _loaded;
    private ZoneMenuResponse? _normalMenuCache;
    private ZoneMenuResponse? _acMenuCache;
    private string _searchText = "";
    private string _vegFilter = "All";
    private readonly SearchBar _searchBar = new();
    private readonly Button _filterAllBtn = new();
    private readonly Button _filterVegBtn = new();
    private readonly Button _filterNonVegBtn = new();
    private bool _filterUiInitialized;
    private bool _isRendering;
    private CancellationTokenSource? _searchDebounceCts;

    public OrderView(ApiService api, DashboardPage dash) {
        _api = api;
        _dash = dash;
        SetupFilterControls();
        BuildLayout();
        Loaded += OnLoaded;
    }

    private async void OnLoaded(object? sender, EventArgs e) {
        if (_loaded) return;
        _loaded = true;
        try {
            var config = await _api.GetOutletConfigAsync();
            await MainThread.InvokeOnMainThreadAsync(() => BuildTableButtons(config));
            await LoadMenuForZone(_currentZone);
            _ = Task.Run(async () => {
                try {
                    var preloadZone = _currentZone == "normal" ? "ac" : "normal";
                    var response = await _api.GetMenuByZoneAsync(preloadZone);
                    if (response != null) {
                        if (preloadZone == "normal") _normalMenuCache = response;
                        else _acMenuCache = response;
                    }
                } catch (Exception ex) {
                    CrashLogger.Log(ex, "OrderView.MenuPreload");
                }
            });
        } catch (Exception ex) {
            CrashLogger.Log(ex, "OrderView.OnLoaded");
        }
    }


    private void SetupFilterControls() {
        if (_filterUiInitialized) return;
        _filterUiInitialized = true;

        _searchBar.Placeholder = "Search dishes...";
        _searchBar.PlaceholderColor = Color.FromArgb("#AAAAAA");
        _searchBar.BackgroundColor = Colors.White;
        _searchBar.TextColor = Colors.Black;
        _searchBar.Margin = new Thickness(12, 8, 12, 4);
        _searchBar.TextChanged += OnSearchTextChanged;

        ConfigureFilterButton(_filterAllBtn, "All");
        ConfigureFilterButton(_filterVegBtn, "Veg");
        ConfigureFilterButton(_filterNonVegBtn, "Non-Veg");

        _filterAllBtn.Clicked += (s, e) => ApplyVegFilter("All");
        _filterVegBtn.Clicked += (s, e) => ApplyVegFilter("Veg");
        _filterNonVegBtn.Clicked += (s, e) => ApplyVegFilter("Non-Veg");

        var filterRow = new HorizontalStackLayout {
            Spacing = 8,
            Margin = new Thickness(12, 4, 12, 12),
            HorizontalOptions = LayoutOptions.Fill,
            Children = { _filterAllBtn, _filterVegBtn, _filterNonVegBtn }
        };

        _filterContainer.Children.Clear();
        _filterContainer.Children.Add(_searchBar);
        _filterContainer.Children.Add(filterRow);

        UpdateFilterButtonStyles();
    }

    private void ConfigureFilterButton(Button button, string text) {
        button.Text = text;
        button.FontSize = 13;
        button.CornerRadius = 8;
        button.HeightRequest = 40;
        button.HorizontalOptions = LayoutOptions.Fill;
        button.BorderColor = Color.FromArgb("#DEE2E6");
        button.BorderWidth = 1;
    }

    private async void OnSearchTextChanged(object? sender, TextChangedEventArgs e) {
        _searchText = e.NewTextValue ?? "";
        Debug.WriteLine($">>> [DIAGNOSTIC]: SearchBar TextChanged -> '{_searchText}'");
        _searchDebounceCts?.Cancel();
        _searchDebounceCts = new CancellationTokenSource();
        var token = _searchDebounceCts.Token;
        try {
            await Task.Delay(250, token);
            if (!token.IsCancellationRequested)
                RenderCurrentZoneMenu();
        } catch (TaskCanceledException) { }
    }

    private void ApplyVegFilter(string filter) {
        Debug.WriteLine($">>> [DIAGNOSTIC]: ApplyVegFilter -> '{filter}'");
        _vegFilter = filter;
        UpdateFilterButtonStyles();
        RenderCurrentZoneMenu();
    }

    private void UpdateFilterButtonStyles() {
        UpdateFilterButton(_filterAllBtn, _vegFilter == "All");
        UpdateFilterButton(_filterVegBtn, _vegFilter == "Veg");
        UpdateFilterButton(_filterNonVegBtn, _vegFilter == "Non-Veg");
    }

    private static void UpdateFilterButton(Button button, bool isSelected) {
        if (isSelected) {
            button.BackgroundColor = Color.FromArgb("#1B4332");
            button.TextColor = Colors.White;
        } else {
            button.BackgroundColor = Colors.White;
            button.TextColor = Color.FromArgb("#1B4332");
        }
    }

    private ZoneMenuResponse? GetCurrentZoneMenu() =>
        _currentZone == "normal" ? _normalMenuCache : _acMenuCache;

    private void RenderCurrentZoneMenu() => RenderMenu(GetCurrentZoneMenu());

    private void BuildLayout() {
        _regularBtn = new Button {
            Text = "REGULAR", FontSize = 13, FontAttributes = FontAttributes.Bold,
            BackgroundColor = Color.FromArgb("#495057"), TextColor = Colors.White,
            CornerRadius = 20, HeightRequest = 40, Padding = new Thickness(20, 0)
        };
        _acBtn = new Button {
            Text = "AC \u2744\uFE0F", FontSize = 13, FontAttributes = FontAttributes.Bold,
            BackgroundColor = Colors.White, TextColor = Color.FromArgb("#212529"),
            CornerRadius = 20, HeightRequest = 40, Padding = new Thickness(20, 0),
            BorderColor = Color.FromArgb("#DEE2E6"), BorderWidth = 1
        };
        _regularBtn.Clicked += async (s, e) => {
            try { await SwitchZone("normal"); }
            catch (Exception ex) { CrashLogger.Log(ex, "OrderView.RegularBtnClicked"); }
        };
        _acBtn.Clicked += async (s, e) => {
            try { await SwitchZone("ac"); }
            catch (Exception ex) { CrashLogger.Log(ex, "OrderView.AcBtnClicked"); }
        };


        var zoneToggle = new HorizontalStackLayout {
            Spacing = 10, Margin = new Thickness(16, 8, 16, 0),
            Children = { _regularBtn, _acBtn }
        };

        _zoneBanner = new Label {
            Text = "Regular Menu - Standard Prices",
            FontSize = 12, TextColor = Color.FromArgb("#495057"),
            BackgroundColor = Color.FromArgb("#F8F9FA"),
            Padding = new Thickness(12, 6),
            Margin = new Thickness(16, 4, 16, 0)
        };

        var tableScrollContent = new Grid { Children = { _normalTablesRow, _acTablesRow } };
        var tableScroll = new ScrollView {
            Orientation = ScrollOrientation.Horizontal,
            HorizontalScrollBarVisibility = ScrollBarVisibility.Never,
            Margin = new Thickness(16, 6, 16, 4),
            HeightRequest = 55,
            Content = tableScrollContent
        };

        var menuScroll = new ScrollView {
            Content = new StackLayout {
                Padding = new Thickness(12, 4, 12, 12),
                Children = { _filterContainer, _menuContainer }
            }
        };

        var cartHeader = new Label {
            Text = "Current Order", FontSize = 15,
            FontAttributes = FontAttributes.Bold, TextColor = Color.FromArgb("#1B4332")
        };

        var cartScrollArea = new ScrollView { MaximumHeightRequest = 130, Content = _cartStack };

        var totalRow = new Grid {
            ColumnDefinitions = { new(GridLength.Star), new(GridLength.Auto) },
            Margin = new Thickness(0, 4)
        };
        totalRow.Add(new Label {
            Text = "TOTAL", FontSize = 16, FontAttributes = FontAttributes.Bold,
            TextColor = Colors.Black, VerticalOptions = LayoutOptions.Center
        }, 0, 0);
        totalRow.Add(_totalLbl, 1, 0);

        var placeBtn = new Button {
            Text = "Place Order", BackgroundColor = Color.FromArgb("#28A745"),
            TextColor = Colors.White, FontSize = 16, FontAttributes = FontAttributes.Bold,
            CornerRadius = 10, HeightRequest = 52, Margin = new Thickness(0, 4, 0, 0)
        };
        placeBtn.Clicked += OnPlaceOrder;

        var cartPanel = new Grid {
            BackgroundColor = Colors.White, Padding = new Thickness(16, 12),
            RowDefinitions = { new(GridLength.Auto), new(GridLength.Auto), new(GridLength.Auto), new(GridLength.Auto) }
        };
        cartPanel.Shadow = new Shadow { Brush = Brush.Black, Offset = new Point(0, -4), Radius = 12, Opacity = 0.1f };
        cartPanel.Add(cartHeader, 0, 0);
        cartPanel.Add(cartScrollArea, 0, 1);
        cartPanel.Add(totalRow, 0, 2);
        cartPanel.Add(placeBtn, 0, 3);

        var root = new Grid {
            RowDefinitions = {
                new(GridLength.Auto),
                new(GridLength.Auto),
                new(new GridLength(65)),
                new(GridLength.Star),
                new(GridLength.Auto)
            },
            BackgroundColor = Color.FromArgb("#F8F9FA")
        };
        root.Add(zoneToggle, 0, 0);
        root.Add(_zoneBanner, 0, 1);
        root.Add(tableScroll, 0, 2);
        root.Add(menuScroll, 0, 3);
        root.Add(cartPanel, 0, 4);

        Content = root;
    }

    private void BuildTableButtons(OutletConfig config) {
        _normalTablesRow.Children.Clear();
        _normalTableButtons.Clear();
        for (int i = 1; i <= config.NormalTableCount; i++)
            AddTableButton($"N-{i}", _normalTablesRow, _normalTableButtons);

        _acTablesRow.Children.Clear();
        _acTableButtons.Clear();
        for (int i = 1; i <= config.AcTableCount; i++)
            AddTableButton($"A-{i}", _acTablesRow, _acTableButtons);

        if (_normalTableButtons.Any()) {
            _table = _normalTableButtons[0].Text;
            _normalTableButtons[0].BackgroundColor = Color.FromArgb("#1B4332");
            _normalTableButtons[0].TextColor = Colors.White;
        }
    }

    private void AddTableButton(string tableId, HorizontalStackLayout row, List<Button> list) {
        var btn = new Button {
            Text = tableId, FontSize = 13,
            Padding = new Thickness(8, 6), Margin = new Thickness(4, 0),
            CornerRadius = 8,
            BackgroundColor = Color.FromArgb("#FFFFFF"),
            TextColor = Color.FromArgb("#212529"),
            BorderColor = Color.FromArgb("#DEE2E6"), BorderWidth = 1
        };
        btn.Clicked += (s, e) => {
            _table = tableId;
            foreach (var b in list) {
                b.BackgroundColor = Color.FromArgb("#FFFFFF");
                b.TextColor = Color.FromArgb("#212529");
            }
            btn.BackgroundColor = Color.FromArgb("#1B4332");
            btn.TextColor = Colors.White;
        };
        list.Add(btn);
        row.Children.Add(btn);
    }

    private async Task SwitchZone(string zone) {
        _currentZone = zone;
        await MainThread.InvokeOnMainThreadAsync(() => {
            if (zone == "normal") {
                _regularBtn.BackgroundColor = Color.FromArgb("#495057");
                _regularBtn.TextColor = Colors.White;
                _regularBtn.BorderWidth = 0;
                _acBtn.BackgroundColor = Colors.White;
                _acBtn.TextColor = Color.FromArgb("#212529");
                _acBtn.BorderColor = Color.FromArgb("#DEE2E6");
                _acBtn.BorderWidth = 1;
                _zoneBanner.Text = "Regular Menu - Standard Prices";
                _zoneBanner.TextColor = Color.FromArgb("#495057");
                _zoneBanner.BackgroundColor = Color.FromArgb("#F8F9FA");
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
                _zoneBanner.Text = "AC Menu \u2744\uFE0F \u2014 Premium Prices";
                _zoneBanner.TextColor = Color.FromArgb("#0C5460");
                _zoneBanner.BackgroundColor = Color.FromArgb("#D1ECF1");
                _normalTablesRow.IsVisible = false;
                _acTablesRow.IsVisible = true;
            }
            _cart.Clear();
            RefreshCart();
        });
        await LoadMenuForZone(zone);
    }

    public void RefreshCache() {
        _normalMenuCache = null;
        _acMenuCache = null;
    }

    private async Task LoadMenuForZone(string zone) {
        try {
            var cached = zone == "normal" ? _normalMenuCache : _acMenuCache;
            if (cached != null) {
                await MainThread.InvokeOnMainThreadAsync(() => RenderMenu(cached));
                return;
            }
            await MainThread.InvokeOnMainThreadAsync(() => {
                _menuContainer.Children.Clear();
                _menuContainer.Children.Add(new ActivityIndicator {
                    IsRunning = true, Color = Color.FromArgb("#1B4332"),
                    HeightRequest = 40, WidthRequest = 40,
                    HorizontalOptions = LayoutOptions.Center,
                    Margin = new Thickness(0, 20)
                });
            });
            var response = await _api.GetMenuByZoneAsync(zone);
            if (response != null) {
                if (zone == "normal") _normalMenuCache = response;
                else _acMenuCache = response;
            }
            await MainThread.InvokeOnMainThreadAsync(() => RenderMenu(response));
        } catch (Exception ex) {
            Debug.WriteLine($"LoadMenuForZone error: {ex.Message}");
            Debug.WriteLine($"LoadMenuForZone error: {ex.Message}");
            await MainThread.InvokeOnMainThreadAsync(() => {
                _menuContainer.Children.Clear();
                _menuContainer.Children.Add(new Label {
                    Text = "Could not load menu", FontSize = 14,
                    TextColor = Color.FromArgb("#6C757D"),
                    HorizontalOptions = LayoutOptions.Center, Margin = new Thickness(0, 20)
                });
            });
        }
    }

    private void RenderMenu(ZoneMenuResponse? response) {
        if (_isRendering) {
            Debug.WriteLine(">>> [DIAGNOSTIC]: RenderMenu SKIPPED (re-entrancy guard)");
            return;
        }
        _isRendering = true;
        Debug.WriteLine($">>> [DIAGNOSTIC]: RenderMenu START zone={_currentZone} search='{_searchText}' filter={_vegFilter}");
        try {
            _menuContainer.Children.Clear();
            if (response == null) {
                _menuContainer.Children.Add(new Label {
                    Text = "Could not load menu", FontSize = 14,
                    TextColor = Color.FromArgb("#6C757D"),
                    HorizontalOptions = LayoutOptions.Center, Margin = new Thickness(0, 20)
                });
                return;
            }

            _categories = response.Categories;
            var hasResults = false;
            foreach (var cat in _categories) {
                var activeItems = cat.Items
                    .Where(i => i.IsAvailable)
                    .Where(i => string.IsNullOrWhiteSpace(_searchText) ||
                        i.Name.Contains(_searchText, StringComparison.OrdinalIgnoreCase))
                    .Where(i => _vegFilter == "All" ||
                        (_vegFilter == "Veg" && i.IsVeg) ||
                        (_vegFilter == "Non-Veg" && !i.IsVeg))
                    .ToList();
                if (!activeItems.Any()) continue;

                hasResults = true;
                _menuContainer.Children.Add(new Label {
                    Text = cat.Name, FontSize = 13, FontAttributes = FontAttributes.Bold,
                    TextColor = Color.FromArgb("#1B4332"),
                    BackgroundColor = Color.FromArgb("#F0F7F0"),
                    Padding = new Thickness(16, 10, 16, 8)
                });
                foreach (var item in activeItems)
                    _menuContainer.Children.Add(BuildMenuItemCard(item));
            }

            if (!hasResults) {
                _menuContainer.Children.Add(new Label {
                    Text = "No dishes match the current filters",
                    FontSize = 14,
                    TextColor = Color.FromArgb("#6C757D"),
                    HorizontalOptions = LayoutOptions.Center,
                    Margin = new Thickness(0, 20)
                });
            }
            Debug.WriteLine($">>> [DIAGNOSTIC]: RenderMenu END hasResults={hasResults}");
        } finally {
            _isRendering = false;
        }
    }

    private View BuildMenuItemCard(Models.MenuItem item) {
        var badge = new Border {
            BackgroundColor = item.IsVeg ? Color.FromArgb("#28A745") : Color.FromArgb("#DC3545"),
            StrokeThickness = 0,
            StrokeShape = new Microsoft.Maui.Controls.Shapes.RoundRectangle { CornerRadius = 4 },
            Padding = new Thickness(6, 2),
            Content = new Label {
                Text = item.IsVeg ? "VEG" : "NON-VEG",
                TextColor = Colors.White, FontSize = 9, FontAttributes = FontAttributes.Bold
            }
        };

        var nameLabel = new Label {
            Text = item.Name, FontSize = 14, FontAttributes = FontAttributes.Bold,
            TextColor = Color.FromArgb("#212529"), VerticalOptions = LayoutOptions.Center,
            Margin = new Thickness(8, 0, 0, 0)
        };

        var priceLabel = new Label {
            Text = $"\u20B9{item.DisplayPrice:F0}", FontSize = 14, FontAttributes = FontAttributes.Bold,
            TextColor = Color.FromArgb("#1B4332"), VerticalOptions = LayoutOptions.Center,
            HorizontalOptions = LayoutOptions.End
        };

        var row1 = new Grid { ColumnDefinitions = { new(GridLength.Auto), new(GridLength.Star), new(GridLength.Auto) } };
        row1.Add(badge, 0, 0);
        row1.Add(nameLabel, 1, 0);
        row1.Add(priceLabel, 2, 0);

        var addBtn = new Button {
            Text = "+", BackgroundColor = Color.FromArgb("#28A745"), TextColor = Colors.White,
            CornerRadius = 16, WidthRequest = 32, HeightRequest = 32,
            FontSize = 18, FontAttributes = FontAttributes.Bold, Padding = new Thickness(0),
            HorizontalOptions = LayoutOptions.End
        };
        addBtn.Clicked += (s, e) => AddToCart(item);

        var cardContainer = new Frame {
            HasShadow = false, BorderColor = Color.FromArgb("#DEE2E6"),
            CornerRadius = 8, Padding = new Thickness(12, 8),
            Margin = new Thickness(0, 2), BackgroundColor = Colors.White
        };
        cardContainer.Content = new StackLayout { Spacing = 6, Children = { row1, addBtn } };

        return cardContainer;
    }

    private void AddToCart(Models.MenuItem item) {
        var existing = _cart.FirstOrDefault(c => c.MenuItemId == item.Id);
        if (existing != null) existing.Quantity++;
        else _cart.Add(new CartItem { MenuItemId = item.Id, Name = item.Name, BasePrice = item.DisplayPrice });
        RefreshCart();
    }

    private void RefreshCart() {
        _cartStack.Children.Clear();
        if (!_cart.Any()) { _totalLbl.Text = "\u20B90"; return; }
        foreach (var item in _cart.ToList()) {
            var minus = new Button {
                Text = "\u2212", WidthRequest = 30, HeightRequest = 30, FontSize = 16,
                CornerRadius = 6, BackgroundColor = Color.FromArgb("#F0F0F0"),
                TextColor = Colors.Black, Padding = new Thickness(0)
            };
            var qLbl = new Label {
                Text = item.Quantity.ToString(), FontSize = 14,
                FontAttributes = FontAttributes.Bold, TextColor = Colors.Black,
                VerticalOptions = LayoutOptions.Center, MinimumWidthRequest = 22,
                HorizontalTextAlignment = TextAlignment.Center
            };
            var plus = new Button {
                Text = "+", WidthRequest = 30, HeightRequest = 30, FontSize = 16,
                CornerRadius = 6, BackgroundColor = Color.FromArgb("#1B4332"),
                TextColor = Colors.White, Padding = new Thickness(0)
            };
            minus.Clicked += (s, e) => {
                if (item.Quantity > 1) { item.Quantity--; qLbl.Text = item.Quantity.ToString(); }
                else _cart.Remove(item);
                RefreshCart();
            };
            plus.Clicked += (s, e) => { item.Quantity++; qLbl.Text = item.Quantity.ToString(); RefreshCart(); };

            var row = new Grid {
                ColumnDefinitions = { new(GridLength.Star), new(GridLength.Auto), new(GridLength.Auto) }
            };
            row.Add(new Label {
                Text = $"{item.Name}  x{item.Quantity}", FontSize = 13,
                TextColor = Color.FromArgb("#212529"),
                VerticalOptions = LayoutOptions.Center,
                LineBreakMode = LineBreakMode.TailTruncation
            }, 0, 0);
            row.Add(new HorizontalStackLayout {
                Spacing = 6, VerticalOptions = LayoutOptions.Center,
                Children = { minus, qLbl, plus }
            }, 1, 0);
            row.Add(new Label {
                Text = $"\u20B9{item.ItemTotal:F0}", FontSize = 13,
                FontAttributes = FontAttributes.Bold,
                TextColor = Color.FromArgb("#212529"),
                VerticalOptions = LayoutOptions.Center,
                Margin = new Thickness(8, 0, 0, 0)
            }, 2, 0);
            _cartStack.Children.Add(row);
        }
        _totalLbl.Text = $"\u20B9{_cart.Sum(i => i.ItemTotal):F0}";
    }

    private async void OnPlaceOrder(object? s, EventArgs e) {
        try {
            if (!_cart.Any()) {
                await Application.Current!.Windows[0].Page!.DisplayAlertAsync("Empty Cart", "Add items before placing order.", "OK");
                return;
            }
            var (ok, msg) = await _api.PlaceOrderAsync(_cart, _table, "dine_in");
            if (ok) {
                _cart.Clear();
                RefreshCart();
                await Application.Current!.Windows[0].Page!.DisplayAlertAsync(
                    "\u2705 Order Placed", $"Order for {_table} sent to kitchen!", "Done");
            } else {
                await Application.Current!.Windows[0].Page!.DisplayAlertAsync("Error", msg, "OK");
            }
        } catch (Exception ex) {
            CrashLogger.Log(ex, "OrderView.OnPlaceOrder");
        }
    }

}
