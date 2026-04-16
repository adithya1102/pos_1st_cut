using System.ComponentModel;
using System.Runtime.CompilerServices;
namespace GustoPOS.Models;
public class CartItem : INotifyPropertyChanged {
    private int _qty = 1;
    public string MenuItemId { get; set; } = "";
    public string Name { get; set; } = "";
    public decimal BasePrice { get; set; }
    public int Quantity {
        get => _qty;
        set { _qty = value; OnPropertyChanged(); OnPropertyChanged(nameof(ItemTotal)); }
    }
    public decimal ItemTotal => BasePrice * Quantity;
    public event PropertyChangedEventHandler? PropertyChanged;
    protected void OnPropertyChanged([CallerMemberName] string? n = null)
        => PropertyChanged?.Invoke(this, new PropertyChangedEventArgs(n));
}
