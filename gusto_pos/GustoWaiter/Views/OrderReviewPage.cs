using System;
using System.Collections.Generic;
using System.Linq;
using System.Text.Json;
using System.Threading.Tasks;
using Microsoft.Maui.Controls;
using Microsoft.Maui.Graphics;
using GustoWaiter.Models;
using GustoWaiter.Services;

namespace GustoWaiter.Views;

public class OrderReviewPage : ContentPage {
    private readonly ApiService _api;
    private readonly Notification _notif;
    private List<CartItem> _items = new();
    private List<MenuCategory> _menuCategories = new();
    private readonly StackLayout _itemsStack = new() { Spacing = 8 };
    private readonly StackLayout _searchResultsStack = new() { Spacing = 4 };
    private readonly Label _subtotalLabel = new() { FontSize = 14, TextColor = Color.FromArgb("#495057") };
    private readonly Label _gstLabel = new() { FontSize = 14, TextColor = Color.FromArgb("#495057") };
    private readonly Label _totalLabel = new() { FontSize = 18, FontAttributes = FontAttributes.Bold, TextColor = Color.FromArgb("#1B4332") };
    private Button _sendBtn = new();
    private bool _modified;

    public OrderReviewPage(ApiService api, Notification notif) {
        _api = api;
        _notif = notif;
        NavigationPage.SetHasNavigationBar(this, false);

        // Populate initial items from structured data attached to the notification
        if (notif.OrderItems != null) {
            foreach (var oi in notif.OrderItems) {
                _items.Add(new CartItem {
                    MenuItemId = "",
                    Name = oi.Name,
                    BasePrice = oi.UnitPrice,
                    Quantity = oi.Quantity,
                    Customizations = oi.Customizations.ToList(),
                    Note = oi.CustomNote
                });
            }
        }

        // Fallback: OrderPreview may be a JSON array string — parse it properly
        if (!_items.Any() && !string.IsNullOrEmpty(notif.OrderPreview)) {
            var parsed = ParseOrderPreviewJson(notif.OrderPreview);
            if (parsed.Count > 0) {
                foreach (var (name, qty) in parsed)
                    _items.Add(new CartItem { Name = name, BasePrice = 0, Quantity = qty });
            } else {
                foreach (var line in notif.OrderPreview.Split('\n')) {
                    if (string.IsNullOrWhiteSpace(line)) continue;
                    _items.Add(new CartItem { Name = line.Trim(), BasePrice = 0, Quantity = 1 });
                }
            }
        }

        BuildLayout();
        _ = LoadDataAsync();
    }

    private static List<(string Name, int Qty)> ParseOrderPreviewJson(string preview) {
        var result = new List<(string, int)>();
        try {
            if (!preview.TrimStart().StartsWith("[")) return result;
            using var doc = JsonDocument.Parse(preview);
            foreach (var el in doc.RootElement.EnumerateArray()) {
                var name = el.TryGetProperty("name", out var n) ? n.GetString() ?? "" : "";
                var qty  = el.TryGetProperty("quantity", out var q) ? q.GetInt32() : 1;
                if (!string.IsNullOrEmpty(name))
                    result.Add((name, qty));
            }
        } catch { }
        return result;
    }

