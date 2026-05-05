using System;
using System.Collections.Generic;
using System.Linq;
using System.Net.Http;
using System.Text;
using System.Text.Json;
using System.Threading.Tasks;
using GustoPOS.Models;
namespace GustoPOS.Services;
public class ApiService {
    private readonly HttpClient _http = new() { Timeout = TimeSpan.FromSeconds(15) };
    private const string Base = "http://127.0.0.1:8000/api/v1";
    private const string MenuId = "dc88b6a6-129c-479f-8609-07b8525f4310";
    private const string OutletId = "0b8a8349-6144-41a8-b028-b9089bd8eaea";
    private static readonly JsonSerializerOptions Opts = new() {
        PropertyNameCaseInsensitive = true,
        PropertyNamingPolicy = JsonNamingPolicy.SnakeCaseLower
    };
    public async Task<Menu?> GetMenuAsync() {
        try {
            var json = await _http.GetStringAsync($"{Base}/menus/{MenuId}");
            return JsonSerializer.Deserialize<Menu>(json, Opts);
        } catch (Exception ex) {
            System.Diagnostics.Debug.WriteLine($"GetMenu: {ex.Message}");
            return null;
        }
    }
    public async Task<Menu?> GetMenuByZoneAsync(string zone) {
        try {
            var json = await _http.GetStringAsync($"{Base}/menus/by-zone/{OutletId}/{zone}");
            return JsonSerializer.Deserialize<Menu>(json, Opts);
        } catch (Exception ex) {
            System.Diagnostics.Debug.WriteLine($"GetMenuByZone: {ex.Message}");
            return null;
        }
    }
    public async Task<Order?> CreateOrderAsync(List<CartItem> items, string? tableId, string orderType = "dine_in", string? zone = null) {
        try {
            var body = JsonSerializer.Serialize(new {
                outlet_id = OutletId,
                table_id = tableId,
                total_amount = items.Sum(i => i.ItemTotal),
                order_type = orderType,
                zone = zone,
                items = items.Select(i => new {
                    name = i.Name,
                    quantity = i.Quantity,
                    unit_price = i.BasePrice
                }).ToArray()
            }, Opts);
            var res = await _http.PostAsync($"{Base}/orders/",
                new StringContent(body, Encoding.UTF8, "application/json"));
            return JsonSerializer.Deserialize<Order>(await res.Content.ReadAsStringAsync(), Opts);
        } catch (Exception ex) {
            System.Diagnostics.Debug.WriteLine($"CreateOrder: {ex.Message}");
            return null;
        }
    }
    public async Task<bool> ToggleItemAvailabilityAsync(string itemId, bool isActive) {
        try {
            var body = JsonSerializer.Serialize(new { is_active = isActive }, Opts);
            var res = await _http.PutAsync($"{Base}/menus/items/{itemId}",
                new StringContent(body, Encoding.UTF8, "application/json"));
            return res.IsSuccessStatusCode;
        } catch (Exception ex) {
            System.Diagnostics.Debug.WriteLine($"ToggleItem: {ex.Message}");
            return false;
        }
    }
    public async Task<Models.MenuItem?> AddMenuItemAsync(string categoryId, string name, decimal price, bool isVeg, string shortCode) {
        try {
            var body = JsonSerializer.Serialize(new {
                category_id = categoryId,
                name,
                short_code = shortCode,
                base_price = price,
                is_veg = isVeg,
                is_active = true
            }, Opts);
            var res = await _http.PostAsync($"{Base}/menus/items/",
                new StringContent(body, Encoding.UTF8, "application/json"));
            if (!res.IsSuccessStatusCode) return null;
            return JsonSerializer.Deserialize<Models.MenuItem>(await res.Content.ReadAsStringAsync(), Opts);
        } catch (Exception ex) {
            System.Diagnostics.Debug.WriteLine($"AddMenuItem: {ex.Message}");
            return null;
        }
    }
    public async Task<bool> CreatePaymentAsync(string orderId, decimal amount, string method) {
        try {
            var body = JsonSerializer.Serialize(new {
                order_id = orderId, amount,
                payment_method = method, payment_status = "Completed"
            }, Opts);
            var res = await _http.PostAsync($"{Base}/payments/",
                new StringContent(body, Encoding.UTF8, "application/json"));
            return res.IsSuccessStatusCode;
        } catch { return false; }
    }
    public async Task<List<Order>> GetActiveOrdersAsync() {
        try {
            var json = await _http.GetStringAsync($"{Base}/orders/");
            return JsonSerializer.Deserialize<List<Order>>(json, Opts) ?? new();
        } catch { return new(); }
    }
    public async Task<Order?> UpdateOrderStatusAsync(string orderId, string status) {
        try {
            var body = JsonSerializer.Serialize(new { order_status = status }, Opts);
            var res = await _http.PutAsync($"{Base}/orders/{orderId}",
                new StringContent(body, Encoding.UTF8, "application/json"));
            return JsonSerializer.Deserialize<Order>(await res.Content.ReadAsStringAsync(), Opts);
        } catch (Exception ex) {
            System.Diagnostics.Debug.WriteLine($"UpdateOrder: {ex.Message}");
            return null;
        }
    }
    public async Task<List<Order>> GetTableOrdersAsync(string tableId) {
        try {
            var json = await _http.GetStringAsync($"{Base}/orders/table/{tableId}");
            return JsonSerializer.Deserialize<List<Order>>(json, Opts) ?? new();
        } catch (Exception ex) {
            System.Diagnostics.Debug.WriteLine($"GetTableOrders: {ex.Message}");
            return new();
        }
    }
    public async Task<BillResponse?> GenerateBillAsync(string tableId) {
        try {
            var res = await _http.PostAsync($"{Base}/orders/bill/{tableId}", null);
            if (!res.IsSuccessStatusCode) return null;
            return JsonSerializer.Deserialize<BillResponse>(await res.Content.ReadAsStringAsync(), Opts);
        } catch (Exception ex) {
            System.Diagnostics.Debug.WriteLine($"GenerateBill: {ex.Message}");
            return null;
        }
    }
    public async Task<SettleResponse?> SettleTableAsync(string tableId) {
        try {
            var res = await _http.PostAsync($"{Base}/orders/settle/{tableId}", null);
            if (!res.IsSuccessStatusCode) return null;
            return JsonSerializer.Deserialize<SettleResponse>(await res.Content.ReadAsStringAsync(), Opts);
        } catch (Exception ex) {
            System.Diagnostics.Debug.WriteLine($"SettleTable: {ex.Message}");
            return null;
        }
    }
    public async Task<bool> CloseTableAsync(string tableId) {
        try {
            var res = await _http.PostAsync(
                $"{Base}/tables/close/{tableId}?outlet_id={OutletId}",
                new StringContent("", Encoding.UTF8, "application/json"));
            return res.IsSuccessStatusCode;
        } catch (Exception ex) {
            System.Diagnostics.Debug.WriteLine($"CloseTable: {ex.Message}");
            return false;
        }
    }
    public async Task<BillResponse?> GenerateBillAutoAsync(string tableId, string paymentMethod, string? zone = null) {
        try {
            var body = JsonSerializer.Serialize(new { payment_method = paymentMethod, zone = zone }, Opts);
            var res = await _http.PostAsync($"{Base}/orders/bill/{tableId}",
                new StringContent(body, Encoding.UTF8, "application/json"));
            if (!res.IsSuccessStatusCode) return null;
            return JsonSerializer.Deserialize<BillResponse>(await res.Content.ReadAsStringAsync(), Opts);
        } catch (Exception ex) {
            System.Diagnostics.Debug.WriteLine($"GenerateBillAuto: {ex.Message}");
            return null;
        }
    }
    public async Task<Order?> CreateOrderWithPaymentAsync(List<CartItem> items, string? tableId, string orderType, string paymentMethod, string? zone = null) {
        try {
            var body = JsonSerializer.Serialize(new {
                outlet_id = OutletId,
                table_id = tableId,
                total_amount = items.Sum(i => i.ItemTotal),
                order_type = orderType,
                payment_method = paymentMethod,
                zone = zone,
                items = items.Select(i => new {
                    name = i.Name,
                    quantity = i.Quantity,
                    unit_price = i.BasePrice
                }).ToArray()
            }, Opts);
            var res = await _http.PostAsync($"{Base}/orders/",
                new StringContent(body, Encoding.UTF8, "application/json"));
            return JsonSerializer.Deserialize<Order>(await res.Content.ReadAsStringAsync(), Opts);
        } catch (Exception ex) {
            System.Diagnostics.Debug.WriteLine($"CreateOrderWithPayment: {ex.Message}");
            return null;
        }
    }
    public async Task<OutletConfig> GetOutletConfigAsync() {
        try {
            var json = await _http.GetStringAsync($"{Base}/config/{OutletId}");
            return JsonSerializer.Deserialize<OutletConfig>(json, Opts) ?? new OutletConfig();
        } catch (Exception ex) {
            System.Diagnostics.Debug.WriteLine($"GetOutletConfig: {ex.Message}");
            return new OutletConfig();
        }
    }
    public async Task<bool> UpdateOutletConfigAsync(string key, string value) {
        try {
            var body = JsonSerializer.Serialize(new { config_key = key, config_value = value }, Opts);
            var res = await _http.PostAsync($"{Base}/config/{OutletId}",
                new StringContent(body, Encoding.UTF8, "application/json"));
            return res.IsSuccessStatusCode;
        } catch (Exception ex) {
            System.Diagnostics.Debug.WriteLine($"UpdateOutletConfig: {ex.Message}");
            return false;
        }
    }

    public async Task<PinLoginResponse?> PinLoginAsync(string pin) {
        try {
            var body = JsonSerializer.Serialize(new { pin }, Opts);
            var res = await _http.PostAsync($"{Base}/auth/pin-login",
                new StringContent(body, Encoding.UTF8, "application/json"));
            if (!res.IsSuccessStatusCode) return null;
            return JsonSerializer.Deserialize<PinLoginResponse>(await res.Content.ReadAsStringAsync(), Opts);
        } catch (Exception ex) {
            System.Diagnostics.Debug.WriteLine($"PinLogin: {ex.Message}");
            return null;
        }
    }
}

