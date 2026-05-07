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

public class TablesView : ContentView {
    private readonly ApiService _api;
    private readonly DashboardPage _dash;
    private readonly Grid _normalGrid = new() { ColumnSpacing = 10, RowSpacing = 10 };
    private readonly Grid _acGrid = new() { ColumnSpacing = 10, RowSpacing = 10 };
    private System.Threading.Timer? _refreshTimer;

    public TablesView(ApiService api, DashboardPage dash) {
        _api = api;
        _dash = dash;
        BuildLayout();
        Loaded += OnLoaded;
        Unloaded += OnUnloaded;
    }

    private async void OnLoaded(object? sender, EventArgs e) {
        try {
            await RefreshTables();
        } catch (Exception ex) {
            CrashLogger.Log(ex, "TablesView.OnLoaded");
        }
        _refreshTimer?.Dispose();
        _refreshTimer = new System.Threading.Timer(async _ => {
            try { await RefreshTables(); }
            catch (Exception ex) { CrashLogger.Log(ex, "TablesView.Timer"); }
        }, null, 10000, 10000);
    }


    private void OnUnloaded(object? sender, EventArgs e) {
        _refreshTimer?.Dispose();
        _refreshTimer = null;
    }

    private void BuildLayout() {
        var title = new Label {
            Text = "Tables", FontSize = 18,
            FontAttributes = FontAttributes.Bold,
            TextColor = Color.FromArgb("#212529")
        };

        var normalHeader = new Border {
            BackgroundColor = Color.FromArgb("#F8F9FA"),
            StrokeThickness = 0,
            Padding = new Thickness(12, 8),
            Margin = new Thickness(0, 8, 0, 4),
            Content = new Label {
                Text = "NORMAL DINING", FontSize = 14,
                FontAttributes = FontAttributes.Bold,
                TextColor = Color.FromArgb("#495057")
            }
        };

        var acHeader = new Border {
            BackgroundColor = Color.FromArgb("#D1ECF1"),
            StrokeThickness = 0,
            Padding = new Thickness(12, 8),
            Margin = new Thickness(0, 16, 0, 4),
            Content = new Label {
                Text = "AC DINING ??", FontSize = 14,
                FontAttributes = FontAttributes.Bold,
                TextColor = Color.FromArgb("#0C5460")
            }
        };

        Content = new ScrollView {
            BackgroundColor = Color.FromArgb("#F8F9FA"),
            Content = new StackLayout {
                Padding = new Thickness(16), Spacing = 4,
                Children = { title, normalHeader, _normalGrid, acHeader, _acGrid }
            }
        };
    }

    private async Task RefreshTables() {
        try {
            var tables = await _api.GetTablesAsync();
            var normalTables = tables.Where(t => t.TableId.StartsWith("N-")).ToList();
            var acTables = tables.Where(t => t.TableId.StartsWith("A-")).ToList();
            await MainThread.InvokeOnMainThreadAsync(() => {
                RebuildGrid(_normalGrid, normalTables);
                RebuildGrid(_acGrid, acTables);
            });
        } catch (Exception ex) {
            CrashLogger.Log(ex, "TablesView.RefreshTables");
        }
    }


    private void RebuildGrid(Grid grid, List<TableInfo> tables) {
        grid.Children.Clear();
        grid.ColumnDefinitions.Clear();
        grid.RowDefinitions.Clear();
        for (int c = 0; c < 3; c++) grid.ColumnDefinitions.Add(new ColumnDefinition(GridLength.Star));
        int rows = (int)Math.Ceiling(tables.Count / 3.0);
        for (int r = 0; r < rows; r++) grid.RowDefinitions.Add(new RowDefinition(GridLength.Auto));

        for (int i = 0; i < tables.Count; i++) {
            var t = tables[i];
            var card = new Border {
                BackgroundColor = t.IsOpen ? Color.FromArgb("#E8F5E9") : Colors.White,
                StrokeThickness = t.IsOpen ? 2 : 1,
                Stroke = t.IsOpen ? Color.FromArgb("#28A745") : Color.FromArgb("#E0E0E0"),
                StrokeShape = new Microsoft.Maui.Controls.Shapes.RoundRectangle { CornerRadius = 12 },
                Padding = new Thickness(12, 14), Margin = new Thickness(2)
            };

            var statusLabel = new Label {
                Text = t.IsOpen ? "OCCUPIED" : "FREE",
                FontSize = 9, FontAttributes = FontAttributes.Bold,
                TextColor = t.IsOpen ? Color.FromArgb("#DC3545") : Color.FromArgb("#28A745"),
                HorizontalOptions = LayoutOptions.Center
            };

            var btn = new Button {
                Text = t.IsOpen ? "Close" : "Open",
                BackgroundColor = t.IsOpen ? Color.FromArgb("#DC3545") : Color.FromArgb("#1B4332"),
                TextColor = Colors.White, CornerRadius = 8,
                FontSize = 11, FontAttributes = FontAttributes.Bold, HeightRequest = 34,
                Margin = new Thickness(0, 6, 0, 0)
            };
            var tableId = t.TableId;
            var isOpen = t.IsOpen;
            btn.Clicked += async (s, e) => {
                btn.IsEnabled = false;
                try {
                    if (isOpen) await _api.CloseTableAsync(tableId);
                    else await _api.OpenTableAsync(tableId);
                    await RefreshTables();
                } catch (Exception ex) {
                    CrashLogger.Log(ex, "TablesView.TableAction");
                } finally {
                    await MainThread.InvokeOnMainThreadAsync(() => { btn.IsEnabled = true; });
                }
            };


            card.Content = new StackLayout {
                HorizontalOptions = LayoutOptions.Center, Spacing = 4,
                Children = {
                    new Label { Text = t.TableId, FontSize = 16, FontAttributes = FontAttributes.Bold,
                        TextColor = Colors.Black, HorizontalOptions = LayoutOptions.Center },
                    statusLabel,
                    btn
                }
            };

            grid.Add(card, i % 3, i / 3);
        }
    }
}
