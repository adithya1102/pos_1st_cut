using System.Diagnostics;
using System.Net.Http;
using System.Text;
using System.Text.Json;
using GustoWaiter.Models;

namespace GustoWaiter.Services;

public class ApiService {
    private readonly HttpClient _http = new() { Timeout = TimeSpan.FromSeconds(15) };
    private const string Base = "http://192.168.1.7:8000/api/v1";
    public const string OutletId = "0b8a8349-6144-41a8-b028-b9089bd8eaea";
    private const string MenuId = "dc88b6a6-129c-479f-8609-07b8525f4310";

    private static readonly JsonSerializerOptions J = new() {
        PropertyNameCaseInsensitive = true,
        PropertyNamingPolicy = JsonNamingPolicy.SnakeCaseLower
    };

    public async Task<List<Notification>> GetNotificationsAsync() {
        try {
            Debug.WriteLine($">>> [DIAGNOSTIC]: GetNotificationsAsync START");
            var json = await _http.GetStringAsync($"{Base}/sessions/waiter/notifications/{OutletId}");
            Debug.WriteLine($">>> [DIAGNOSTIC]: GetNotificationsAsync got {json.Length} chars");
            return JsonSerializer.Deserialize<List<Notification>>(json, J) ?? new();
        } catch (Exception ex) {
            Debug.WriteLine($"GetNotificationsAsync error: {ex.Message}");
            return new();
        }
    }

    public async Task<bool> RespondToNotificationAsync(string id, bool confirm) {
        try {
            var body = JsonSerializer.Serialize(new { notification_id = id, confirmed = confirm });
            Debug.WriteLine($">>> [DIAGNOSTIC]: RespondToNotification id={id} confirm={confirm} body={body}");
            var r = await _http.PostAsync(
                $"{Base}/sessions/waiter/action",
                new StringContent(body, Encoding.UTF8, "application/json"));
            Debug.WriteLine($">>> [DIAGNOSTIC]: RespondToNotification status={r.StatusCode}");
            return r.IsSuccessStatusCode;
        } catch (Exception ex) {
            Debug.WriteLine($"RespondToNotificationAsync error: {ex.Message}");
            return false;
        }
    }

    public async Task<ZoneMenuResponse?> GetMenuByZoneAsync(string zone) {
        try {
            Debug.WriteLine($">>> [DIAGNOSTIC]: GetMenuByZoneAsync START zone={zone}");
            var json = await _http.GetStringAsync($"{Base}/menus/zone/{OutletId}/{zone}");
            Debug.WriteLine($">>> [DIAGNOSTIC]: GetMenuByZoneAsync got {json.Length} chars");
            try {
                var result = JsonSerializer.Deserialize<ZoneMenuResponse>(json, J);
                Debug.WriteLine($">>> [DIAGNOSTIC]: GetMenuByZoneAsync deserialized {result?.Categories?.Count ?? 0} categories");
                return result;
            } catch (JsonException jex) {
                Debug.WriteLine($">>> [DIAGNOSTIC]: GetMenuByZoneAsync DESERIALIZATION FAILED: {jex.Message}");
                Debug.WriteLine($">>> [DIAGNOSTIC]: Raw JSON (first 500): {json[..Math.Min(json.Length, 500)]}");
                return null;
            }
        } catch (Exception ex) {
            Debug.WriteLine($"GetMenuByZoneAsync error: {ex.Message}");
            return null;
        }
    }

    public async Task<MenuResponse?> GetMenuAsync() {
        var zone = await GetMenuByZoneAsync("normal");
        if (zone != null) {
            return new MenuResponse { Categories = zone.Categories };
        }

        try {
            var json = await _http.GetStringAsync($"{Base}/menus/{MenuId}");
            return JsonSerializer.Deserialize<MenuResponse>(json, J);
        } catch (Exception ex) {
            Debug.WriteLine($"GetMenuAsync error: {ex.Message}");
            return null;
        }
    }

    public async Task<bool> ConfirmOrderAsync(string orderId) {
        try {
            Debug.WriteLine($">>> [DIAGNOSTIC]: ConfirmOrderAsync orderId={orderId}");
            var r = await _http.PostAsync(
                $"{Base}/orders/{orderId}/confirm",
                new StringContent("{}", Encoding.UTF8, "application/json"));
            var resp = await r.Content.ReadAsStringAsync();
            Debug.WriteLine($">>> [DIAGNOSTIC]: ConfirmOrderAsync status={r.StatusCode} resp={resp}");
            return r.IsSuccessStatusCode;
        } catch (Exception ex) {
            Debug.WriteLine($"ConfirmOrderAsync error: {ex.Message}");
            return false;
        }
    }

