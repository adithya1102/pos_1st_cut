using System;
using System.Collections.Generic;
using System.Linq;
using System.Net.Http;
using System.Text;
using Microsoft.Maui.Controls;
using Microsoft.Maui.Graphics;
using Microsoft.Maui.Layouts;
using GustoPOS.Models;
using GustoPOS.Services;
using PosMenuItem = GustoPOS.Models.MenuItem;

namespace GustoPOS.Views;

public partial class PosTerminalPage : ContentView
{
    private readonly ApiService _api;
    private List<MenuCategory> _categories = new();
    private List<CategoryItem> _categoryItems = new();
    private List<PosMenuItem> _allItems = new();
    private List<PosMenuItem> _filtered = new();
    private List<CartItem> _cart = new();
    private List<Order> _existingOrders = new();
    private Dictionary<string, Border> _cardCache = new();
    private string _selectedCategory = "All";
    private string _selectedTable = "Direct";
    private string _orderType = "dine_in";
    private string _selectedPaymentMethod = "cash";
    private bool _newDishIsVeg = true;
    private string? _loggedInStaffId;

    private string _selectedZone = "";
    private int _normalCount = 10;
    private int _acCount = 10;
    private List<Button> _allTableButtons = new();
    private Dictionary<string, bool> _tableHasOrders = new();


    public PosTerminalPage(ApiService api)
    {
        InitializeComponent();
        _api = api;
        LoadStaffIdAsync();
        LoadMenuAsync();
        LoadConfigAndBuildTablesAsync();
    }

    private async void LoadStaffIdAsync()
    {
        _loggedInStaffId = await SecureStorage.GetAsync("staff_id");
    }

    private async void LoadMenuAsync()
    {
        _cardCache.Clear();
        _selectedCategory = "All";
        var menu = await _api.GetMenuAsync();
        if (menu == null)
        {
            MenuGrid.Children.Add(new Label
            {
                Text = "Could not load menu. Make sure backend is running.",
                TextColor = Colors.Red, FontSize = 14, Margin = new Thickness(20)
            });
            return;
        }

        _categories = menu.Categories;
        _allItems = menu.Categories
            .SelectMany(c => c.Items.Select(i => { i.CategoryId = c.Id; return i; }))
            .Cast<PosMenuItem>().ToList();
        SetAllItemsACMode(_selectedZone == "ac");

        _categoryItems = await _api.GetCategoriesForMenuAsync();
        NewDishCategory.Items.Clear();
        foreach (var c in _categoryItems) NewDishCategory.Items.Add(c.Name);
        if (NewDishCategory.Items.Count > 0) NewDishCategory.SelectedIndex = 0;

        CategoryTabsPanel.Children.Clear();
        AddTab("All", true);
        foreach (var cat in _categories) AddTab(cat.Name, false);

        Filter();
    }

    // Flip IsACMode on every loaded item.
    // Card price labels update reactively via PropertyChanged — no cache rebuild needed.
    private void SetAllItemsACMode(bool isAC)
    {
        foreach (var item in _allItems) item.IsACMode = isAC;
    }

    private void AddTab(string name, bool active)
    {
        var btn = new Button
        {
            Text = name,
            BackgroundColor = active ? Color.FromArgb("#1B4332") : Color.FromArgb("#E8E8E8"),
            TextColor = active ? Colors.White : Color.FromArgb("#000000"),
            FontSize = 12, CornerRadius = 20,
            Padding = new Thickness(14, 6), HeightRequest = 36
        };
        btn.Clicked += (s, e) =>
        {
            _selectedCategory = name;
            foreach (var v in CategoryTabsPanel.Children)
                if (v is Button b) { b.BackgroundColor = Color.FromArgb("#E8E8E8"); b.TextColor = Colors.Black; }
            btn.BackgroundColor = Color.FromArgb("#1B4332");
            btn.TextColor = Colors.White;
            Filter();
        };
        CategoryTabsPanel.Children.Add(btn);
    }

    private void Filter()
    {
        _filtered = _selectedCategory == "All"
            ? _allItems.ToList()
            : (_categories.FirstOrDefault(c => c.Name == _selectedCategory)?.Items.ToList() ?? new());

        var q = SearchEntry?.Text?.Trim().ToLower();
        if (!string.IsNullOrEmpty(q))
            _filtered = _filtered.Where(i => i.Name.ToLower().Contains(q)).ToList();

        BuildMenuGrid();
    }

