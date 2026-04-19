using System;
using System.Collections.Generic;
using System.Diagnostics;
using System.Threading.Tasks;
using Microsoft.Maui.Controls;
using Microsoft.Maui.Graphics;
using GustoWaiter.Models;
using GustoWaiter.Services;

namespace GustoWaiter.Views;

public class AlertsView : ContentView {
private readonly ApiService _api;
private readonly DashboardPage _dash;
private readonly StackLayout _list = new() { Spacing = 12, Padding = new Thickness(16) };
private readonly System.Threading.Timer _pollTimer;

public AlertsView(ApiService api, DashboardPage dash) {
    _api = api; _dash = dash;
    Content = new ScrollView { Content = _list, BackgroundColor = Color.FromArgb("#F8F9FA") };
    _pollTimer = new System.Threading.Timer(async _ => {
        try {
            var notifs = await _api.GetNotificationsAsync();
            await MainThread.InvokeOnMainThreadAsync(() => {
                try {
                    _dash.SetBadge(notifs.Count);
                    BuildList(notifs);
                } catch (Exception uiEx) {
                    System.Diagnostics.Debug.WriteLine($"UI update error: {uiEx.Message}");
                    CrashLogger.Log(uiEx, "AlertsView.UIUpdate");
                }
            });
        } catch (Exception ex) {
            Debug.WriteLine($"AlertsView poll error: {ex.Message}");
            CrashLogger.Log(ex, "AlertsView.Poll");
        }
    }, null, 0, 3000);
}

    public void Refresh(List<Notification> notifs) => BuildList(notifs);

    private async Task LoadAsync() => BuildList(await _api.GetNotificationsAsync());

    private void BuildList(List<Notification> notifs) {
        _list.Children.Clear();

        // Section header
        _list.Children.Add(new Label {
            Text = "Pending Actions",
            FontSize = 18, FontAttributes = FontAttributes.Bold,
            TextColor = Colors.Black, Margin = new Thickness(0, 8, 0, 4)
        });

        if (notifs.Count == 0) {
            // Empty state
            _list.Children.Add(new Border {
                BackgroundColor = Colors.White, StrokeThickness = 1,
                Stroke = Color.FromArgb("#E0E0E0"),
                StrokeShape = new Microsoft.Maui.Controls.Shapes.RoundRectangle { CornerRadius = 12 },
                Padding = new Thickness(24), Margin = new Thickness(0, 8),
                Content = new StackLayout {
                    HorizontalOptions = LayoutOptions.Center, Spacing = 8,
                    Children = {
                        new Label { Text = "✅", FontSize = 40, HorizontalOptions = LayoutOptions.Center },
                        new Label { Text = "All caught up!", FontSize = 16, FontAttributes = FontAttributes.Bold,
                                    TextColor = Colors.Black, HorizontalOptions = LayoutOptions.Center },
                        new Label { Text = "No pending customer confirmations.", FontSize = 13,
                                    TextColor = Color.FromArgb("#6C757D"), HorizontalOptions = LayoutOptions.Center }
                    }
                }
            });
            return;
        }

        foreach (var n in notifs) {
            if (n.Type == "order_placed")
                _list.Children.Add(BuildOrderPlacedCard(n));
            else
                _list.Children.Add(BuildCustomerCard(n));
        }
    }

