using System.Diagnostics;
using GustoWaiter.Models;
using GustoWaiter.Services;

namespace GustoWaiter.Views;

/// <summary>
/// Full-screen modal that lets a waiter browse the zone menu, build a cart,
/// and place an order directly for the selected table.
/// </summary>
public class MenuPickerPage : ContentPage {
    private readonly ApiService _api;
    private readonly string _zone;
    private readonly string _tableId;
    private ZoneMenuResponse? _menuCache;

    private readonly List<CartItem>    _cart = new();
    private List<MenuCategory>         _categories = new();
    private readonly StackLayout       _menuStack  = new() { Spacing = 0 };
    private readonly Label             _cartBadge  = new();
    private readonly Button            _placeBtn   = new();
    private readonly SearchBar         _searchBar  = new();
    private readonly Button            _vegAll     = new();
    private readonly Button            _vegVeg     = new();
    private readonly Button            _vegNon     = new();
    private readonly HorizontalStackLayout _catRow = new() { Spacing = 6, Padding = new Thickness(12, 0) };
    private readonly List<Button>      _catBtns    = new();
    private string  _searchText     = "";
    private string  _vegFilter      = "All";
    private string  _selectedCat    = "All";
    private bool    _isRendering;
    private CancellationTokenSource? _debounceCts;

    public event Action? OrderPlaced;

    // ── Constructor ───────────────────────────────────────────────────────────

    public MenuPickerPage(ApiService api, string zone, string tableId, ZoneMenuResponse? cache = null) {
        _api = api; _zone = zone; _tableId = tableId; _menuCache = cache;
        NavigationPage.SetHasNavigationBar(this, false);
        BackgroundColor = Colors.White;
        BuildLayout();
    }

    protected override void OnAppearing() {
        base.OnAppearing();
        _ = LoadMenuAsync();
    }

    // ── Layout ────────────────────────────────────────────────────────────────

    private void BuildLayout() {
        // ── Header ──────────────────────────────────────────────────────────
        var closeBtn = new Button {
            Text = "✕", FontSize = 18, FontAttributes = FontAttributes.Bold,
            BackgroundColor = Colors.Transparent, TextColor = Colors.White,
            WidthRequest = 44, HeightRequest = 44, Padding = new Thickness(0)
        };
        closeBtn.Clicked += async (_, _) =>
            await Application.Current!.Windows[0].Page!.Navigation.PopModalAsync(true);

        var tableBadge = new Border {
            BackgroundColor = Color.FromArgb("#28A745"), StrokeThickness = 0,
            StrokeShape = new Microsoft.Maui.Controls.Shapes.RoundRectangle { CornerRadius = 8 },
            Padding = new Thickness(12, 4), VerticalOptions = LayoutOptions.Center,
            Content = new Label {
                Text = _tableId, TextColor = Colors.White,
                FontSize = 16, FontAttributes = FontAttributes.Bold
            }
        };

        var zoneLabel = new Label {
            Text = _zone == "ac" ? "AC Menu ❄️" : "Regular Menu",
            TextColor = Color.FromArgb("#A8D5B5"), FontSize = 11
        };

        var headerGrid = new Grid {
            BackgroundColor = Color.FromArgb("#1B4332"),
            Padding = new Thickness(16, 12),
            ColumnDefinitions = { new(GridLength.Star), new(GridLength.Auto), new(GridLength.Auto) }
        };
        headerGrid.Add(new StackLayout {
            Spacing = 2, VerticalOptions = LayoutOptions.Center,
            Children = {
                new Label { Text = "Add Items", TextColor = Colors.White, FontSize = 17, FontAttributes = FontAttributes.Bold },
                zoneLabel
            }
        }, 0, 0);
        headerGrid.Add(tableBadge, 1, 0);
        headerGrid.Add(closeBtn,   2, 0);

        // ── Search + veg filter ─────────────────────────────────────────────
        _searchBar.Placeholder = "Search dishes...";
        _searchBar.PlaceholderColor = Color.FromArgb("#AAAAAA");
        _searchBar.BackgroundColor  = Colors.White;
        _searchBar.TextColor        = Colors.Black;
        _searchBar.Margin           = new Thickness(12, 8, 12, 4);
        _searchBar.TextChanged     += OnSearchTextChanged;

        ConfigureVegBtn(_vegAll, "All");
        ConfigureVegBtn(_vegVeg, "Veg");
        ConfigureVegBtn(_vegNon, "Non-Veg");
        _vegAll.Clicked += (_, _) => ApplyVegFilter("All");
        _vegVeg.Clicked += (_, _) => ApplyVegFilter("Veg");
        _vegNon.Clicked += (_, _) => ApplyVegFilter("Non-Veg");
        UpdateVegBtnStyles();

        var vegRow = new HorizontalStackLayout {
            Spacing = 8, Margin = new Thickness(12, 4, 12, 8),
            Children = { _vegAll, _vegVeg, _vegNon }
        };

        // ── Category strip ──────────────────────────────────────────────────
        var catScroll = new ScrollView {
            Orientation = ScrollOrientation.Horizontal,
            HorizontalScrollBarVisibility = ScrollBarVisibility.Never,
            HeightRequest = 44, Margin = new Thickness(0, 0, 0, 4),
            Content = _catRow
        };

        var searchPanel = new VerticalStackLayout {
            BackgroundColor = Colors.White, Spacing = 0,
            Children = { _searchBar, vegRow, catScroll }
        };
        searchPanel.Shadow = new Shadow { Brush = Brush.Black, Offset = new Point(0, 2), Radius = 6, Opacity = 0.06f };

        // ── Menu scroll ─────────────────────────────────────────────────────
        var menuScroll = new ScrollView {
            Content = new StackLayout { Padding = new Thickness(12, 4, 12, 12), Children = { _menuStack } }
        };

        // ── Cart footer ─────────────────────────────────────────────────────
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

        // ── Root ────────────────────────────────────────────────────────────
        var root = new Grid {
            RowDefinitions = {
                new(GridLength.Auto),  // header
                new(GridLength.Auto),  // search + filters
                new(GridLength.Star),  // menu
                new(GridLength.Auto)   // cart footer
            },
            BackgroundColor = Color.FromArgb("#F8F9FA")
        };
        root.Add(headerGrid,   0, 0);
        root.Add(searchPanel,  0, 1);
        root.Add(menuScroll,   0, 2);
        root.Add(footer,       0, 3);

        Content = root;
    }