    private void OnSearchChanged(object? s, TextChangedEventArgs e) => Filter();

    // ── MENU GRID: 100% code, zero bindings ─────────────────
    private void BuildMenuGrid()
    {
        MenuGrid.Children.Clear();
        if (!_filtered.Any())
        {
            MenuGrid.Children.Add(new Label
            {
                Text = "No items found.",
                TextColor = Colors.Gray, FontSize = 14, Margin = new Thickness(20)
            });
            return;
        }
        foreach (var item in _filtered)
        {
            if (!_cardCache.TryGetValue(item.Id, out var card))
            {
                card = BuildCard(item);
                _cardCache[item.Id] = card;
            }
            MenuGrid.Children.Add(card);
        }
    }

    private Border BuildCard(PosMenuItem item)
    {
        // VEG / NON-VEG badge
        var badge = new Border
        {
            BackgroundColor = item.IsVeg ? Color.FromArgb("#28A745") : Color.FromArgb("#DC3545"),
            StrokeShape = new Microsoft.Maui.Controls.Shapes.RoundRectangle { CornerRadius = 4 },
            Padding = new Thickness(6, 2), HorizontalOptions = LayoutOptions.Start,
            Content = new Label
            {
                Text = item.IsVeg ? "VEG" : "NON-VEG",
                TextColor = Colors.White, FontSize = 9, FontAttributes = FontAttributes.Bold
            }
        };

        var price = new Label
        {
            Text = $"₹{item.DisplayPrice:F0}",
            TextColor = Color.FromArgb("#28A745"),
            FontAttributes = FontAttributes.Bold, FontSize = 14,
            HorizontalOptions = LayoutOptions.End, VerticalOptions = LayoutOptions.Center
        };
        item.PropertyChanged += (_, args) =>
        {
            if (args.PropertyName == nameof(PosMenuItem.DisplayPrice))
                MainThread.BeginInvokeOnMainThread(() => price.Text = $"₹{item.DisplayPrice:F0}");
        };

        var topRow = new Grid();
        topRow.ColumnDefinitions.Add(new ColumnDefinition(GridLength.Auto));
        topRow.ColumnDefinitions.Add(new ColumnDefinition(GridLength.Star));
        topRow.ColumnDefinitions.Add(new ColumnDefinition(GridLength.Auto));
        topRow.Add(badge, 0, 0);
        topRow.Add(price, 2, 0);

        // Name — solid black
        var nameLabel = new Label
        {
            Text = item.Name,
            TextColor = Colors.Black,
            FontAttributes = FontAttributes.Bold,
            FontSize = 13,
            LineBreakMode = LineBreakMode.WordWrap,
            Margin = new Thickness(0, 8, 0, 4),
            MinimumHeightRequest = 36
        };

        // Availability — only show "Unavailable" badge when inactive; no green tick clutter
        var unavailLbl = new Label
        {
            Text = "Unavailable",
            TextColor = Color.FromArgb("#DC3545"),
            FontSize = 10,
            VerticalOptions = LayoutOptions.Center,
            Margin = new Thickness(4, 0),
            IsVisible = !item.IsActive,
        };
        var toggle = new Switch
        {
            IsToggled = item.IsActive,
            OnColor = Color.FromArgb("#28A745"),
            ThumbColor = Colors.White,
            Scale = 0.8,
            VerticalOptions = LayoutOptions.Center
        };
        toggle.Toggled += async (s, e) =>
        {
            item.IsActive = e.Value;
            unavailLbl.IsVisible = !e.Value;
            await _api.ToggleItemAvailabilityAsync(item.Id, e.Value);
        };

        var bottomRow = new Grid { Margin = new Thickness(0, 4, 0, 0) };
        bottomRow.ColumnDefinitions.Add(new ColumnDefinition(GridLength.Auto));
        bottomRow.ColumnDefinitions.Add(new ColumnDefinition(GridLength.Star));
        bottomRow.Add(toggle, 0, 0);
        bottomRow.Add(unavailLbl, 1, 0);

        // Card — tap to add, hover = black border
        var card = new Border
        {
            BackgroundColor = Colors.White,
            Stroke = Color.FromArgb("#DDDDDD"),
            StrokeThickness = 1.5,
            StrokeShape = new Microsoft.Maui.Controls.Shapes.RoundRectangle { CornerRadius = 10 },
            Padding = new Thickness(12),
            Margin = new Thickness(4),
            WidthRequest = 220
        };
        card.Content = new StackLayout { Spacing = 0, Children = { topRow, nameLabel, bottomRow } };
        FlexLayout.SetGrow(card, 0);

        // Pointer hover = thick black border
        var pointerRecognizer = new PointerGestureRecognizer();
        pointerRecognizer.PointerEntered += (s, e) =>
        {
            card.Stroke = Colors.Black;
            card.StrokeThickness = 2.5;
            card.BackgroundColor = Color.FromArgb("#F5F5F5");
        };
        pointerRecognizer.PointerExited += (s, e) =>
        {
            card.Stroke = Color.FromArgb("#DDDDDD");
            card.StrokeThickness = 1.5;
            card.BackgroundColor = Colors.White;
        };
        card.GestureRecognizers.Add(pointerRecognizer);

        // Tap to add to cart
        var tap = new TapGestureRecognizer();
        tap.Tapped += async (s, e) =>
        {
            if (!item.IsActive)
            {
                await Application.Current!.Windows[0].Page!
                    .DisplayAlertAsync("Unavailable", $"{item.Name} is currently unavailable.", "OK");
                return;
            }
            // Flash green feedback
            card.Stroke = Color.FromArgb("#28A745");
            card.StrokeThickness = 2.5;
            MainThread.BeginInvokeOnMainThread(async () =>
            {
                await Task.Delay(200);
                card.Stroke = Color.FromArgb("#DDDDDD");
                card.StrokeThickness = 1.5;
            });
            AddToCart(item);
        };
        card.GestureRecognizers.Add(tap);

        return card;
    }

