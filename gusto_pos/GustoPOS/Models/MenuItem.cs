using System.Collections.Generic;
using System.ComponentModel;
using System.Runtime.CompilerServices;
namespace GustoPOS.Models;
public class MenuModifier {
    public string Id { get; set; } = "";
    public string ModifierName { get; set; } = "";
    public decimal ExtraPrice { get; set; }
}
public class MenuItem : INotifyPropertyChanged {
private bool _isActive = true;
public string Id { get; set; } = "";
public string Name { get; set; } = "";
public string ShortCode { get; set; } = "";
public decimal BasePrice { get; set; }
public decimal PriceNormal { get; set; }  // Normal-zone price (computed from BasePrice)
public decimal PriceAc { get; set; }      // AC-zone price (BasePrice * 1.30, computed in-memory)
public bool IsVeg { get; set; }
public string CategoryId { get; set; } = "";
public bool IsActive {
        get => _isActive;
        set { _isActive = value; OnPropertyChanged(); }
    }
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