    private static void ConfigureVegBtn(Button btn, string text) {
        btn.Text = text; btn.FontSize = 12; btn.CornerRadius = 8;
        btn.HeightRequest = 38; btn.HorizontalOptions = LayoutOptions.Fill;
        btn.BorderColor = Color.FromArgb("#DEE2E6"); btn.BorderWidth = 1;
    }

    // ── Menu load & render ────────────────────────────────────────────────────

    private async Task LoadMenuAsync() {
        if (_menuCache != null) {
            await MainThread.InvokeOnMainThreadAsync(() => { RebuildCategoryBar(_menuCache); RenderMenu(_menuCache); });
            return;
        }
        await MainThread.InvokeOnMainThreadAsync(() => {
            _menuStack.Children.Clear();
            _menuStack.Children.Add(new ActivityIndicator {
                IsRunning = true, Color = Color.FromArgb("#1B4332"),
                HeightRequest = 40, WidthRequest = 40,
                HorizontalOptions = LayoutOptions.Center, Margin = new Thickness(0, 32)
            });
        });
        try {
            var response = await _api.GetMenuByZoneAsync(_zone);
            _menuCache = response;
            await MainThread.InvokeOnMainThreadAsync(() => { RebuildCategoryBar(response); RenderMenu(response); });
        } catch (Exception ex) {
            Debug.WriteLine($"MenuPickerPage.LoadMenuAsync: {ex.Message}");
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
                    _menuStack.Children.Add(BuildMenuItemCard(item));
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

    private View BuildMenuItemCard(Models.MenuItem item) {
        var vegBadge = new Border {
            BackgroundColor = item.IsVeg ? Color.FromArgb("#28A745") : Color.FromArgb("#DC3545"),
            StrokeThickness = 0,
            StrokeShape = new Microsoft.Maui.Controls.Shapes.RoundRectangle { CornerRadius = 4 },
            Padding = new Thickness(6, 2),
            Content = new Label {
                Text = item.IsVeg ? "VEG" : "NON-VEG",
                TextColor = Colors.White, FontSize = 9, FontAttributes = FontAttributes.Bold
            }
        };

        var nameLbl = new Label {
            Text = item.Name, FontSize = 14, FontAttributes = FontAttributes.Bold,
            TextColor = Color.FromArgb("#212529"), VerticalOptions = LayoutOptions.Center,
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

        // Qty stepper (hidden until item added)
        var minus = new Button {
            Text = "−", WidthRequest = 32, HeightRequest = 32, FontSize = 16,
            CornerRadius = 8, BackgroundColor = Color.FromArgb("#F0F0F0"),
            TextColor = Colors.Black, Padding = new Thickness(0)
        };
        var qtyLbl = new Label {
            FontSize = 14, FontAttributes = FontAttributes.Bold, TextColor = Colors.Black,
            VerticalOptions = LayoutOptions.Center, MinimumWidthRequest = 24,
            HorizontalTextAlignment = TextAlignment.Center
        };
        var plus = new Button {
            Text = "+", WidthRequest = 32, HeightRequest = 32, FontSize = 16,
            CornerRadius = 8, BackgroundColor = Color.FromArgb("#1B4332"),
            TextColor = Colors.White, Padding = new Thickness(0)
        };
        var stepper = new HorizontalStackLayout {
            Spacing = 6, VerticalOptions = LayoutOptions.Center, IsVisible = false,
            Children = { minus, qtyLbl, plus }
        };

        var addBtn = new Button {
            Text = "+  Add", BackgroundColor = Color.FromArgb("#28A745"), TextColor = Colors.White,
            CornerRadius = 8, FontSize = 12, FontAttributes = FontAttributes.Bold,
            HeightRequest = 34, Padding = new Thickness(12, 0),
            HorizontalOptions = LayoutOptions.End
        };

        var actionRow = new Grid {
            ColumnDefinitions = { new(GridLength.Star), new(GridLength.Auto) }
        };
        actionRow.Add(stepper, 0, 0);
        actionRow.Add(addBtn,  1, 0);

        addBtn.Clicked += (_, _) => {
            var ci = _cart.FirstOrDefault(c => c.MenuItemId == item.Id);
            if (ci == null) {
                ci = new CartItem { MenuItemId = item.Id, Name = item.Name, BasePrice = item.DisplayPrice };
                _cart.Add(ci);
            } else {
                ci.Quantity++;
            }
            qtyLbl.Text = ci.Quantity.ToString();
            stepper.IsVisible = true;
            addBtn.IsVisible  = false;
            UpdateCartBadge();
        };

        minus.Clicked += (_, _) => {
            var ci = _cart.FirstOrDefault(c => c.MenuItemId == item.Id);
            if (ci == null) return;
            ci.Quantity--;
            if (ci.Quantity <= 0) {
                _cart.Remove(ci);
                stepper.IsVisible = false;
                addBtn.IsVisible  = true;
            } else {
                qtyLbl.Text = ci.Quantity.ToString();
            }
            UpdateCartBadge();
        };

        plus.Clicked += (_, _) => {
            var ci = _cart.FirstOrDefault(c => c.MenuItemId == item.Id);
            if (ci == null) return;
            ci.Quantity++;
            qtyLbl.Text = ci.Quantity.ToString();
            UpdateCartBadge();
        };

        var card = new Border {
            BackgroundColor = Colors.White,
            StrokeThickness = 1, Stroke = Color.FromArgb("#DEE2E6"),
            StrokeShape = new Microsoft.Maui.Controls.Shapes.RoundRectangle { CornerRadius = 8 },
            Padding = new Thickness(12, 8), Margin = new Thickness(0, 2),
            Content = new StackLayout { Spacing = 8, Children = { nameRow, actionRow } }
        };
        return card;
    }

    // ── Cart ──────────────────────────────────────────────────────────────────

    private void UpdateCartBadge() {
        var totalItems = _cart.Sum(c => c.Quantity);
        var total = _cart.Sum(c => c.ItemTotal);
        _cartBadge.Text = totalItems > 0 ? $"{totalItems} item{(totalItems > 1 ? "s" : "")} · ₹{total:F0}" : "0 items in cart";
        _placeBtn.Text = totalItems > 0 ? $"Place Order  ₹{total:F0}" : "Place Order";
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
        RenderMenu(_menuCache != null ? new ZoneMenuResponse { Zone = _zone, Categories = _categories } : null);
    }

    // ── Search & veg filter ───────────────────────────────────────────────────

    private async void OnSearchTextChanged(object? sender, TextChangedEventArgs e) {
        _searchText = e.NewTextValue ?? "";
        _debounceCts?.Cancel();
        _debounceCts = new CancellationTokenSource();
        var token = _debounceCts.Token;
        try {
            await Task.Delay(250, token);
            if (!token.IsCancellationRequested) RenderMenu(CurrentMenu());
        } catch (TaskCanceledException) { }
    }

    private void ApplyVegFilter(string filter) {
        _vegFilter = filter;
        UpdateVegBtnStyles();
        RenderMenu(CurrentMenu());
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

    private ZoneMenuResponse? CurrentMenu() =>
        _menuCache != null ? new ZoneMenuResponse { Zone = _zone, Categories = _categories } : null;

    // ── Place order ───────────────────────────────────────────────────────────

    private async void OnPlaceOrder(object? sender, EventArgs e) {
        if (!_cart.Any()) return;
        _placeBtn.IsEnabled = false;
        _placeBtn.Text = "Placing…";
        try {
            var (ok, msg) = await _api.PlaceOrderAsync(_cart, _tableId, "dine_in");
            if (ok) {
                OrderPlaced?.Invoke();
                await Application.Current!.Windows[0].Page!.Navigation.PopModalAsync(true);
            } else {
                _placeBtn.Text = $"Place Order  ₹{_cart.Sum(c => c.ItemTotal):F0}";
                _placeBtn.IsEnabled = true;
                await Application.Current!.Windows[0].Page!.DisplayAlertAsync("Error", msg, "OK");
            }
        } catch (Exception ex) {
            CrashLogger.Log(ex, "MenuPickerPage.OnPlaceOrder");
            _placeBtn.Text = "Place Order";
            _placeBtn.IsEnabled = _cart.Any();
        }
    }
}