    private async Task LoadDataAsync() {
        if (!string.IsNullOrEmpty(_notif.OrderId)) {
            var details = await _api.GetOrderDetailsAsync(_notif.OrderId);
            if (details.HasValue) {
                try {
                    var root = details.Value;
                    if (root.TryGetProperty("items", out var itemsArr)) {
                        _items.Clear();
                        foreach (var el in itemsArr.EnumerateArray()) {
                            var name  = el.TryGetProperty("name", out var n)        ? n.GetString()   ?? "" : "";
                            var qty   = el.TryGetProperty("quantity", out var q)    ? q.GetInt32()         : 1;
                            var price = el.TryGetProperty("unit_price", out var p)  ? p.GetDecimal()       : 0m;
                            var note  = el.TryGetProperty("custom_note", out var nt) ? nt.GetString() ?? "" : "";
                            var custs = new List<string>();
                            if (el.TryGetProperty("customizations", out var ca) && ca.ValueKind == JsonValueKind.Array)
                                foreach (var c in ca.EnumerateArray())
                                    custs.Add(c.GetString() ?? "");
                            _items.Add(new CartItem {
                                Name = name, BasePrice = price, Quantity = qty,
                                Note = note, Customizations = custs
                            });
                        }
                        // Always dispatch UI updates back to the main thread
                        await MainThread.InvokeOnMainThreadAsync(RenderItems);
                    }
                } catch { }
            }
        }
        var zone = await _api.GetMenuByZoneAsync("normal");
        if (zone != null) _menuCategories = zone.Categories;
    }

    private void BuildLayout() {
        var backBtn = new Button {
            Text = "Back", BackgroundColor = Colors.Transparent,
            TextColor = Colors.White, FontSize = 14, FontAttributes = FontAttributes.Bold,
            WidthRequest = 60, HeightRequest = 44, Padding = new Thickness(0)
        };
        backBtn.Clicked += async (s, e) => {
            try { await Navigation.PopAsync(); }
            catch (Exception ex) { CrashLogger.Log(ex, "OrderReviewPage.BackBtnClicked"); }
        };

        var headerBar = new Grid {
            BackgroundColor = Color.FromArgb("#1B4332"),
            Padding = new Thickness(8, 0, 16, 0),
            HeightRequest = 56,
            ColumnDefinitions = { new(GridLength.Auto), new(GridLength.Star) }
        };
        headerBar.Add(backBtn, 0, 0);
        headerBar.Add(new Label {
            Text = $"Review Order  -  Table {_notif.TableId}",
            TextColor = Colors.White, FontSize = 18,
            FontAttributes = FontAttributes.Bold,
            VerticalOptions = LayoutOptions.Center
        }, 1, 0);

        var customerOrderTitle = new Label {
            Text = "Customer's Order", FontSize = 16,
            FontAttributes = FontAttributes.Bold,
            TextColor = Color.FromArgb("#1B4332"),
            Margin = new Thickness(16, 12, 16, 4)
        };

        var fromLabel = new Label {
            Text = $"From: {_notif.CustomerName}",
            FontSize = 13, TextColor = Color.FromArgb("#6C757D"),
            Margin = new Thickness(16, 0, 16, 8)
        };

        _itemsStack.Padding = new Thickness(16, 0);

        var addMoreTitle = new Label {
            Text = "Add More Items", FontSize = 16,
            FontAttributes = FontAttributes.Bold,
            TextColor = Color.FromArgb("#1B4332"),
            Margin = new Thickness(16, 12, 16, 4)
        };

        var searchEntry = new Entry {
            Placeholder = "Search menu...", PlaceholderColor = Color.FromArgb("#AAAAAA"),
            BackgroundColor = Colors.White, TextColor = Colors.Black, FontSize = 14
        };
        searchEntry.TextChanged += (s, e) => FilterMenuItems(e.NewTextValue ?? "");

        var searchBorder = new Border {
            BackgroundColor = Colors.White, StrokeThickness = 1,
            Stroke = Color.FromArgb("#E0E0E0"),
            StrokeShape = new Microsoft.Maui.Controls.Shapes.RoundRectangle { CornerRadius = 10 },
            Padding = new Thickness(12, 0), Margin = new Thickness(16, 0, 16, 4),
            Content = searchEntry
        };

        _searchResultsStack.Padding = new Thickness(16, 0);

        var summarySection = new StackLayout {
            Margin = new Thickness(16, 12), Spacing = 4,
            Children = { _subtotalLabel, _gstLabel, _totalLabel }
        };

        var bodyScroll = new ScrollView {
            Content = new StackLayout {
                Padding = new Thickness(0, 0, 0, 120), Spacing = 0,
                Children = {
                    customerOrderTitle, fromLabel,
                    _itemsStack,
                    addMoreTitle, searchBorder,
                    _searchResultsStack,
                    summarySection
                }
            }
        };

        _sendBtn = new Button {
            Text = "Send to Kitchen",
            BackgroundColor = Color.FromArgb("#28A745"), TextColor = Colors.White,
            CornerRadius = 10, FontSize = 16, FontAttributes = FontAttributes.Bold,
            HeightRequest = 52, Margin = new Thickness(16, 8)
        };
        _sendBtn.Clicked += OnSendToKitchen;

        var bottomPanel = new StackLayout {
            BackgroundColor = Colors.White, Padding = new Thickness(0, 8),
            Children = { _sendBtn }
        };
        bottomPanel.Shadow = new Shadow { Brush = Brush.Black, Offset = new Point(0, -4), Radius = 12, Opacity = 0.1f };

        var root = new Grid {
            RowDefinitions = { new(GridLength.Auto), new(GridLength.Star), new(GridLength.Auto) },
            BackgroundColor = Color.FromArgb("#F8F9FA")
        };
        root.Add(headerBar, 0, 0);
        root.Add(bodyScroll, 0, 1);
        root.Add(bottomPanel, 0, 2);

        Content = root;
        RenderItems();
    }

