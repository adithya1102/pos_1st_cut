using System;
using System.Collections.Generic;
using System.Linq;
using System.Threading.Tasks;
using Microsoft.Maui.Controls;
using Microsoft.Maui.Graphics;
using GustoWaiter.Models;
using GustoWaiter.Services;

namespace GustoWaiter.Views;

public class OrderApprovalPage : ContentPage {
    private readonly ApiService _api;
    private readonly string _orderId;
    private readonly string _tableId;
    private readonly decimal _totalAmount;
    private readonly StackLayout _itemsStack = new() { Spacing = 0 };
    private readonly ActivityIndicator _spinner;
    private string? _notifId;
    private bool _actionTaken;

    // Fired just before the page pops so the caller can refresh its UI.
    public event Action? Dismissed;

    public OrderApprovalPage(ApiService api, string orderId, string tableId, decimal totalAmount) {
        _api = api;
        _orderId = orderId;
        _tableId = string.IsNullOrEmpty(tableId) ? "—" : tableId;
        _totalAmount = totalAmount;
        NavigationPage.SetHasNavigationBar(this, false);
        BackgroundColor = Color.FromArgb("#CC000000");
        _spinner = new ActivityIndicator {
            IsRunning = true, Color = Color.FromArgb("#1B4332"),
            HorizontalOptions = LayoutOptions.Center, Margin = new Thickness(0, 24)
        };
        BuildLayout();
    }

    protected override void OnAppearing() {
        base.OnAppearing();
        _ = LoadAsync();
    }

    // ── Layout ────────────────────────────────────────────────────────────────

    private void BuildLayout() {
        // Header bar
        var headerGrid = new Grid {
            BackgroundColor = Color.FromArgb("#1B4332"),
            Padding = new Thickness(20, 14),
            ColumnDefinitions = { new(GridLength.Star), new(GridLength.Auto) }
        };
        headerGrid.Add(new StackLayout {
            Spacing = 2, VerticalOptions = LayoutOptions.Center,
            Children = {
                new Label {
                    Text = "🛎️  NEW ORDER",
                    TextColor = Colors.White, FontSize = 17, FontAttributes = FontAttributes.Bold
                },
                new Label {
                    Text = "Approve to fire to kitchen · Reject to cancel",
                    TextColor = Color.FromArgb("#A8D5B5"), FontSize = 11
                }
            }
        }, 0, 0);
        headerGrid.Add(new Border {
            BackgroundColor = Color.FromArgb("#28A745"), StrokeThickness = 0,
            StrokeShape = new Microsoft.Maui.Controls.Shapes.RoundRectangle { CornerRadius = 10 },
            Padding = new Thickness(14, 8), VerticalOptions = LayoutOptions.Center,
            Content = new Label {
                Text = _tableId, TextColor = Colors.White,
                FontSize = 18, FontAttributes = FontAttributes.Bold,
                HorizontalOptions = LayoutOptions.Center
            }
        }, 1, 0);

        // Items scroll area with spinner
        var itemsScroll = new ScrollView {
            MaximumHeightRequest = 320,
            Content = new StackLayout {
                Padding = new Thickness(20, 10, 20, 4), Spacing = 0,
                Children = { _spinner, _itemsStack }
            }
        };

        // Total row
        var dividerTop = new BoxView { HeightRequest = 1, BackgroundColor = Color.FromArgb("#E9ECEF") };
        var totalGrid = new Grid {
            Padding = new Thickness(20, 12),
            ColumnDefinitions = { new(GridLength.Star), new(GridLength.Auto) }
        };
        totalGrid.Add(new Label {
            Text = "ORDER TOTAL",
            TextColor = Color.FromArgb("#6C757D"), FontSize = 12, FontAttributes = FontAttributes.Bold,
            VerticalOptions = LayoutOptions.Center
        }, 0, 0);
        totalGrid.Add(new Label {
            Text = $"₹{_totalAmount:F0}",
            TextColor = Color.FromArgb("#1B4332"), FontSize = 22, FontAttributes = FontAttributes.Bold,
            VerticalOptions = LayoutOptions.Center
        }, 1, 0);

        // Approve / Reject buttons
        var dividerBot = new BoxView { HeightRequest = 1, BackgroundColor = Color.FromArgb("#E9ECEF") };
        var approveBtn = new Button {
            Text = "✅  Approve", BackgroundColor = Color.FromArgb("#28A745"), TextColor = Colors.White,
            CornerRadius = 10, FontSize = 15, FontAttributes = FontAttributes.Bold, HeightRequest = 52
        };
        var rejectBtn = new Button {
            Text = "❌  Reject", BackgroundColor = Color.FromArgb("#DC3545"), TextColor = Colors.White,
            CornerRadius = 10, FontSize = 15, FontAttributes = FontAttributes.Bold, HeightRequest = 52
        };
        approveBtn.Clicked += OnApprove;
        rejectBtn.Clicked  += OnReject;

        var btnGrid = new Grid {
            ColumnSpacing = 12, Padding = new Thickness(20, 12, 20, 20),
            ColumnDefinitions = { new(GridLength.Star), new(GridLength.Star) }
        };
        btnGrid.Add(approveBtn, 0, 0);
        btnGrid.Add(rejectBtn,  1, 0);

        // White card
        var card = new Border {
            BackgroundColor = Colors.White, StrokeThickness = 0,
            StrokeShape = new Microsoft.Maui.Controls.Shapes.RoundRectangle { CornerRadius = 16 },
            HorizontalOptions = LayoutOptions.Fill, VerticalOptions = LayoutOptions.Center,
            Margin = new Thickness(16),
            Shadow = new Shadow { Brush = Brush.Black, Offset = new Point(0, 8), Radius = 40, Opacity = 0.5f },
            Content = new StackLayout {
                Spacing = 0,
                Children = { headerGrid, itemsScroll, dividerTop, totalGrid, dividerBot, btnGrid }
            }
        };

        var root = new Grid { BackgroundColor = Color.FromArgb("#AA000000") };
        root.Children.Add(card);
        Content = root;
    }