    // ── Cart ──────────────────────────────────────────────────
    private void AddToCart(PosMenuItem item)
    {
        var ex = _cart.FirstOrDefault(c => c.MenuItemId == item.Id);
        if (ex != null) ex.Quantity++;
        else _cart.Add(new CartItem { MenuItemId = item.Id, Name = item.Name, BasePrice = item.DisplayPrice });
        RefreshCart();
    }

    private void RefreshCart()
    {
        CartPanel.Children.Clear();
        bool hasExisting = _existingOrders.Any();
        bool hasNewItems = _cart.Any();

        if (!hasExisting && !hasNewItems)
        {
            CartPanel.Children.Add(new Label
            {
                Text = "Cart is empty", TextColor = Colors.Gray,
                HorizontalOptions = LayoutOptions.Center, Margin = new Thickness(0, 16)
            });
            SubtotalLabel.Text = TotalLabel.Text = "₹0";
            return;
        }

        decimal existingTotal = 0;

        // ── Existing orders section (read-only, line-item detail) ──
        if (hasExisting)
        {
            CartPanel.Children.Add(new Label
            {
                Text = "Active Orders", FontSize = 13,
                FontAttributes = FontAttributes.Bold,
                TextColor = Color.FromArgb("#1B4332"),
                Margin = new Thickness(0, 0, 0, 4)
            });

            foreach (var order in _existingOrders)
            {
                existingTotal += order.TotalAmount;

                CartPanel.Children.Add(new Label
                {
                    Text = $"  Order #{order.ReadableId}  ({order.OrderStatus})",
                    FontSize = 11, FontAttributes = FontAttributes.Italic,
                    TextColor = Color.FromArgb("#6C757D"),
                    Margin = new Thickness(0, 2, 0, 2)
                });

                foreach (var item in order.Items)
                {
                    var itemName = item.NameSnap ?? "Item";
                    var itemTotal = (item.PriceSnap ?? 0m) * item.Quantity;
                    var itemRow = new Grid { Margin = new Thickness(4, 1) };
                    itemRow.ColumnDefinitions.Add(new ColumnDefinition(GridLength.Star));
                    itemRow.ColumnDefinitions.Add(new ColumnDefinition(GridLength.Auto));
                    itemRow.Add(new Label
                    {
                        Text = $"{itemName}  ×{item.Quantity}",
                        FontSize = 12, TextColor = Colors.Black,
                        VerticalOptions = LayoutOptions.Center
                    }, 0, 0);
                    itemRow.Add(new Label
                    {
                        Text = $"₹{itemTotal:F0}",
                        FontSize = 12, FontAttributes = FontAttributes.Bold,
                        TextColor = Colors.Black,
                        VerticalOptions = LayoutOptions.Center
                    }, 1, 0);
                    CartPanel.Children.Add(itemRow);
                }
            }

            // Divider
            CartPanel.Children.Add(new BoxView
            {
                Color = Color.FromArgb("#DEE2E6"),
                HeightRequest = 1, Margin = new Thickness(0, 8)
            });

            // Add Items header
            CartPanel.Children.Add(new Label
            {
                Text = "Add Items", FontSize = 13,
                FontAttributes = FontAttributes.Bold,
                TextColor = Color.FromArgb("#1B4332"),
                Margin = new Thickness(0, 0, 0, 4)
            });
        }

        // ── New cart items (with +/- controls) ──
        foreach (var item in _cart.ToList())
        {
            var row = new Grid { Margin = new Thickness(0, 3) };
            row.ColumnDefinitions.Add(new ColumnDefinition(GridLength.Star));
            row.ColumnDefinitions.Add(new ColumnDefinition(GridLength.Auto));
            row.ColumnDefinitions.Add(new ColumnDefinition(GridLength.Auto));
            row.Add(new Label
            {
                Text = item.Name, FontSize = 12,
                TextColor = Colors.Black, VerticalOptions = LayoutOptions.Center
            }, 0, 0);

            var minus = new Button
            {
                Text = "−", WidthRequest = 28, HeightRequest = 28,
                FontSize = 14, CornerRadius = 4,
                BackgroundColor = Color.FromArgb("#E8E8E8"),
                TextColor = Colors.Black, Padding = new Thickness(0)
            };
            var qLbl = new Label
            {
                Text = item.Quantity.ToString(),
                VerticalOptions = LayoutOptions.Center, FontSize = 12,
                TextColor = Colors.Black, MinimumWidthRequest = 20,
                HorizontalTextAlignment = TextAlignment.Center
            };
            var plus = new Button
            {
                Text = "+", WidthRequest = 28, HeightRequest = 28,
                FontSize = 14, CornerRadius = 4,
                BackgroundColor = Color.FromArgb("#28A745"),
                TextColor = Colors.White, Padding = new Thickness(0)
            };
            minus.Clicked += (s, e) =>
            {
                if (item.Quantity > 1) item.Quantity--;
                else _cart.Remove(item);
                RefreshCart();
            };
            plus.Clicked += (s, e) => { item.Quantity++; RefreshCart(); };

            row.Add(new HorizontalStackLayout
            {
                Spacing = 4, VerticalOptions = LayoutOptions.Center,
                Children = { minus, qLbl, plus }
            }, 1, 0);
            row.Add(new Label
            {
                Text = $"₹{item.ItemTotal:F0}", FontSize = 12,
                FontAttributes = FontAttributes.Bold, TextColor = Colors.Black,
                VerticalOptions = LayoutOptions.Center, Margin = new Thickness(8, 0, 0, 0)
            }, 2, 0);
            CartPanel.Children.Add(row);
        }

        var newTotal = _cart.Sum(i => i.ItemTotal);
        var total = existingTotal + newTotal;
        SubtotalLabel.Text = TotalLabel.Text = $"₹{total:F0}";
    }

