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
public class ModifierOption {
    [JsonPropertyName("id")]
    public string Id { get; set; } = "";

    [JsonPropertyName("label")]
    public string Label { get; set; } = "";

    [JsonPropertyName("extra_price")]
    public decimal ExtraPrice { get; set; }

    [JsonPropertyName("modifier_type")]
    public string ModifierType { get; set; } = "";

    [JsonPropertyName("group_name")]
    public string GroupName { get; set; } = "";
}
public class MenuItem {
    [JsonPropertyName("id")]
    public string Id { get; set; } = "";

    [JsonPropertyName("name")]
    public string Name { get; set; } = "";

    [JsonPropertyName("price")]
    public decimal Price { get; set; }

    [JsonPropertyName("base_price")]
    public decimal BasePrice {
        get => Price;
        set => Price = value;
    }

    [JsonPropertyName("is_veg")]
    public bool IsVeg { get; set; }

    public bool IsActive { get; set; } = true;

    [JsonPropertyName("is_available")]
    public bool IsAvailable { get; set; } = true;

    [JsonPropertyName("customization_options")]
    public List<ModifierOption> CustomizationOptions { get; set; } = new();

    [JsonIgnore]
    public decimal DisplayPrice => Price;
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

// ── Approval Checklist models ─────────────────────────────────────────────────

public class OrderItemModifier {
    [JsonPropertyName("label")]
    public string Label { get; set; } = "";

    [JsonPropertyName("extra_charge")]
    public decimal ExtraCharge { get; set; } = 0;

    [JsonIgnore]
    public string DisplayText => ExtraCharge > 0 ? $"{Label}  +₹{ExtraCharge:F0}" : Label;

    // Parse "Extra Cheese +₹25" style strings from existing customizations list
    public static OrderItemModifier Parse(string raw) {
        var idx = raw.LastIndexOf("+₹", StringComparison.Ordinal);
        if (idx > 0 && decimal.TryParse(raw[(idx + 2)..].Trim(), out var charge))
            return new OrderItemModifier { Label = raw[..idx].Trim(), ExtraCharge = charge };
        return new OrderItemModifier { Label = raw.Trim() };
    }
}

public class VerifiableOrderItem : System.ComponentModel.INotifyPropertyChanged {
    public string Name { get; set; } = "";

    private int _quantity = 1;
    public int Quantity {
        get => _quantity;
        set {
            if (_quantity == value) return;
            _quantity = value;
            Notify(nameof(Quantity));
            Notify(nameof(DisplayQuantityPrice));
            Notify(nameof(ItemTotal));
        }
    }

    public decimal UnitPrice { get; set; }
    public List<OrderItemModifier> Modifiers { get; set; } = new();
    public string CustomNote { get; set; } = "";

    private bool _isVerified;
    public bool IsVerified {
        get => _isVerified;
        set {
            if (_isVerified == value) return;
            _isVerified = value;
            Notify(nameof(IsVerified));
            Notify(nameof(VerifiedLabel));
        }
    }

    [JsonIgnore] public string VerifiedLabel => IsVerified ? "✓ OK" : "Verify";
    [JsonIgnore] public decimal ModifiersExtra => Modifiers.Sum(m => m.ExtraCharge);
    [JsonIgnore] public decimal ItemTotal => (UnitPrice + ModifiersExtra) * Quantity;
    [JsonIgnore] public string DisplayQuantityPrice => $"x{Quantity}   ₹{ItemTotal:F0}";
    [JsonIgnore] public bool HasModifiers => Modifiers.Any();
    [JsonIgnore] public bool HasNote => !string.IsNullOrWhiteSpace(CustomNote);
    [JsonIgnore] public string NoteDisplay => $"Note: {CustomNote}";

    public event System.ComponentModel.PropertyChangedEventHandler? PropertyChanged;
    private void Notify(string prop) =>
        PropertyChanged?.Invoke(this, new System.ComponentModel.PropertyChangedEventArgs(prop));

    public static VerifiableOrderItem FromOrderItemInfo(OrderItemInfo oi) => new() {
        Name = oi.Name, Quantity = oi.Quantity, UnitPrice = oi.UnitPrice,
        CustomNote = oi.CustomNote,
        Modifiers = oi.Customizations.Select(OrderItemModifier.Parse).ToList()
    };

    public static VerifiableOrderItem FromCartItem(CartItem ci) => new() {
        Name = ci.Name, Quantity = ci.Quantity, UnitPrice = ci.BasePrice,
        CustomNote = ci.Note,
        Modifiers = ci.Customizations.Select(OrderItemModifier.Parse).ToList()
    };
}