    // ── Data loading ──────────────────────────────────────────────────────────

    private async Task LoadAsync() {
        try {
            var notifs = await _api.GetNotificationsAsync();
            var match  = notifs.FirstOrDefault(n => n.OrderId == _orderId);
            await MainThread.InvokeOnMainThreadAsync(() => {
                _spinner.IsRunning = false;
                _spinner.IsVisible = false;
                if (match != null) {
                    _notifId = match.Id;
                    RenderItems(match);
                } else {
                    _itemsStack.Children.Add(new Label {
                        Text = "Item details loading…",
                        TextColor = Color.FromArgb("#6C757D"), FontSize = 13,
                        HorizontalOptions = LayoutOptions.Center, Margin = new Thickness(0, 8)
                    });
                }
            });
        } catch (Exception ex) {
            CrashLogger.Log(ex, "OrderApprovalPage.LoadAsync");
            await MainThread.InvokeOnMainThreadAsync(() => {
                _spinner.IsRunning = false;
                _spinner.IsVisible = false;
            });
        }
    }

    private void RenderItems(Notification notif) {
        _itemsStack.Children.Clear();

        List<(string Name, int Qty, decimal Price, List<string> Custs, string Note)> list;

        if (notif.OrderItems?.Any() == true) {
            list = notif.OrderItems
                .Select(oi => (oi.Name, oi.Quantity, oi.UnitPrice, oi.Customizations, oi.CustomNote))
                .ToList();
        } else if (!string.IsNullOrEmpty(notif.OrderPreview)) {
            list = ParsePreviewJson(notif.OrderPreview)
                .Select(p => (p.Name, p.Qty, 0m, new List<string>(), ""))
                .ToList();
        } else {
            list = new();
        }

        if (!list.Any()) {
            _itemsStack.Children.Add(new Label {
                Text = "No item details available.",
                TextColor = Color.FromArgb("#6C757D"), FontSize = 13,
                HorizontalOptions = LayoutOptions.Center, Margin = new Thickness(0, 8)
            });
            return;
        }

        for (int i = 0; i < list.Count; i++) {
            var (name, qty, price, custs, note) = list[i];
            var topRow = new Grid {
                Padding = new Thickness(0, 7, 0, 3),
                ColumnDefinitions = { new(GridLength.Star), new(GridLength.Auto) }
            };
            topRow.Add(new Label {
                Text = $"{name}  ×{qty}",
                FontSize = 14, FontAttributes = FontAttributes.Bold,
                TextColor = Colors.Black, VerticalOptions = LayoutOptions.Center
            }, 0, 0);
            topRow.Add(new Label {
                Text = price > 0 ? $"₹{price * qty:F0}" : "",
                FontSize = 14, TextColor = Color.FromArgb("#1B4332"),
                VerticalOptions = LayoutOptions.Center
            }, 1, 0);

            var block = new StackLayout { Spacing = 1, Children = { topRow } };

            var custParts = custs.Where(c => !string.IsNullOrWhiteSpace(c)).ToList();
            if (custParts.Any())
                block.Children.Add(new Label {
                    Text = string.Join("  ·  ", custParts),
                    FontSize = 11, TextColor = Color.FromArgb("#6C757D"),
                    FontAttributes = FontAttributes.Italic, Margin = new Thickness(0, 0, 0, 4)
                });
            if (!string.IsNullOrWhiteSpace(note))
                block.Children.Add(new Label {
                    Text = $"📝 {note}",
                    FontSize = 11, TextColor = Color.FromArgb("#856404"),
                    FontAttributes = FontAttributes.Italic, Margin = new Thickness(0, 0, 0, 4)
                });

            _itemsStack.Children.Add(block);

            if (i < list.Count - 1)
                _itemsStack.Children.Add(new BoxView {
                    HeightRequest = 1, BackgroundColor = Color.FromArgb("#F0F0F0"),
                    Margin = new Thickness(0, 3)
                });
        }
    }