    // ── Order type buttons ────────────────────────────────────
    private void OnDineInClicked(object? s, EventArgs e) { _orderType = "dine_in"; SetOrderType(BtnDineIn); }
    private void OnTakeawayClicked(object? s, EventArgs e) { _orderType = "takeaway"; SetOrderType(BtnTakeaway); }
    private void OnOnlineClicked(object? s, EventArgs e) { _orderType = "online"; SetOrderType(BtnOnline); }
    private void SetOrderType(Button active)
    {
        foreach (var b in new[] { BtnDineIn, BtnTakeaway, BtnOnline })
        {
            b.BackgroundColor = Color.FromArgb("#E8E8E8");
            b.TextColor = Colors.Black;
        }
        active.BackgroundColor = Color.FromArgb("#1B4332");
        active.TextColor = Colors.White;
    }

    // ── Config & Dynamic Table Grid ──────────────────────────
    public void OnTabShown()
    {
        LoadConfigAndBuildTablesAsync();
        LoadMenuAsync();
    }

    public void TriggerTableRefresh() => LoadTableOrderStatusAsync();

    private async void LoadConfigAndBuildTablesAsync()
    {
        var config = await _api.GetOutletConfigAsync();
        _normalCount = config.NormalTableCount;
        _acCount = config.AcTableCount;
        BuildTableButtons();
        LoadTableOrderStatusAsync();
    }

