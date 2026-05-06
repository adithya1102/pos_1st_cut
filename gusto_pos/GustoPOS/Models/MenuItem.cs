using System.Collections.Generic;
using System.ComponentModel;
using System.Runtime.CompilerServices;
using System.Text.Json.Serialization;
namespace GustoPOS.Models;
public class MenuModifier {
    public string Id { get; set; } = "";
    public string ModifierName { get; set; } = "";
    public decimal ExtraPrice { get; set; }
}
public class MenuItem : INotifyPropertyChanged {
    private decimal _basePrice;
    private bool _isActive = true;
    private bool _isACMode;

    public string Id { get; set; } = "";
    public string Name { get; set; } = "";
    public string ShortCode { get; set; } = "";

    // Canonical price from the backend — both JSON field names write here.
    // This value is NEVER mutated by AC/zone logic.
    [JsonPropertyName("base_price")]
    public decimal BasePrice {
        get => _basePrice;
        set => _basePrice = value;
    }

    // Some endpoints emit "price" instead of "base_price"; both land in the same slot.
    [JsonPropertyName("price")]
    public decimal Price {
        get => _basePrice;
        set => _basePrice = value;
    }

    public bool IsVeg { get; set; }
    public string CategoryId { get; set; } = "";

    public bool IsActive {
        get => _isActive;
        set { _isActive = value; OnPropertyChanged(); }
    }

    // Flip this flag to switch between Normal and AC display pricing.
    // Raising PropertyChanged(DisplayPrice) lets bound UI update without a cache rebuild.
    public bool IsACMode {
        get => _isACMode;
        set {
            if (_isACMode == value) return;
            _isACMode = value;
            OnPropertyChanged();
            OnPropertyChanged(nameof(DisplayPrice));
        }
    }

    // The price shown in the UI — derived, never stored, never mutates BasePrice.
    public decimal DisplayPrice => IsACMode ? Math.Round(BasePrice * 1.30m, 0) : BasePrice;

    public List<MenuModifier> Modifiers { get; set; } = new();
    public event PropertyChangedEventHandler? PropertyChanged;
    protected void OnPropertyChanged([CallerMemberName] string? n = null)
        => PropertyChanged?.Invoke(this, new PropertyChangedEventArgs(n));
}
public class MenuCategory {
    public string Id { get; set; } = "";
    public string Name { get; set; } = "";
    public List<MenuItem> Items { get; set; } = new();
}
public class Menu {
    public string Id { get; set; } = "";
    public string OutletId { get; set; } = "";
    public string VersionLabel { get; set; } = "";
    public List<MenuCategory> Categories { get; set; } = new();
}
public class CategoryItem {
    public string Id { get; set; } = "";
    public string Name { get; set; } = "";
    public string MenuId { get; set; } = "";
}