    public async Task<JsonElement?> GetOrderDetailsAsync(string orderId) {
        try {
            var json = await _http.GetStringAsync($"{Base}/orders/{orderId}");
            using var doc = JsonDocument.Parse(json);
            return doc.RootElement.Clone();
        } catch (Exception ex) {
            Debug.WriteLine($"GetOrderDetailsAsync error: {ex.Message}");
            return null;
        }
    }

    public async Task<bool> UpdateOrderItemsAsync(string orderId, List<CartItem> items) {
        try {
            var payload = new {
                total_amount = items.Sum(i => i.ItemTotal),
                order_status = "pending",
                items = items.Select(i => new {
                    name = i.Name,
                    quantity = i.Quantity,
                    unit_price = i.BasePrice,
                    customizations = i.Customizations ?? new List<string>(),
                    custom_note = i.Note ?? ""
                }).ToList()
            };
            var body = JsonSerializer.Serialize(payload);
            var r = await _http.PutAsync(
                $"{Base}/orders/{orderId}",
                new StringContent(body, Encoding.UTF8, "application/json"));
            return r.IsSuccessStatusCode;
        } catch (Exception ex) {
            Debug.WriteLine($"UpdateOrderItemsAsync error: {ex.Message}");
            return false;
        }
    }

    public async Task<(bool ok, string msg)> PlaceOrderAsync(
        List<CartItem> items, string tableId, string orderType) {
        try {
            var body = JsonSerializer.Serialize(new {
                outlet_id = OutletId,
                table_id = tableId,
                total_amount = items.Sum(i => i.ItemTotal),
                order_type = orderType,
                source = "waiter",
                items = items.Select(i => new {
                    name = i.Name,
                    quantity = i.Quantity,
                    unit_price = i.BasePrice
                }).ToArray()
            });
            Debug.WriteLine($">>> [DIAGNOSTIC]: PlaceOrderAsync table={tableId} body={body}");
            var r = await _http.PostAsync(
                $"{Base}/orders/",
                new StringContent(body, Encoding.UTF8, "application/json"));
            var resp = await r.Content.ReadAsStringAsync();
            Debug.WriteLine($">>> [DIAGNOSTIC]: PlaceOrderAsync status={r.StatusCode} resp={resp}");
            return r.IsSuccessStatusCode ? (true, "Order placed!") : (false, resp);
        } catch (Exception ex) {
            Debug.WriteLine($"PlaceOrderAsync error: {ex.Message}");
            return (false, ex.Message);
        }
    }

    public async Task<OutletConfig> GetOutletConfigAsync() {
        try {
            var json = await _http.GetStringAsync($"{Base}/config/{OutletId}");
            return JsonSerializer.Deserialize<OutletConfig>(json, J) ?? new OutletConfig();
        } catch (Exception ex) {
            Debug.WriteLine($"GetOutletConfigAsync error: {ex.Message}");
            return new OutletConfig();
        }
    }

    public async Task<List<TableInfo>> GetTablesAsync() {
        try {
            var config = await GetOutletConfigAsync();

            // Fetch sessions and all orders in parallel — a table is occupied if it has
            // an active session OR unpaid orders (covers waiter-placed orders with no session)
            var sessionsTask = _http.GetStringAsync($"{Base}/tables/all");
            var ordersTask = _http.GetStringAsync($"{Base}/orders/");
            await Task.WhenAll(sessionsTask, ordersTask);

            var activeSessions = new Dictionary<string, string>();
            using (var doc = JsonDocument.Parse(sessionsTask.Result)) {
                foreach (var el in doc.RootElement.EnumerateArray()) {
                    if (el.TryGetProperty("is_active", out var active) && active.GetBoolean()) {
                        var tid = el.GetProperty("table_id").GetString() ?? "";
                        var tok = el.GetProperty("token").GetString() ?? "";
                        activeSessions[tid] = tok;
                    }
                }
            }

            var occupiedByOrders = new HashSet<string>();
            using (var doc = JsonDocument.Parse(ordersTask.Result)) {
                foreach (var el in doc.RootElement.EnumerateArray()) {
                    var status = el.TryGetProperty("order_status", out var sp) ? sp.GetString() : null;
                    var tableId = el.TryGetProperty("table_id", out var tp) ? tp.GetString() : null;
                    if (!string.IsNullOrEmpty(tableId) && status != "paid" && status != "cancelled")
                        occupiedByOrders.Add(tableId);
                }
            }

            var tables = new List<TableInfo>();
            for (int i = 1; i <= config.NormalTableCount; i++) {
                var tid = $"N-{i}";
                tables.Add(new TableInfo {
                    TableId = tid,
                    Slug = activeSessions.TryGetValue(tid, out var tok) ? tok : "",
                    IsOpen = activeSessions.ContainsKey(tid) || occupiedByOrders.Contains(tid),
                    Capacity = "4"
                });
            }
            for (int i = 1; i <= config.AcTableCount; i++) {
                var tid = $"A-{i}";
                tables.Add(new TableInfo {
                    TableId = tid,
                    Slug = activeSessions.TryGetValue(tid, out var tok) ? tok : "",
                    IsOpen = activeSessions.ContainsKey(tid) || occupiedByOrders.Contains(tid),
                    Capacity = "4"
                });
            }
            return tables;
        } catch (Exception ex) {
            Debug.WriteLine($"GetTablesAsync error: {ex.Message}");
            return new();
        }
    }