    private View BuildCustomerCard(Notification n) {
        bool isCustom = n.Type == "custom_order";

        var card = new Border {
            BackgroundColor = Colors.White,
            StrokeThickness = 1,
            Stroke = isCustom ? Color.FromArgb("#FFC107") : Color.FromArgb("#28A745"),
            StrokeShape = new Microsoft.Maui.Controls.Shapes.RoundRectangle { CornerRadius = 12 },
            Padding = new Thickness(16), Margin = new Thickness(0, 4)
        };

        var typeBadge = new Border {
            BackgroundColor = isCustom ? Color.FromArgb("#FFC107") : Color.FromArgb("#1B4332"),
            StrokeThickness = 0,
            StrokeShape = new Microsoft.Maui.Controls.Shapes.RoundRectangle { CornerRadius = 6 },
            Padding = new Thickness(8, 3), HorizontalOptions = LayoutOptions.Start,
            Content = new Label {
                Text = isCustom ? "⚠️  CUSTOM REQUEST" : "👤  NEW CUSTOMER",
                TextColor = Colors.White, FontSize = 10, FontAttributes = FontAttributes.Bold
            }
        };

        var tableBadge = new Border {
            BackgroundColor = Color.FromArgb("#1B4332"),
            StrokeThickness = 0,
            StrokeShape = new Microsoft.Maui.Controls.Shapes.RoundRectangle { CornerRadius = 6 },
            Padding = new Thickness(10, 3), HorizontalOptions = LayoutOptions.End,
            Content = new Label {
                Text = n.TableId, TextColor = Colors.White, FontSize = 13, FontAttributes = FontAttributes.Bold
            }
        };

        var headerRow = new Grid { ColumnDefinitions = { new ColumnDefinition(GridLength.Star), new ColumnDefinition(GridLength.Auto) } };
        headerRow.Add(typeBadge, 0, 0);
        headerRow.Add(tableBadge, 1, 0);

        var customerLabel = new Label {
            Text = n.CustomerName, FontSize = 15, FontAttributes = FontAttributes.Bold,
            TextColor = Colors.Black, Margin = new Thickness(0, 8, 0, 0)
        };

        var descLabel = new Label {
            Text = isCustom ? n.OrderPreview : "Walk to this table and confirm the customer is present.",
            FontSize = 13, TextColor = Color.FromArgb("#6C757D"),
            LineBreakMode = LineBreakMode.WordWrap, Margin = new Thickness(0, 2, 0, 12)
        };

        var confirmBtn = new Button {
            Text = isCustom ? "✅  Handled" : "✅  Confirm",
            BackgroundColor = Color.FromArgb("#28A745"), TextColor = Colors.White,
            CornerRadius = 8, FontSize = 13, FontAttributes = FontAttributes.Bold,
            HeightRequest = 44
        };

        confirmBtn.Clicked += async (s, e) => {
            try {
                confirmBtn.IsEnabled = false;
                await _api.RespondToNotificationAsync(n.Id, true);
                await LoadAsync();
            } catch (Exception ex) {
                CrashLogger.Log(ex, "AlertsView.ConfirmClicked");
                Debug.WriteLine($"Confirm click error: {ex.Message}");
            } finally {
                await MainThread.InvokeOnMainThreadAsync(() => confirmBtn.IsEnabled = true);
            }
        };

        var content = new StackLayout { Spacing = 4, Children = { headerRow, customerLabel, descLabel } };

        if (!isCustom) {
            var rejectBtn = new Button {
                Text = "❌  Reject",
                BackgroundColor = Color.FromArgb("#DC3545"), TextColor = Colors.White,
                CornerRadius = 8, FontSize = 13, FontAttributes = FontAttributes.Bold,
                HeightRequest = 44
            };
            rejectBtn.Clicked += async (s, e) => {
                try {
                    bool sure = await Application.Current!.Windows[0].Page!.DisplayAlertAsync(
                        "Reject?", $"Reject session for {n.CustomerName} at {n.TableId}?", "Reject", "Cancel");
                    if (!sure) return;
                    await _api.RespondToNotificationAsync(n.Id, false);
                    await LoadAsync();
                } catch (Exception ex) {
                    CrashLogger.Log(ex, "AlertsView.RejectClicked");
                }
            };
            var btnRow = new Grid { ColumnSpacing = 8, ColumnDefinitions = { new(GridLength.Star), new(GridLength.Star) } };
            btnRow.Add(confirmBtn, 0, 0); btnRow.Add(rejectBtn, 1, 0);
            content.Children.Add(btnRow);
        } else {
            content.Children.Add(confirmBtn);
        }

        card.Content = content;
        return card;
    }