    private void BuildTableButtons()
    {
        TableGridContainer.Children.Clear();
        _allTableButtons.Clear();

        var directBtn = new Button
        {
            Text = "Direct",
            BackgroundColor = Color.FromArgb("#1B4332"),
            TextColor = Colors.White,
            FontSize = 11,
            CornerRadius = 6,
            HeightRequest = 34,
            HorizontalOptions = LayoutOptions.Fill
        };
        directBtn.Clicked += OnDynamicTableClicked;
        _allTableButtons.Add(directBtn);
        TableGridContainer.Children.Add(directBtn);

        TableGridContainer.Children.Add(new Border
        {
            BackgroundColor = Color.FromArgb("#F8F9FA"),
            StrokeShape = new Microsoft.Maui.Controls.Shapes.RoundRectangle { CornerRadius = 4 },
            Stroke = Colors.Transparent,
            Padding = new Thickness(8, 4),
            Margin = new Thickness(0, 4, 0, 0),
            Content = new Label
            {
                Text = "NORMAL DINING",
                FontSize = 12,
                FontAttributes = FontAttributes.Bold,
                TextColor = Color.FromArgb("#495057")
            }
        });

        int normalRows = (int)Math.Ceiling(_normalCount / 5.0);
        var normalGrid = new Grid
        {
            ColumnDefinitions =
            {
                new ColumnDefinition(GridLength.Star),
                new ColumnDefinition(GridLength.Star),
                new ColumnDefinition(GridLength.Star),
                new ColumnDefinition(GridLength.Star),
                new ColumnDefinition(GridLength.Star)
            },
            ColumnSpacing = 4,
            RowSpacing = 4
        };
        for (int r = 0; r < normalRows; r++)
            normalGrid.RowDefinitions.Add(new RowDefinition(GridLength.Auto));
        for (int i = 1; i <= _normalCount; i++)
        {
            var btn = new Button
            {
                Text = $"N-{i}",
                BackgroundColor = Colors.White,
                TextColor = Color.FromArgb("#212529"),
                BorderColor = Color.FromArgb("#DEE2E6"),
                BorderWidth = 1,
                FontSize = 11,
                CornerRadius = 6,
                HeightRequest = 32
            };
            btn.Clicked += OnDynamicTableClicked;
            _allTableButtons.Add(btn);
            normalGrid.Add(btn, (i - 1) % 5, (i - 1) / 5);
        }
        TableGridContainer.Children.Add(normalGrid);

        TableGridContainer.Children.Add(new Border
        {
            BackgroundColor = Color.FromArgb("#D1ECF1"),
            StrokeShape = new Microsoft.Maui.Controls.Shapes.RoundRectangle { CornerRadius = 4 },
            Stroke = Colors.Transparent,
            Padding = new Thickness(8, 4),
            Margin = new Thickness(0, 4, 0, 0),
            Content = new Label
            {
                Text = "AC DINING ❄️",
                FontSize = 12,
                FontAttributes = FontAttributes.Bold,
                TextColor = Color.FromArgb("#0C5460")
            }
        });

        int acRows = (int)Math.Ceiling(_acCount / 5.0);
        var acGrid = new Grid
        {
            ColumnDefinitions =
            {
                new ColumnDefinition(GridLength.Star),
                new ColumnDefinition(GridLength.Star),
                new ColumnDefinition(GridLength.Star),
                new ColumnDefinition(GridLength.Star),
                new ColumnDefinition(GridLength.Star)
            },
            ColumnSpacing = 4,
            RowSpacing = 4
        };
        for (int r = 0; r < acRows; r++)
            acGrid.RowDefinitions.Add(new RowDefinition(GridLength.Auto));
        for (int i = 1; i <= _acCount; i++)
        {
            var btn = new Button
            {
                Text = $"A-{i}",
                BackgroundColor = Colors.White,
                TextColor = Color.FromArgb("#212529"),
                BorderColor = Color.FromArgb("#DEE2E6"),
                BorderWidth = 1,
                FontSize = 11,
                CornerRadius = 6,
                HeightRequest = 32
            };
            btn.Clicked += OnDynamicTableClicked;
            _allTableButtons.Add(btn);
            acGrid.Add(btn, (i - 1) % 5, (i - 1) / 5);
        }
        TableGridContainer.Children.Add(acGrid);
    }