    private void RenderItems() {
        _itemsStack.Children.Clear();
        foreach (var item in _items.ToList()) {
            var captured = item;
            var card = new Border {
                BackgroundColor = Colors.White, StrokeThickness = 1,
                Stroke = Color.FromArgb("#DEE2E6"),
                StrokeShape = new Microsoft.Maui.Controls.Shapes.RoundRectangle { CornerRadius = 8 },
                Padding = new Thickness(12, 10), Margin = new Thickness(0, 4)
            };

            var nameLabel = new Label {
                Text = captured.Name, FontSize = 14, FontAttributes = FontAttributes.Bold,
                TextColor = Colors.Black, VerticalOptions = LayoutOptions.Center
            };

            var priceLabel = new Label {
                Text = captured.BasePrice > 0 ? $"Rs.{captured.ItemTotal:F0}" : "",
                FontSize = 13, TextColor = Color.FromArgb("#1B4332"),
                VerticalOptions = LayoutOptions.Center
            };

            var qtyLabel = new Label {
                Text = captured.Quantity.ToString(),
                FontSize = 14, FontAttributes = FontAttributes.Bold,
                TextColor = Colors.Black, VerticalOptions = LayoutOptions.Center,
                HorizontalOptions = LayoutOptions.Center, MinimumWidthRequest = 28,
                HorizontalTextAlignment = TextAlignment.Center
            };

            var minusBtn = new Button {
                Text = "-", BackgroundColor = Color.FromArgb("#F8D7DA"),
                TextColor = Color.FromArgb("#721C24"),
                CornerRadius = 6, FontSize = 16, FontAttributes = FontAttributes.Bold,
                WidthRequest = 34, HeightRequest = 34, Padding = new Thickness(0)
            };
            minusBtn.Clicked += (s, e) => {
                captured.Quantity--;
                _modified = true;
                if (captured.Quantity <= 0) _items.Remove(captured);
                RenderItems();
            };

            var plusBtn = new Button {
                Text = "+", BackgroundColor = Color.FromArgb("#D4EDDA"),
                TextColor = Color.FromArgb("#155724"),
                CornerRadius = 6, FontSize = 16, FontAttributes = FontAttributes.Bold,
                WidthRequest = 34, HeightRequest = 34, Padding = new Thickness(0)
            };
            plusBtn.Clicked += (s, e) => {
                captured.Quantity++;
                _modified = true;
                RenderItems();
            };

            var qtyRow = new StackLayout {
                Orientation = StackOrientation.Horizontal, Spacing = 6,
                VerticalOptions = LayoutOptions.Center,
                Children = { minusBtn, qtyLabel, plusBtn, priceLabel }
            };

            var topRow = new Grid { ColumnDefinitions = { new(GridLength.Star), new(GridLength.Auto) } };
            topRow.Add(nameLabel, 0, 0);
            topRow.Add(qtyRow, 1, 0);

            var content = new StackLayout { Spacing = 4, Children = { topRow } };

            var custParts = captured.Customizations
                .Where(c => !string.IsNullOrWhiteSpace(c)).ToList();
            var custText = custParts.Any() ? string.Join(", ", custParts) : "";
            if (!string.IsNullOrWhiteSpace(captured.Note))
                custText = string.IsNullOrEmpty(custText)
                    ? $"Note: {captured.Note}"
                    : $"{custText}  |  Note: {captured.Note}";
            if (!string.IsNullOrEmpty(custText)) {
                content.Children.Add(new Label {
                    Text = custText, FontSize = 11,
                    TextColor = Color.FromArgb("#6C757D"), FontAttributes = FontAttributes.Italic,
                    LineBreakMode = LineBreakMode.WordWrap
                });
            }

            card.Content = content;
            _itemsStack.Children.Add(card);
        }

        UpdateSummary();
    }

