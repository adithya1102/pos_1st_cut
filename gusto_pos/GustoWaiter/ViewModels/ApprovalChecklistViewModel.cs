using System;
using System.Collections.Generic;
using System.Collections.ObjectModel;
using System.ComponentModel;
using System.Linq;
using System.Runtime.CompilerServices;
using System.Text.Json;
using System.Threading.Tasks;
using System.Windows.Input;
using Microsoft.Maui.Controls;
using GustoWaiter.Models;
using GustoWaiter.Services;
using MenuItem = GustoWaiter.Models.MenuItem;

namespace GustoWaiter.ViewModels;

public class ApprovalChecklistViewModel : INotifyPropertyChanged {
    private readonly ApiService _api;
    private readonly string _orderId;
    private List<MenuCategory> _menuCats = new();

    // ── Public state ──────────────────────────────────────────────────────────
    public string TableNumber { get; }
    public string CustomerName { get; }
    public string PageTitle => $"Rudrarthi · Table {TableNumber} — Checklist";

    public ObservableCollection<VerifiableOrderItem> OrderItems { get; } = new();
    public ObservableCollection<MenuItem> SearchResults { get; } = new();

    private string _searchQuery = "";
    public string SearchQuery {
        get => _searchQuery;
        set { _searchQuery = value; OnPropertyChanged(); FilterMenu(); }
    }

    private bool _isBusy;
    public bool IsBusy {
        get => _isBusy;
        set { _isBusy = value; OnPropertyChanged(); OnPropertyChanged(nameof(IsNotBusy)); }
    }
    public bool IsNotBusy => !_isBusy;

    public string ProgressText {
        get {
            var done = OrderItems.Count(i => i.IsVerified);
            return $"{done} of {OrderItems.Count} dishes verified";
        }
    }

    public string GrandTotalText {
        get {
            var total = OrderItems.Where(i => i.IsVerified).Sum(i => i.ItemTotal);
            return $"Total (verified items):  ₹{total:F0}";
        }
    }

    // ── Commands ──────────────────────────────────────────────────────────────
    public ICommand ApproveCommand { get; }
    public ICommand AddItemCommand { get; }
    public ICommand RemoveItemCommand { get; }

    // ── Events for page to handle UI concerns ─────────────────────────────────
    public event Func<string, string, string, Task>? ShowAlert;
    public event Action? ApprovalSucceeded;

    // ── Constructor ───────────────────────────────────────────────────────────
    public ApprovalChecklistViewModel(ApiService api, Notification notif) {
        _api = api;
        TableNumber = notif.TableId;
        CustomerName = notif.CustomerName ?? "Customer";
        _orderId = notif.OrderId ?? "";

        if (notif.OrderItems != null)
            foreach (var oi in notif.OrderItems)
                Track(VerifiableOrderItem.FromOrderItemInfo(oi));

        ApproveCommand = new Command(async () => await ApproveAsync());
        AddItemCommand = new Command<MenuItem>(AddMenuItem);
        RemoveItemCommand = new Command<VerifiableOrderItem>(item => {
            OrderItems.Remove(item);
            RefreshTotals();
        });
    }

    // ── Initialization (fetch full order + menu) ──────────────────────────────
    public async Task InitializeAsync() {
        IsBusy = true;
        try {
            if (!string.IsNullOrEmpty(_orderId)) {
                var details = await _api.GetOrderDetailsAsync(_orderId);
                if (details.HasValue)
                    TryPopulateFromJson(details.Value);
            }

            var zone = await _api.GetMenuByZoneAsync("normal");
            if (zone != null) _menuCats = zone.Categories;
        } finally {
            IsBusy = false;
        }
    }

    // ── Private helpers ───────────────────────────────────────────────────────
    private void Track(VerifiableOrderItem item) {
        item.PropertyChanged += (_, e) => {
            if (e.PropertyName is nameof(VerifiableOrderItem.IsVerified)
                              or nameof(VerifiableOrderItem.ItemTotal))
                RefreshTotals();
        };
        OrderItems.Add(item);
    }

    private void RefreshTotals() {
        OnPropertyChanged(nameof(ProgressText));
        OnPropertyChanged(nameof(GrandTotalText));
    }