    private async void LoadTableOrderStatusAsync()
    {
        var allTableIds = new List<string>();
        for (int i = 1; i <= _normalCount; i++) allTableIds.Add($"N-{i}");
        for (int i = 1; i <= _acCount; i++) allTableIds.Add($"A-{i}");

        var tasks = allTableIds.Select(async tid =>
        {
            try
            {
                var orders = await _api.GetTableOrdersAsync(tid);
                return (tid, hasOrders: orders.Count > 0);
            }
            catch { return (tid, hasOrders: false); }
        });
        var results = await Task.WhenAll(tasks);
        MainThread.BeginInvokeOnMainThread(() =>
        {
            foreach (var (tid, hasOrders) in results)
            {
                _tableHasOrders[tid] = hasOrders;
                var btn = _allTableButtons.FirstOrDefault(b => b.Text == tid);
                if (btn != null && tid != _selectedTable)
                {
                    if (hasOrders)
                    {
                        btn.BackgroundColor = Color.FromArgb("#FFEBEE");
                        btn.TextColor = Color.FromArgb("#212529");
                        btn.BorderColor = Color.FromArgb("#DC3545");
                    }
                    else
                    {
                        btn.BackgroundColor = Colors.White;
                        btn.TextColor = Color.FromArgb("#212529");
                        btn.BorderColor = Color.FromArgb("#DEE2E6");
                    }
                }
            }
        });
    }

    private async void OnDynamicTableClicked(object? s, EventArgs e)
    {
        if (s is not Button btn) return;
        _selectedTable = btn.Text;

        if (_selectedTable.StartsWith("N-"))
            _selectedZone = "normal";
        else if (_selectedTable.StartsWith("A-"))
            _selectedZone = "ac";
        else
            _selectedZone = "";

        foreach (var b in _allTableButtons)
        {
            bool hasOrders = _tableHasOrders.TryGetValue(b.Text, out var v) && v;
            if (hasOrders && b.Text != _selectedTable)
            {
                b.BackgroundColor = Color.FromArgb("#E8F5E9");
                b.TextColor = Color.FromArgb("#212529");
                b.BorderColor = Color.FromArgb("#28A745");
            }
            else
            {
                b.BackgroundColor = Colors.White;
                b.TextColor = Color.FromArgb("#212529");
                if (b.Text != "Direct") b.BorderColor = Color.FromArgb("#DEE2E6");
            }
        }

        btn.BackgroundColor = Color.FromArgb("#1B4332");
        btn.TextColor = Colors.White;

        if (_selectedZone == "ac")
        {
            ZoneBadge.IsVisible = true;
            ZoneBadgeLabel.Text = "❄️ AC TABLE";
            ZoneBadgeLabel.TextColor = Color.FromArgb("#0C5460");
            ZoneBadge.BackgroundColor = Color.FromArgb("#D1ECF1");
            ZoneBadge.Stroke = Color.FromArgb("#0C5460");
            SetAllItemsACMode(true);
        }
        else if (_selectedZone == "normal")
        {
            ZoneBadge.IsVisible = true;
            ZoneBadgeLabel.Text = "REGULAR TABLE";
            ZoneBadgeLabel.TextColor = Color.FromArgb("#495057");
            ZoneBadge.BackgroundColor = Color.FromArgb("#E8E8E8");
            ZoneBadge.Stroke = Color.FromArgb("#DEE2E6");
            SetAllItemsACMode(false);
        }
        else
        {
            ZoneBadge.IsVisible = false;
            SetAllItemsACMode(false);
        }

        _existingOrders.Clear();
        if (_selectedTable != "Direct")
        {
            _existingOrders = await _api.GetTableOrdersAsync(_selectedTable);
        }
        RefreshCart();
    }