    public async Task<(bool ok, string token)> OpenTableAsync(string tableId) {
        try {
            var body = JsonSerializer.Serialize(new { outlet_id = OutletId, table_id = tableId });
            var r = await _http.PostAsync(
                $"{Base}/tables/open",
                new StringContent(body, Encoding.UTF8, "application/json"));
            var resp = await r.Content.ReadAsStringAsync();
            if (r.IsSuccessStatusCode) {
                using var doc = JsonDocument.Parse(resp);
                var token = doc.RootElement.GetProperty("token").GetString() ?? "";
                return (true, token);
            }

            return (false, "");
        } catch (Exception ex) {
            Debug.WriteLine($"OpenTableAsync error: {ex.Message}");
            return (false, "");
        }
    }

    public async Task<bool> CloseTableAsync(string tableId) {
        try {
            var r = await _http.PostAsync(
                $"{Base}/tables/close/{tableId}?outlet_id={OutletId}",
                new StringContent("", Encoding.UTF8, "application/json"));
            return r.IsSuccessStatusCode;
        } catch (Exception ex) {
            Debug.WriteLine($"CloseTableAsync error: {ex.Message}");
            return false;
        }
    }

    public async Task<(int count, decimal total)> GetTableOrdersAsync(string tableId) {
        try {
            var json = await _http.GetStringAsync($"{Base}/orders/table/{tableId}");
            using var doc = JsonDocument.Parse(json);
            int count = 0;
            decimal total = 0;

            foreach (var el in doc.RootElement.EnumerateArray()) {
                count++;
                if (el.TryGetProperty("total_amount", out var amt)) {
                    total += amt.GetDecimal();
                }
            }

            return (count, total);
        } catch (Exception ex) {
            Debug.WriteLine($"GetTableOrdersAsync error: {ex.Message}");
            return (0, 0);
        }
    }

    public string GetWaiterWsUrl() =>
        $"ws://192.168.1.7:8000/ws/waiter/{OutletId}";

    public async Task SetGpsAsync() {
        try {
            var body = """{"lat":12.982713061267125,"lng":80.1900068666091,"radius_meters":100}""";
            await _http.PostAsync(
                $"{Base}/tables/set-location",
                new StringContent(body, Encoding.UTF8, "application/json"));
        } catch (Exception ex) {
            Debug.WriteLine($"SetGpsAsync error: {ex.Message}");
        }
    }

    public async Task<(Models.PinLoginResponse? Response, string? Error)> PinLoginAsync(string pin) {
        try {
            var body = JsonSerializer.Serialize(new { pin }, J);
            var res = await _http.PostAsync($"{Base}/auth/pin-login",
                new StringContent(body, Encoding.UTF8, "application/json"));
            if (!res.IsSuccessStatusCode) {
                var errorBody = await res.Content.ReadAsStringAsync();
                return (null, $"HTTP {(int)res.StatusCode}: {errorBody}");
            }
            var response = JsonSerializer.Deserialize<Models.PinLoginResponse>(await res.Content.ReadAsStringAsync(), J);
            return (response, null);
        } catch (Exception ex) {
            Debug.WriteLine($"PinLoginAsync error: {ex.Message}");
            return (null, $"Network error: {ex.Message}");
        }
    }
}
