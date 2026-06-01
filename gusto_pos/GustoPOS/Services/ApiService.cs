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
    private const string Base = "http://192.168.1.7:8000/api/v1";
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
            var json = await _http.GetStringAsync($"{Base}/menus/zone/{OutletId}/{zone}");
            return JsonSerializer.Deserialize<Menu>(json, Opts);
        } catch (Exception ex) {
            System.Diagnostics.Debug.WriteLine($"GetMenuByZone: {ex.Message}");
            return null;
        }
    }
    public async Task<Order?> CreateOrderAsync(List<CartItem> items, string? tableId, string orderType = "dine_in", string? zone = null, string? staffId = null) {
        try {
            var body = JsonSerializer.Serialize(new {
                outlet_id = OutletId,
                table_id = tableId,
                staff_id = staffId,
                total_amount = items.Sum(i => i.ItemTotal),
                order_type = orderType,
                zone = zone,
                source = "pos",
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
    public async Task<Order?> CreateOrderWithPaymentAsync(List<CartItem> items, string? tableId, string orderType, string paymentMethod, string? zone = null, string? staffId = null) {
        try {
            var body = JsonSerializer.Serialize(new {
                outlet_id = OutletId,
                table_id = tableId,
                staff_id = staffId,
                total_amount = items.Sum(i => i.ItemTotal),
                order_type = orderType,
                payment_method = paymentMethod,
                zone = zone,
                source = "pos",
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

    public string GetPosWsUrl() =>
        $"ws://192.168.1.7:8000/ws/pos/{OutletId}";

    public async Task<List<StaffMember>> GetStaffAsync() {
        try {
            var json = await _http.GetStringAsync($"{Base}/staff/");
            return JsonSerializer.Deserialize<List<StaffMember>>(json, Opts) ?? new();
        } catch (Exception ex) {
            System.Diagnostics.Debug.WriteLine($"GetStaff: {ex.Message}");
            return new();
        }
    }

    public async Task<StaffMember?> CreateStaffAsync(string name, string role, string pin) {
        try {
            var body = JsonSerializer.Serialize(new { name, role, pin }, Opts);
            var res = await _http.PostAsync($"{Base}/staff/",
                new StringContent(body, Encoding.UTF8, "application/json"));
            if (!res.IsSuccessStatusCode) return null;
            return JsonSerializer.Deserialize<StaffMember>(await res.Content.ReadAsStringAsync(), Opts);
        } catch (Exception ex) {
            System.Diagnostics.Debug.WriteLine($"CreateStaff: {ex.Message}");
            return null;
        }
    }

    public async Task<bool> ResetStaffPinAsync(string staffId, string pin) {
        try {
            var body = JsonSerializer.Serialize(new { pin }, Opts);
            var res = await _http.PutAsync($"{Base}/staff/{staffId}/pin",
                new StringContent(body, Encoding.UTF8, "application/json"));
            return res.IsSuccessStatusCode;
        } catch (Exception ex) {
            System.Diagnostics.Debug.WriteLine($"ResetStaffPin: {ex.Message}");
            return false;
        }
    }

    public async Task<bool> DeleteStaffAsync(string staffId) {
        try {
            var res = await _http.DeleteAsync($"{Base}/staff/{staffId}");
            return res.IsSuccessStatusCode;
        } catch (Exception ex) {
            System.Diagnostics.Debug.WriteLine($"DeleteStaff: {ex.Message}");
            return false;
        }
    }

    public async Task<StaffMember?> UpdateStaffAsync(string staffId, string? assignedTable, string? shiftStart, string? shiftEnd) {
        try {
            var body = JsonSerializer.Serialize(new {
                assigned_table = assignedTable,
                shift_start = shiftStart,
                shift_end = shiftEnd
            }, Opts);
            var res = await _http.PutAsync($"{Base}/staff/{staffId}",
                new StringContent(body, Encoding.UTF8, "application/json"));
            if (!res.IsSuccessStatusCode) return null;
            return JsonSerializer.Deserialize<StaffMember>(await res.Content.ReadAsStringAsync(), Opts);
        } catch (Exception ex) {
            System.Diagnostics.Debug.WriteLine($"UpdateStaff: {ex.Message}");
            return null;
        }
    }

    public async Task<List<CategoryItem>> GetCategoriesForMenuAsync() {
        try {
            var json = await _http.GetStringAsync($"{Base}/menus/categories/menu/{MenuId}");
            var cats = JsonSerializer.Deserialize<List<CategoryItem>>(json, Opts) ?? new();
            return cats;
        } catch (Exception ex) {
            System.Diagnostics.Debug.WriteLine($"GetCategories: {ex.Message}");
            return new();
        }
    }

    public async Task<CategoryItem?> CreateCategoryAsync(string name) {
        try {
            var body = JsonSerializer.Serialize(new { menu_id = MenuId, name }, Opts);
            var res = await _http.PostAsync($"{Base}/menus/categories/",
                new StringContent(body, Encoding.UTF8, "application/json"));
            if (!res.IsSuccessStatusCode) return null;
            return JsonSerializer.Deserialize<CategoryItem>(await res.Content.ReadAsStringAsync(), Opts);
        } catch (Exception ex) {
            System.Diagnostics.Debug.WriteLine($"CreateCategory: {ex.Message}");
            return null;
        }
    }

    public async Task<bool> UpdateCategoryAsync(string categoryId, string name) {
        try {
            var body = JsonSerializer.Serialize(new { name }, Opts);
            var res = await _http.PutAsync($"{Base}/categories/{categoryId}",
                new StringContent(body, Encoding.UTF8, "application/json"));
            return res.IsSuccessStatusCode;
        } catch (Exception ex) {
            System.Diagnostics.Debug.WriteLine($"UpdateCategory: {ex.Message}");
            return false;
        }
    }

    public async Task<bool> DeleteCategoryAsync(string categoryId) {
        try {
            var res = await _http.DeleteAsync($"{Base}/categories/{categoryId}");
            return res.IsSuccessStatusCode;
        } catch (Exception ex) {
            System.Diagnostics.Debug.WriteLine($"DeleteCategory: {ex.Message}");
            return false;
        }
    }

    public async Task<bool> UpdateMenuItemPriceAsync(string itemId, decimal newPrice) {
        try {
            var body = JsonSerializer.Serialize(new { base_price = newPrice }, Opts);
            var res = await _http.PutAsync($"{Base}/menus/items/{itemId}",
                new StringContent(body, Encoding.UTF8, "application/json"));
            return res.IsSuccessStatusCode;
        } catch (Exception ex) {
            System.Diagnostics.Debug.WriteLine($"UpdateMenuItemPrice: {ex.Message}");
            return false;
        }
    }

    public async Task<string> GetFreeTablesAsync() {
        try {
            var json = await _http.GetStringAsync($"{Base}/analytics/free-tables?outlet_id={OutletId}");
            var resp = JsonSerializer.Deserialize<FreeTablesResponse>(json, Opts);
            if (resp == null) return "No data returned.";
            if (resp.Count == 0) return "All tables are currently occupied.";
            var list = string.Join(", ", resp.TableNumbers.Select(n => $"T-{n}"));
            return $"{resp.Count} free {(resp.Count == 1 ? "table" : "tables")}: {list}";
        } catch (Exception ex) {
            System.Diagnostics.Debug.WriteLine($"GetFreeTables: {ex.Message}");
            return "Error: could not reach the server.";
        }
    }
    public async Task<string> GetTotalTablesAsync() {
        try {
            var json = await _http.GetStringAsync($"{Base}/analytics/total-tables?outlet_id={OutletId}");
            var resp = JsonSerializer.Deserialize<TotalTablesResponse>(json, Opts);
            return resp == null ? "No data returned." : $"{resp.Count} total tables";
        } catch (Exception ex) {
            System.Diagnostics.Debug.WriteLine($"GetTotalTables: {ex.Message}");
            return "Error: could not reach the server.";
        }
    }
    public async Task<string> GetTopDishAsync() {
        try {
            var json = await _http.GetStringAsync($"{Base}/analytics/top-dish?outlet_id={OutletId}");
            var resp = JsonSerializer.Deserialize<TopDishResponse>(json, Opts);
            if (resp?.Dish == null) return "No orders recorded today yet.";
            return $"{resp.Dish}  —  {resp.Quantity} sold today";
        } catch (Exception ex) {
            System.Diagnostics.Debug.WriteLine($"GetTopDish: {ex.Message}");
            return "Error: could not reach the server.";
        }
    }
    public async Task<string> GetTodaysRevenueAsync() {
        try {
            var json = await _http.GetStringAsync($"{Base}/analytics/todays-revenue?outlet_id={OutletId}");
            var resp = JsonSerializer.Deserialize<RevenueResponse>(json, Opts);
            return resp == null ? "No data returned." : $"₹{resp.Revenue:N2}";
        } catch (Exception ex) {
            System.Diagnostics.Debug.WriteLine($"GetTodaysRevenue: {ex.Message}");
            return "Error: could not reach the server.";
        }
    }

    public async Task<ChatResponse?> ChatQueryAsync(string question) {
        try {
            var body = JsonSerializer.Serialize(new { question }, Opts);
            var res = await _http.PostAsync($"{Base}/chat/query",
                new StringContent(body, Encoding.UTF8, "application/json"));
            return JsonSerializer.Deserialize<ChatResponse>(await res.Content.ReadAsStringAsync(), Opts);
        } catch (Exception ex) {
            System.Diagnostics.Debug.WriteLine($"ChatQuery: {ex.Message}");
            return null;
        }
    }

    public async Task<ChatResponse?> AskGustoAsync(string query) {
        try {
            var body = JsonSerializer.Serialize(new { query, outlet_id = OutletId }, Opts);
            var res = await _http.PostAsync($"{Base}/chat/ask",
                new StringContent(body, Encoding.UTF8, "application/json"));
            if (!res.IsSuccessStatusCode)
                return new ChatResponse { Answer = "Server returned an error. Please try again." };
            return JsonSerializer.Deserialize<ChatResponse>(await res.Content.ReadAsStringAsync(), Opts);
        } catch (Exception ex) {
            System.Diagnostics.Debug.WriteLine($"AskGusto: {ex.Message}");
            return new ChatResponse { Answer = "Error: could not reach the server." };
        }
    }

    public async Task<(PinLoginResponse? Response, string? Error)> PinLoginAsync(string pin) {
        try {
            var body = JsonSerializer.Serialize(new { pin }, Opts);
            var res = await _http.PostAsync($"{Base}/auth/pin-login",
                new StringContent(body, Encoding.UTF8, "application/json"));
            if (!res.IsSuccessStatusCode) {
                var errorBody = await res.Content.ReadAsStringAsync();
                return (null, $"HTTP {(int)res.StatusCode}: {errorBody}");
            }
            var response = JsonSerializer.Deserialize<PinLoginResponse>(await res.Content.ReadAsStringAsync(), Opts);
            return (response, null);
        } catch (Exception ex) {
            System.Diagnostics.Debug.WriteLine($"PinLogin: {ex.Message}");
            return (null, $"Network error: {ex.Message}");
        }
    }
}