    // ── Generate Bill ────────────────────────────────────────
    private async void OnPlaceOrderClicked(object? s, EventArgs e)
    {
        var tableId = _selectedTable == "Direct" ? null : _selectedTable;

        // Direct order — just place the order (no bill flow)
        if (tableId == null)
        {
            if (!_cart.Any())
            {
                await Application.Current!.Windows[0].Page!.DisplayAlertAsync("Empty Cart", "Add items first.", "OK");
                return;
            }
            var order = await _api.CreateOrderAsync(_cart, null, _orderType, staffId: _loggedInStaffId);
            if (order != null)
            {
                _cart.Clear();
                _existingOrders.Clear();
                RefreshCart();
                await Application.Current!.Windows[0].Page!.DisplayAlertAsync(
                    "Order Placed!",
                    $"Order #{order.ReadableId} | {_orderType.Replace("_", "-").ToUpper()} | Direct",
                    "OK");
            }
            else
            {
                await Application.Current!.Windows[0].Page!.DisplayAlertAsync("Error", "Backend not reachable.", "OK");
            }
            return;
        }

        // Table selected — check there's something to bill
        if (!_existingOrders.Any() && !_cart.Any())
        {
            await Application.Current!.Windows[0].Page!.DisplayAlertAsync("No Orders", "No pending orders for this table.", "OK");
            return;
        }

        // Show payment method selector overlay
        _selectedPaymentMethod = "cash";
        UpdatePaymentButtons();
        PaymentOverlay.IsVisible = true;
    }

    private void OnPaymentMethodClicked(object? s, EventArgs e)
    {
        if (s is not Button btn) return;
        if (btn == BtnCash) _selectedPaymentMethod = "cash";
        else if (btn == BtnCard) _selectedPaymentMethod = "card";
        else if (btn == BtnUpi) _selectedPaymentMethod = "upi";
        UpdatePaymentButtons();
    }

    private void UpdatePaymentButtons()
    {
        foreach (var btn in new[] { BtnCash, BtnCard, BtnUpi })
        {
            btn.BackgroundColor = Colors.White;
            btn.TextColor = Color.FromArgb("#212529");
            btn.BorderColor = Color.FromArgb("#DEE2E6");
        }
        var active = _selectedPaymentMethod switch
        {
            "card" => BtnCard,
            "upi" => BtnUpi,
            _ => BtnCash
        };
        active.BackgroundColor = Color.FromArgb("#1B4332");
        active.TextColor = Colors.White;
        active.BorderColor = Color.FromArgb("#1B4332");
    }

    private void OnCancelPaymentClicked(object? s, EventArgs e)
    {
        PaymentOverlay.IsVisible = false;
    }

    private async void OnConfirmGenerateBillClicked(object? s, EventArgs e)
    {
        PaymentOverlay.IsVisible = false;
        var tableId = _selectedTable;

        // Step 1: If new items in cart, save them
        if (_cart.Any())
        {
            var newOrder = await _api.CreateOrderWithPaymentAsync(_cart, tableId, _orderType, _selectedPaymentMethod, _selectedZone, _loggedInStaffId);
            if (newOrder == null)
            {
                await Application.Current!.Windows[0].Page!.DisplayAlertAsync("Error", "Could not save new items.", "OK");
                return;
            }
        }

        // Step 2: Generate bill PDF with payment method
        var bill = await _api.GenerateBillAutoAsync(tableId, _selectedPaymentMethod, _selectedZone);
        if (bill == null)
        {
            await Application.Current!.Windows[0].Page!.DisplayAlertAsync("No Orders", "No pending orders found for this table.", "OK");
            return;
        }

        // Step 3: Settle all orders
        await _api.SettleTableAsync(tableId);

        // Step 4: Close table
        await _api.CloseTableAsync(tableId);

        // Step 5: Open PDF
        try
        {
            System.Diagnostics.Process.Start(new System.Diagnostics.ProcessStartInfo(bill.PdfPath) { UseShellExecute = true });
        }
        catch { /* PDF viewer not available */ }

        // Step 6: Show green toast banner
        var methodLabel = _selectedPaymentMethod.ToUpper();
        var zoneLabel = _selectedZone == "ac" ? "AC Dining ❄️" : "Regular Dining";
        ShowToast($"✅ Bill generated & Table {tableId} closed — {zoneLabel} — Total: ₹{bill.Total:F0} via {methodLabel}");

        // Step 7: Clear cart, deselect table, refresh
        _cart.Clear();
        _existingOrders.Clear();
        _selectedTable = "Direct";
        _selectedZone = "";
        foreach (var b in _allTableButtons)
        {
            b.BackgroundColor = Colors.White;
            b.TextColor = Color.FromArgb("#212529");
            if (b.Text != "Direct") b.BorderColor = Color.FromArgb("#DEE2E6");
        }
        var directBtnRef = _allTableButtons.FirstOrDefault(b => b.Text == "Direct");
        if (directBtnRef != null)
        {
            directBtnRef.BackgroundColor = Color.FromArgb("#1B4332");
            directBtnRef.TextColor = Colors.White;
        }
        ZoneBadge.IsVisible = false;
        RefreshCart();
        LoadTableOrderStatusAsync();
    }