    private void UpdateSummary() {
        var subtotal = _items.Sum(i => i.ItemTotal);
        var gst      = subtotal * 0.05m;
        var total    = subtotal + gst;
        _subtotalLabel.Text = $"Items Subtotal: Rs.{subtotal:F0}";
        _gstLabel.Text      = $"GST 5%: Rs.{gst:F0}";
        _totalLabel.Text    = $"TOTAL: Rs.{total:F0}";
    }

    private void FilterMenuItems(string query) {
        _searchResultsStack.Children.Clear();
        if (string.IsNullOrWhiteSpace(query) || query.Length < 2) return;

        var q = query.ToLower();
        var matches = _menuCategories
            .SelectMany(c => c.Items)
            .Where(i => i.Name.ToLower().Contains(q) && i.IsAvailable)
            .Take(8)
            .ToList();

        foreach (var mi in matches) {
            var addBtn = new Button {
                Text = $"{mi.Name}   Rs.{mi.DisplayPrice:F0}",
                BackgroundColor = Color.FromArgb("#E8F5E9"), TextColor = Color.FromArgb("#1B4332"),
                CornerRadius = 8, FontSize = 13, HeightRequest = 40,
                HorizontalOptions = LayoutOptions.Fill
            };
            addBtn.Clicked += (s, e) => {
                var existing = _items.FirstOrDefault(i => i.Name == mi.Name);
                if (existing != null) existing.Quantity++;
                else _items.Add(new CartItem {
                    MenuItemId = mi.Id, Name = mi.Name,
                    BasePrice = mi.DisplayPrice, Quantity = 1
                });
                _modified = true;
                RenderItems();
            };
            _searchResultsStack.Children.Add(addBtn);
        }
    }

    private async void OnSendToKitchen(object? s, EventArgs e) {
        try {
            _sendBtn.IsEnabled = false;

            // 1. Persist any waiter-added items back to the order
            if (!string.IsNullOrEmpty(_notif.OrderId)) {
                if (_modified)
                    await _api.UpdateOrderItemsAsync(_notif.OrderId, _items);

                // 2. Confirm the order — sets status to "confirmed" and broadcasts to kitchen/POS
                await _api.ConfirmOrderAsync(_notif.OrderId);
            }

            // 3. Dismiss the notification from the Pending Actions list
            await _api.RespondToNotificationAsync(_notif.Id, true);

            // 4. Return to dashboard — AlertsView will refresh on next load
            await Navigation.PopAsync();
        } catch (Exception ex) {
            CrashLogger.Log(ex, "OrderReviewPage.OnSendToKitchen");
            _sendBtn.IsEnabled = true;
        }
    }
}
