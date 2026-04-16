using System.Text.Json.Serialization;

namespace GustoWaiter.Models;
public class Notification {
    [JsonPropertyName("id")]
    public string Id { get; set; } = "";

    [JsonPropertyName("table_id")]
    public string TableId { get; set; } = "";

    [JsonPropertyName("customer_name")]
    public string CustomerName { get; set; } = "";

    [JsonPropertyName("type")]
    public string Type { get; set; } = "";

    [JsonPropertyName("order_preview")]
    public string OrderPreview { get; set; } = "";

    [JsonPropertyName("session_id")]
    public string SessionId { get; set; } = "";

    [JsonPropertyName("created_at")]
    public string CreatedAt { get; set; } = "";

    [JsonPropertyName("order_id")]
    public string? OrderId { get; set; }

    [JsonPropertyName("total_amount")]
    public decimal? TotalAmount { get; set; }

    [JsonPropertyName("order_items")]
    public List<OrderItemInfo>? OrderItems { get; set; }
}
public class OrderItemInfo {
    [JsonPropertyName("name")]
    public string Name { get; set; } = "";

    [JsonPropertyName("quantity")]
    public int Quantity { get; set; } = 1;

    [JsonPropertyName("unit_price")]
    public decimal UnitPrice { get; set; }

    [JsonPropertyName("customizations")]
    public List<string> Customizations { get; set; } = new();

    [JsonPropertyName("custom_note")]
    public string CustomNote { get; set; } = "";
}
public class MenuItem {
    [JsonPropertyName("id")]
    public string Id { get; set; } = "";

    [JsonPropertyName("name")]
    public string Name { get; set; } = "";

    [JsonPropertyName("base_price")]
    public decimal BasePrice { get; set; }

    [JsonPropertyName("price")]
    public decimal Price { get; set; }

    [JsonPropertyName("is_veg")]
    public bool IsVeg { get; set; }

    [JsonPropertyName("is_active")]
    public bool IsActive { get; set; } = true; // Default value set to true

    [JsonPropertyName("is_available")]
    public bool IsAvailable { get; set; } = true;

    [JsonPropertyName("customization_options")]
    public List<string> CustomizationOptions { get; set; } = new();

    [JsonIgnore]
    public decimal DisplayPrice => Price > 0 ? Price : BasePrice;
}
public class MenuCategory {
    [JsonPropertyName("id")]
    public string Id { get; set; } = "";

    [JsonPropertyName("name")]
    public string Name { get; set; } = "";

    [JsonPropertyName("items")]
    public List<MenuItem> Items { get; set; } = new();
}
public class MenuResponse {
    [JsonPropertyName("categories")]
    public List<MenuCategory> Categories { get; set; } = new();
}
public class ZoneMenuResponse {
    [JsonPropertyName("zone")]
    public string Zone { get; set; } = "normal";

    [JsonPropertyName("categories")]
    public List<MenuCategory> Categories { get; set; } = new();
}
public class CartItem {
    public string MenuItemId { get; set; } = "";
    public string Name { get; set; } = "";
    public decimal BasePrice { get; set; }
    public int Quantity { get; set; } = 1;
    public string Note { get; set; } = "";
    public List<string> Customizations { get; set; } = new();
    public decimal ItemTotal => BasePrice * Quantity;
}
public class TableInfo {
    [JsonPropertyName("table_id")]
    public string TableId { get; set; } = "";

    [JsonPropertyName("slug")]
    public string Slug { get; set; } = "";

    [JsonPropertyName("is_open")]
    public bool IsOpen { get; set; }

    [JsonPropertyName("capacity")]
    public string Capacity { get; set; } = "4";
}
public class OrderNotification {
    [JsonPropertyName("id")]
    public string Id { get; set; } = "";

    [JsonPropertyName("notif_type")]
    public string NotifType { get; set; } = "";

    [JsonPropertyName("table_id")]
    public string TableId { get; set; } = "";

    [JsonPropertyName("customer_name")]
    public string CustomerName { get; set; } = "";

    [JsonPropertyName("order_id")]
    public string OrderId { get; set; } = "";

    [JsonPropertyName("items")]
    public List<OrderNotificationItem> Items { get; set; } = new();

    [JsonPropertyName("total")]
    public decimal Total { get; set; }

    [JsonPropertyName("is_read")]
    public bool IsRead { get; set; }
}
public class OrderNotificationItem {
    [JsonPropertyName("name")]
    public string Name { get; set; } = "";

    [JsonPropertyName("quantity")]
    public int Quantity { get; set; }

    [JsonPropertyName("unit_price")]
    public decimal UnitPrice { get; set; }

    [JsonPropertyName("item_notes")]
    public string ItemNotes { get; set; } = "";
}
public class OutletConfig {
    [JsonPropertyName("normal_table_count")]
    public int NormalTableCount { get; set; } = 10;

    [JsonPropertyName("ac_table_count")]
    public int AcTableCount { get; set; } = 10;
}