    private async void ShowToast(string message)
    {
        ToastLabel.Text = message;
        ToastBanner.IsVisible = true;
        await Task.Delay(3000);
        ToastBanner.IsVisible = false;
    }

    // ── Add Dish panel ────────────────────────────────────────
    private void OnAddDishClicked(object? s, EventArgs e)
    {
        AddDishOverlay.IsVisible = true;
        AddDishStatus.Text = "";
        NewDishName.Text = "";
        NewDishPrice.Text = "";
        _newDishIsVeg = true;
        BtnVegSelect.BackgroundColor = Color.FromArgb("#28A745");
        BtnVegSelect.TextColor = Colors.White;
        BtnNonVegSelect.BackgroundColor = Color.FromArgb("#E8E8E8");
        BtnNonVegSelect.TextColor = Colors.Black;
    }

    private void OnCloseAddDishClicked(object? s, EventArgs e) => AddDishOverlay.IsVisible = false;

    private void OnVegSelectClicked(object? s, EventArgs e)
    {
        _newDishIsVeg = true;
        BtnVegSelect.BackgroundColor = Color.FromArgb("#28A745");
        BtnVegSelect.TextColor = Colors.White;
        BtnNonVegSelect.BackgroundColor = Color.FromArgb("#E8E8E8");
        BtnNonVegSelect.TextColor = Colors.Black;
    }

    private void OnNonVegSelectClicked(object? s, EventArgs e)
    {
        _newDishIsVeg = false;
        BtnNonVegSelect.BackgroundColor = Color.FromArgb("#DC3545");
        BtnNonVegSelect.TextColor = Colors.White;
        BtnVegSelect.BackgroundColor = Color.FromArgb("#E8E8E8");
        BtnVegSelect.TextColor = Colors.Black;
    }

    private async void OnConfirmAddDishClicked(object? s, EventArgs e)
    {
        var name = NewDishName.Text?.Trim();
        var priceText = NewDishPrice.Text?.Trim();
        var catName = NewDishCategory.SelectedItem?.ToString();

        if (string.IsNullOrEmpty(name))
        { AddDishStatus.Text = "Enter a dish name."; AddDishStatus.TextColor = Colors.Red; return; }

        if (!decimal.TryParse(priceText, out var price) || price <= 0)
        { AddDishStatus.Text = "Enter a valid price."; AddDishStatus.TextColor = Colors.Red; return; }

        if (catName == null)
        { AddDishStatus.Text = "Select a category."; AddDishStatus.TextColor = Colors.Red; return; }

        var catItem = _categoryItems.FirstOrDefault(c => c.Name == catName);
        var category = _categories.FirstOrDefault(c => c.Name == catName);
        var categoryId = catItem?.Id ?? category?.Id;
        if (categoryId == null) return;

        var sc = string.Concat(name.Where(char.IsLetter).Take(4)).ToUpper();
        AddDishStatus.Text = "Adding...";
        AddDishStatus.TextColor = Colors.Gray;

        var newItem = await _api.AddMenuItemAsync(categoryId, name, price, _newDishIsVeg, sc);
        if (newItem != null)
        {
            newItem.CategoryId = categoryId;
            if (category != null) category.Items.Add(newItem);
            _allItems.Add(newItem);
            AddDishStatus.Text = $"'{name}' added! Synced to customer app.";
            AddDishStatus.TextColor = Color.FromArgb("#28A745");
            Filter();
            await Task.Delay(1500);
            AddDishOverlay.IsVisible = false;
        }
        else
        {
            AddDishStatus.Text = "Failed. Check backend.";
            AddDishStatus.TextColor = Colors.Red;
        }
    }
}
