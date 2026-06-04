using System.Net.Http;
using System.Text.Json;
using GustoPOS.Services;

namespace GustoPOS.Views;

public partial class SalesAndProfitPage : ContentView
{
    private readonly HttpClient _http = new() { Timeout = TimeSpan.FromSeconds(20) };
    private const string BaseUrl = "https://pos-1st-cut.onrender.com/api/v1";

    private static readonly JsonSerializerOptions Opts = new()
    {
        PropertyNameCaseInsensitive = true,
        PropertyNamingPolicy = JsonNamingPolicy.SnakeCaseLower,
    };

    public SalesAndProfitPage(ApiService _)
    {
        InitializeComponent();
    }

    public void OnTabShown() => _ = LoadDataAsync();

    private async void OnRefreshClicked(object s, EventArgs e) => await LoadDataAsync();

    private async Task LoadDataAsync()
    {
        try
        {
            LblTotalBills.Text = "…";
            LblRevenue.Text = "…";

            var json = await _http.GetStringAsync($"{BaseUrl}/orders/sales-summary/");
            var data = JsonSerializer.Deserialize<SalesSummaryDto>(json, Opts);
            if (data == null) return;

            LblTotalBills.Text = data.TotalBillsToday.ToString();
            LblRevenue.Text = $"₹{data.RevenueToday:N0}";

            TimelineList.ItemsSource = data.Timeline
                .Select(t => new TimelineRow
                {
                    TimeStr  = DateTime.TryParse(t.CreatedAt, out var dt) ? dt.ToString("HH:mm") : "—",
                    TableId  = t.TableId ?? "—",
                    DishName = t.DishName ?? "—",
                    Quantity = t.Quantity,
                    PriceStr = $"₹{t.Price:N0}",
                })
                .ToList();

            AggregateList.ItemsSource = data.Aggregates
                .Select(a => new AggregateRow
                {
                    DishName   = a.DishName ?? "—",
                    TotalQty   = a.TotalQty,
                    RevenueStr = $"₹{a.TotalRevenue:N0}",
                })
                .ToList();
        }
        catch (Exception ex)
        {
            System.Diagnostics.Debug.WriteLine($"SalesAndProfit load error: {ex.Message}");
            LblTotalBills.Text = "—";
            LblRevenue.Text = "—";
        }
    }
}

// ── Response DTOs ────────────────────────────────────────────────────────────

internal class SalesSummaryDto
{
    public int TotalBillsToday { get; set; }
    public double RevenueToday { get; set; }
    public List<TimelineItemDto> Timeline { get; set; } = new();
    public List<AggregateItemDto> Aggregates { get; set; } = new();
}

internal class TimelineItemDto
{
    public string? DishName { get; set; }
    public string? TableId { get; set; }
    public int Quantity { get; set; }
    public double Price { get; set; }
    public string? CreatedAt { get; set; }
}

internal class AggregateItemDto
{
    public string? DishName { get; set; }
    public int TotalQty { get; set; }
    public double TotalRevenue { get; set; }
}

// ── Display models ───────────────────────────────────────────────────────────

internal class TimelineRow
{
    public string TimeStr { get; set; } = "";
    public string TableId { get; set; } = "";
    public string DishName { get; set; } = "";
    public int Quantity { get; set; }
    public string PriceStr { get; set; } = "";
}

internal class AggregateRow
{
    public string DishName { get; set; } = "";
    public int TotalQty { get; set; }
    public string RevenueStr { get; set; } = "";
}