    private void TryPopulateFromJson(JsonElement root) {
        try {
            if (!root.TryGetProperty("items", out var arr)) return;
            OrderItems.Clear();
            foreach (var el in arr.EnumerateArray()) {
                var name = el.TryGetProperty("name", out var n) ? n.GetString() ?? "" : "";
                var qty = el.TryGetProperty("quantity", out var q) ? q.GetInt32() : 1;
                var price = el.TryGetProperty("unit_price", out var p) ? p.GetDecimal() : 0m;
                var note = el.TryGetProperty("item_notes", out var nt) ? nt.GetString() ?? "" : "";

                var modifiers = new List<OrderItemModifier>();

                // Prefer structured modifier_charges array if backend sends it
                if (el.TryGetProperty("modifier_charges", out var mods)
                    && mods.ValueKind == JsonValueKind.Array) {
                    foreach (var m in mods.EnumerateArray())
                        modifiers.Add(new OrderItemModifier {
                            Label = m.TryGetProperty("label", out var lbl) ? lbl.GetString() ?? "" : "",
                            ExtraCharge = m.TryGetProperty("extra_charge", out var ec) ? ec.GetDecimal() : 0m
                        });
                } else if (el.TryGetProperty("customizations", out var ca)
                           && ca.ValueKind == JsonValueKind.Array) {
                    foreach (var c in ca.EnumerateArray())
                        modifiers.Add(OrderItemModifier.Parse(c.GetString() ?? ""));
                }

                Track(new VerifiableOrderItem {
                    Name = name, Quantity = qty, UnitPrice = price,
                    CustomNote = note, Modifiers = modifiers
                });
            }
            RefreshTotals();
        } catch (Exception ex) {
            CrashLogger.Log(ex, "ApprovalChecklistViewModel.TryPopulateFromJson");
        }
    }

    private void FilterMenu() {
        SearchResults.Clear();
        if (string.IsNullOrWhiteSpace(_searchQuery) || _searchQuery.Length < 2) return;
        var q = _searchQuery.ToLower();
        foreach (var m in _menuCats.SelectMany(c => c.Items)
                                    .Where(i => i.Name.ToLower().Contains(q) && i.IsAvailable)
                                    .Take(8))
            SearchResults.Add(m);
    }

    private void AddMenuItem(MenuItem mi) {
        // Increment existing identical item (no modifiers) or add fresh
        var existing = OrderItems.FirstOrDefault(i => i.Name == mi.Name && !i.HasModifiers);
        if (existing != null)
            existing.Quantity++;
        else
            Track(new VerifiableOrderItem {
                Name = mi.Name, UnitPrice = mi.DisplayPrice, Quantity = 1
            });
        SearchQuery = "";
        RefreshTotals();
    }

    private async Task ApproveAsync() {
        var verified = OrderItems.Where(i => i.IsVerified).ToList();
        if (!verified.Any()) {
            if (ShowAlert != null)
                await ShowAlert("Nothing Verified",
                    "Tick at least one dish to confirm it with the customer before approving.", "OK");
            return;
        }

        IsBusy = true;
        try {
            if (!string.IsNullOrEmpty(_orderId)) {
                // Always sync the verified item list before confirming so kitchen gets accurate data
                var cartItems = verified.Select(i => new CartItem {
                    Name = i.Name, BasePrice = i.UnitPrice, Quantity = i.Quantity,
                    Customizations = i.Modifiers.Select(m => m.DisplayText).ToList(),
                    Note = i.CustomNote
                }).ToList();

                await _api.UpdateOrderItemsAsync(_orderId, cartItems);
                await _api.ConfirmOrderAsync(_orderId);
            }
            ApprovalSucceeded?.Invoke();
        } catch (Exception ex) {
            CrashLogger.Log(ex, "ApprovalChecklistViewModel.ApproveAsync");
            if (ShowAlert != null)
                await ShowAlert("Error", ex.Message, "OK");
        } finally {
            IsBusy = false;
        }
    }

    public event PropertyChangedEventHandler? PropertyChanged;
    protected void OnPropertyChanged([CallerMemberName] string? name = null)
        => PropertyChanged?.Invoke(this, new PropertyChangedEventArgs(name));
}
