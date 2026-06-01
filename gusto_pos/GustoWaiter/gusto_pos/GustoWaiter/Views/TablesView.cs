using GustoWaiter.Models;
using GustoWaiter.Services;

namespace GustoWaiter.Views;

public class TablesView : ContentView {
    private readonly ApiService _api;
    private readonly DashboardPage _dash;
    private readonly Grid _normalGrid = new() { ColumnSpacing = 10, RowSpacing = 10 };
    private readonly Grid _acGrid     = new() { ColumnSpacing = 10, RowSpacing = 10 };
    private System.Threading.Timer? _refreshTimer;
    private string _zoneFilter = "all"; // all | normal | ac
    private Button _allBtn    = new();
    private Button _normalBtn = new();
    private Button _acBtn     = new();

    public TablesView(ApiService api, DashboardPage dash) {
        _api = api; _dash = dash;
        BuildLayout();
        Loaded   += OnLoaded;
        Unloaded += OnUnloaded;
    }

    public Task TriggerRefreshAsync() => RefreshTables();

    // ── Layout ────────────────────────────────────────────────────────────────

    private void BuildLayout() {
        _allBtn    = MakeZoneBtn("All",    "all");
        _normalBtn = MakeZoneBtn("Normal", "normal");
        _acBtn     = MakeZoneBtn("AC ❄️",  "ac");
        UpdateZoneBtnStyles();

        var zoneBar = new HorizontalStackLayout {
            Spacing = 8, Padding = new Thickness(16, 10, 16, 6),
            Children = { _allBtn, _normalBtn, _acBtn }
        };

        var legend = new HorizontalStackLayout {
            Spacing = 14, Padding = new Thickness(16, 0, 16, 10),
            Children = {
                LegendDot("🟢", "Order Taken"),
                LegendDot("🔵", "Ready"),
                LegendDot("🟡", "Delayed"),
                LegendDot("🔴", "Seated"),
            }
        };

        var header = new VerticalStackLayout {
            BackgroundColor = Colors.White, Spacing = 0,
            Children = {
                new Label {
                    Text = "Tables", FontSize = 18, FontAttributes = FontAttributes.Bold,
                    TextColor = Color.FromArgb("#212529"),
                    Padding = new Thickness(16, 14, 16, 4)
                },
                zoneBar, legend
            }
        };
        header.Shadow = new Shadow { Brush = Brush.Black, Offset = new Point(0, 2), Radius = 6, Opacity = 0.06f };

        var normalHeader = new Border {
            BackgroundColor = Color.FromArgb("#F8F9FA"), StrokeThickness = 0,
            Padding = new Thickness(12, 8), Margin = new Thickness(0, 8, 0, 4),
            Content = new Label {
                Text = "NORMAL DINING", FontSize = 13, FontAttributes = FontAttributes.Bold,
                TextColor = Color.FromArgb("#495057")
            }
        };

        var acHeader = new Border {
            BackgroundColor = Color.FromArgb("#D1ECF1"), StrokeThickness = 0,
            Padding = new Thickness(12, 8), Margin = new Thickness(0, 16, 0, 4),
            Content = new Label {
                Text = "AC DINING ❄️", FontSize = 13, FontAttributes = FontAttributes.Bold,
                TextColor = Color.FromArgb("#0C5460")
            }
        };

        var scroll = new ScrollView {
            BackgroundColor = Color.FromArgb("#F8F9FA"),
            Content = new StackLayout {
                Padding = new Thickness(16), Spacing = 4,
                Children = { normalHeader, _normalGrid, acHeader, _acGrid }
            }
        };

        var root = new Grid { RowDefinitions = { new(GridLength.Auto), new(GridLength.Star) } };
        root.Add(header, 0, 0);
        root.Add(scroll, 0, 1);
        Content = root;
    }

    private Button MakeZoneBtn(string text, string zone) {
        var btn = new Button {
            Text = text, FontSize = 12, CornerRadius = 16,
            HeightRequest = 34, Padding = new Thickness(14, 0),
            BackgroundColor = Colors.White, TextColor = Color.FromArgb("#495057"),
            BorderColor = Color.FromArgb("#DEE2E6"), BorderWidth = 1
        };
        btn.Clicked += (_, _) => {
            _zoneFilter = zone;
            UpdateZoneBtnStyles();
            ApplyZoneOpacity();
        };
        return btn;
    }

    private static View LegendDot(string dot, string label) =>
        new HorizontalStackLayout {
            Spacing = 4, VerticalOptions = LayoutOptions.Center,
            Children = {
                new Label { Text = dot,   FontSize = 11, VerticalOptions = LayoutOptions.Center },
                new Label { Text = label, FontSize = 10, TextColor = Color.FromArgb("#6C757D"), VerticalOptions = LayoutOptions.Center }
            }
        };

    private void UpdateZoneBtnStyles() {
        ApplyZoneStyle(_allBtn,    _zoneFilter == "all");
        ApplyZoneStyle(_normalBtn, _zoneFilter == "normal");
        ApplyZoneStyle(_acBtn,     _zoneFilter == "ac");
    }

    private static void ApplyZoneStyle(Button btn, bool active) {
        btn.BackgroundColor = active ? Color.FromArgb("#1B4332") : Colors.White;
        btn.TextColor       = active ? Colors.White : Color.FromArgb("#495057");
        btn.BorderColor     = active ? Color.FromArgb("#1B4332") : Color.FromArgb("#DEE2E6");
    }

    // ── Opacity dimming ───────────────────────────────────────────────────────