    private View BuildOrderPlacedCard(Notification n) {
        var card = new Border {
            BackgroundColor = Color.FromArgb("#FFFBF0"),
            StrokeThickness = 2,
            Stroke = Color.FromArgb("#856404"),
            StrokeShape = new Microsoft.Maui.Controls.Shapes.RoundRectangle { CornerRadius = 12 },
            Padding = new Thickness(16), Margin = new Thickness(0, 4)
        };

        var typeBadge = new Border {
            BackgroundColor = Color.FromArgb("#856404"),
            StrokeThickness = 0,
            StrokeShape = new Microsoft.Maui.Controls.Shapes.RoundRectangle { CornerRadius = 6 },
            Padding = new Thickness(8, 3), HorizontalOptions = LayoutOptions.Start,
            Content = new Label {
                Text = "🛎️  NEW ORDER",
                TextColor = Colors.White, FontSize = 10, FontAttributes = FontAttributes.Bold
            }
        };

        var tableBadge = new Border {
            BackgroundColor = Color.FromArgb("#1B4332"),
            StrokeThickness = 0,
            StrokeShape = new Microsoft.Maui.Controls.Shapes.RoundRectangle { CornerRadius = 6 },
            Padding = new Thickness(10, 3), HorizontalOptions = LayoutOptions.End,
            Content = new Label {
                Text = n.TableId, TextColor = Colors.White, FontSize = 13, FontAttributes = FontAttributes.Bold
            }
        };

        var headerRow = new Grid { ColumnDefinitions = { new(GridLength.Star), new(GridLength.Auto) } };
        headerRow.Add(typeBadge, 0, 0);
        headerRow.Add(tableBadge, 1, 0);

        var customerLabel = new Label {
            Text = $"Customer: {n.CustomerName}", FontSize = 14, FontAttributes = FontAttributes.Bold,
            TextColor = Color.FromArgb("#495057"), Margin = new Thickness(0, 8, 0, 4)
        };

        var itemsStack = new StackLayout { Spacing = 2 };
        if (n.OrderItems?.Any() == true) {
            foreach (var item in n.OrderItems) {
                var itemText = $"• {item.Name} x{item.Quantity}";
                if (item.Customizations.Any())
                    itemText += $" — {string.Join(", ", item.Customizations)}";
                itemsStack.Children.Add(new Label {
                    Text = itemText, FontSize = 13, TextColor = Color.FromArgb("#495057")
                });
                if (!string.IsNullOrEmpty(item.CustomNote))
                    itemsStack.Children.Add(new Label {
                        Text = $"  \"{item.CustomNote}\"", FontSize = 12,
                        TextColor = Color.FromArgb("#6C757D"), FontAttributes = FontAttributes.Italic
                    });
            }
        } else if (!string.IsNullOrEmpty(n.OrderPreview)) {
            foreach (var line in n.OrderPreview.Split('\n'))
                itemsStack.Children.Add(new Label {
                    Text = $"• {line}", FontSize = 13, TextColor = Color.FromArgb("#495057")
                });
        }

        var totalLabel = new Label {
            Text = (n.TotalAmount ?? 0m) > 0 ? $"Total: ₹{(n.TotalAmount ?? 0m):F0}" : "",
            FontSize = 15, FontAttributes = FontAttributes.Bold,
            TextColor = Color.FromArgb("#1B4332"), Margin = new Thickness(0, 6, 0, 10)
        };

        var openBtn = new Button {
            Text = "📋  Open & Review",
            BackgroundColor = Color.FromArgb("#856404"), TextColor = Colors.White,
            CornerRadius = 8, FontSize = 13, FontAttributes = FontAttributes.Bold,
            HeightRequest = 44
        };
        openBtn.Clicked += async (s, e) => {
            try {
                await _api.RespondToNotificationAsync(n.Id, true);
                var page = new ApprovalChecklistPage(_api, n);
                await Application.Current!.Windows[0].Page!.Navigation.PushAsync(page);
                await LoadAsync();
            } catch (Exception ex) {
                CrashLogger.Log(ex, "AlertsView.OpenReview");
            }
        };

        var ignoreBtn = new Button {
            Text = "❌  Ignore",
            BackgroundColor = Color.FromArgb("#DC3545"), TextColor = Colors.White,
            CornerRadius = 8, FontSize = 13, FontAttributes = FontAttributes.Bold,
            HeightRequest = 44
        };
        ignoreBtn.Clicked += async (s, e) => {
            try {
                await _api.RespondToNotificationAsync(n.Id, false);
                await LoadAsync();
            } catch (Exception ex) {
                CrashLogger.Log(ex, "AlertsView.Ignore");
            }
        };

        var btnRow = new Grid { ColumnSpacing = 8, ColumnDefinitions = { new(GridLength.Star), new(GridLength.Star) } };
        btnRow.Add(openBtn, 0, 0);
        btnRow.Add(ignoreBtn, 1, 0);

        var content = new StackLayout { Spacing = 4, Children = { headerRow, customerLabel, itemsStack, totalLabel, btnRow } };
        card.Content = content;
        return card;
    }
}