    private static List<(string Name, int Qty)> ParsePreviewJson(string preview) {
        var result = new List<(string, int)>();
        try {
            if (!preview.TrimStart().StartsWith("[")) return result;
            using var doc = System.Text.Json.JsonDocument.Parse(preview);
            foreach (var el in doc.RootElement.EnumerateArray()) {
                var name = el.TryGetProperty("name", out var n) ? n.GetString() ?? "" : "";
                var qty  = el.TryGetProperty("quantity", out var q) ? q.GetInt32() : 1;
                if (!string.IsNullOrEmpty(name)) result.Add((name, qty));
            }
        } catch { }
        return result;
    }

    // ── Actions ───────────────────────────────────────────────────────────────

    private async void OnApprove(object? sender, EventArgs e) {
        if (_actionTaken) return;
        _actionTaken = true;
        try {
            await _api.ConfirmOrderAsync(_orderId);
            if (!string.IsNullOrEmpty(_notifId))
                await _api.RespondToNotificationAsync(_notifId, true);
        } catch (Exception ex) {
            CrashLogger.Log(ex, "OrderApprovalPage.OnApprove");
        }
        Dismissed?.Invoke();
        await Application.Current!.Windows[0].Page!.Navigation.PopModalAsync(false);
    }

    private async void OnReject(object? sender, EventArgs e) {
        if (_actionTaken) return;
        _actionTaken = true;
        try {
            await _api.RejectOrderAsync(_orderId);
            if (!string.IsNullOrEmpty(_notifId))
                await _api.RespondToNotificationAsync(_notifId, false);
        } catch (Exception ex) {
            CrashLogger.Log(ex, "OrderApprovalPage.OnReject");
        }
        Dismissed?.Invoke();
        await Application.Current!.Windows[0].Page!.Navigation.PopModalAsync(false);
    }
}