    private void ApplyZoneOpacity() {
        DimGrid(_normalGrid, _zoneFilter == "ac" ? 0.4 : 1.0);
        DimGrid(_acGrid,     _zoneFilter == "normal" ? 0.4 : 1.0);
    }

    private static void DimGrid(Grid grid, double opacity) {
        foreach (var child in grid.Children)
            if (child is VisualElement ve) ve.Opacity = opacity;
    }

    // ── Data refresh ──────────────────────────────────────────────────────────

    private async void OnLoaded(object? sender, EventArgs e) {
        try { await RefreshTables(); } catch (Exception ex) { CrashLogger.Log(ex, "TablesView.OnLoaded"); }
        _refreshTimer?.Dispose();
        _refreshTimer = new System.Threading.Timer(async _ => {
            try { await RefreshTables(); } catch (Exception ex) { CrashLogger.Log(ex, "TablesView.Timer"); }
        }, null, 5000, 5000);
    }

    private void OnUnloaded(object? sender, EventArgs e) {
        _refreshTimer?.Dispose();
        _refreshTimer = null;
    }

    private async Task RefreshTables() {
        try {
            var tables = await _api.GetTablesAsync();
            var normal = tables.Where(t => t.TableId.StartsWith("N-")).ToList();
            var ac     = tables.Where(t => t.TableId.StartsWith("A-")).ToList();
            await MainThread.InvokeOnMainThreadAsync(() => {
                RebuildGrid(_normalGrid, normal);
                RebuildGrid(_acGrid, ac);
                ApplyZoneOpacity();
            });
        } catch (Exception ex) {
            CrashLogger.Log(ex, "TablesView.RefreshTables");
        }
    }

    // ── Grid builder ──────────────────────────────────────────────────────────

    private void RebuildGrid(Grid grid, List<TableInfo> tables) {
        grid.Children.Clear();
        grid.ColumnDefinitions.Clear();
        grid.RowDefinitions.Clear();

        const int cols = 3;
        for (int c = 0; c < cols; c++)
            grid.ColumnDefinitions.Add(new ColumnDefinition(GridLength.Star));
        int rows = (int)Math.Ceiling(tables.Count / (double)cols);
        for (int r = 0; r < rows; r++)
            grid.RowDefinitions.Add(new RowDefinition(GridLength.Auto));

        for (int i = 0; i < tables.Count; i++) {
            var t = tables[i];
            var (stroke, bg) = TableColors(t);
            var (statusText, statusColor) = StatusLabel(t);

            var card = new Border {
                BackgroundColor = bg,
                StrokeThickness = t.IsOpen ? 2 : 1,
                Stroke = stroke,
                StrokeShape = new Microsoft.Maui.Controls.Shapes.RoundRectangle { CornerRadius = 12 },
                Padding = new Thickness(10, 12), Margin = new Thickness(2),
                BindingContext = t  // stored for opacity updates
            };

            var actionBtn = new Button {
                Text = t.IsOpen ? "Close" : "Open",
                BackgroundColor = t.IsOpen ? Color.FromArgb("#DC3545") : Color.FromArgb("#1B4332"),
                TextColor = Colors.White, CornerRadius = 8,
                FontSize = 11, FontAttributes = FontAttributes.Bold, HeightRequest = 32,
                Margin = new Thickness(0, 6, 0, 0)
            };
            var tableId = t.TableId;
            var isOpen  = t.IsOpen;
            actionBtn.Clicked += async (_, _) => {
                actionBtn.IsEnabled = false;
                try {
                    if (isOpen) await _api.CloseTableAsync(tableId);
                    else        await _api.OpenTableAsync(tableId);
                    await RefreshTables();
                } catch (Exception ex) {
                    CrashLogger.Log(ex, "TablesView.ActionBtn");
                } finally {
                    await MainThread.InvokeOnMainThreadAsync(() => actionBtn.IsEnabled = true);
                }
            };

            card.Content = new StackLayout {
                HorizontalOptions = LayoutOptions.Center, Spacing = 2,
                Children = {
                    new Label { Text = t.TableId, FontSize = 15, FontAttributes = FontAttributes.Bold,
                        TextColor = Colors.Black, HorizontalOptions = LayoutOptions.Center },
                    new Label { Text = statusText, FontSize = 9, FontAttributes = FontAttributes.Bold,
                        TextColor = statusColor, HorizontalOptions = LayoutOptions.Center },
                    actionBtn
                }
            };

            grid.Add(card, i % cols, i / cols);
        }
    }

    // ── Color helpers ─────────────────────────────────────────────────────────

    private static (Color Stroke, Color Bg) TableColors(TableInfo t) => t.TableVisualStatus switch {
        "ordered" => (Color.FromArgb("#28A745"), Color.FromArgb("#E8F5E9")),
        "ready"   => (Color.FromArgb("#0D6EFD"), Color.FromArgb("#EFF6FF")),
        "delayed" => (Color.FromArgb("#FFC107"), Color.FromArgb("#FFFBEB")),
        "seated"  => (Color.FromArgb("#DC3545"), Color.FromArgb("#FFF5F5")),
        _         => (Color.FromArgb("#E0E0E0"), Colors.White)
    };

    private static (string Text, Color Color) StatusLabel(TableInfo t) => t.TableVisualStatus switch {
        "ordered" => ("ORDERED",  Color.FromArgb("#1B4332")),
        "ready"   => ("READY",    Color.FromArgb("#0D6EFD")),
        "delayed" => ("DELAYED",  Color.FromArgb("#856404")),
        "seated"  => ("SEATED",   Color.FromArgb("#DC3545")),
        _         => ("FREE",     Color.FromArgb("#28A745"))
    };
}
