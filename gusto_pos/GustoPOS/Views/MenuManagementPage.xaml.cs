using GustoPOS.Models;
using GustoPOS.Services;
using Microsoft.Maui.Graphics;
using PosMenuItem = GustoPOS.Models.MenuItem;

namespace GustoPOS.Views;

public partial class MenuManagementPage : ContentView
{
    private readonly ApiService _api;
    private List<MenuCategory> _categories = new();
    private List<CategoryItem> _categoryItems = new();
    private bool _newDishIsVeg = true;
    private string? _editPriceItemId;

    public event Action? BackRequested;

    public MenuManagementPage(ApiService api)
    {
        InitializeComponent();
        _api = api;
    }

    public async void OnTabShown() => await LoadMenuAsync();

    private async Task LoadMenuAsync()
    {
        var menu = await _api.GetMenuAsync();
        if (menu != null)
        {
            _categories = menu.Categories;
            BuildItemList();
        }

        _categoryItems = await _api.GetCategoriesForMenuAsync();
        NewDishCategory.Items.Clear();
        foreach (var c in _categoryItems) NewDishCategory.Items.Add(c.Name);
        if (NewDishCategory.Items.Count > 0) NewDishCategory.SelectedIndex = 0;
    }

    private void BuildItemList()
    {
        ItemListPanel.Children.Clear();
        foreach (var cat in _categories)
        {
            if (!cat.Items.Any()) continue;

            var catHeader = new Border
            {
                BackgroundColor = Color.FromArgb("#1B4332"),
                StrokeShape = new Microsoft.Maui.Controls.Shapes.RoundRectangle { CornerRadius = 8 },
                Stroke = Colors.Transparent,
                Padding = new Thickness(16, 8),
                Content = new Label
                {
                    Text = cat.Name.ToUpperInvariant(),
                    TextColor = Colors.White,
                    FontSize = 13,
                    FontAttributes = FontAttributes.Bold,
                    CharacterSpacing = 1,
                }
            };
            ItemListPanel.Children.Add(catHeader);

            var card = new Border
            {
                BackgroundColor = Colors.White,
                Stroke = Color.FromArgb("#DEE2E6"),
                StrokeShape = new Microsoft.Maui.Controls.Shapes.RoundRectangle { CornerRadius = 10 },
                Padding = new Thickness(0)
            };

            var itemStack = new StackLayout { Spacing = 0 };
            for (int idx = 0; idx < cat.Items.Count; idx++)
            {
                var item = cat.Items[idx];
                itemStack.Children.Add(BuildItemRow(item));
                if (idx < cat.Items.Count - 1)
                    itemStack.Children.Add(new BoxView { Color = Color.FromArgb("#F0F0F0"), HeightRequest = 1 });
            }
            card.Content = itemStack;
            ItemListPanel.Children.Add(card);
        }
    }

    private View BuildItemRow(PosMenuItem item)
    {
        var vegBadge = new Border
        {
            BackgroundColor = item.IsVeg ? Color.FromArgb("#28A745") : Color.FromArgb("#DC3545"),
            StrokeShape = new Microsoft.Maui.Controls.Shapes.RoundRectangle { CornerRadius = 4 },
            Padding = new Thickness(6, 2),
            Content = new Label
            {
                Text = item.IsVeg ? "VEG" : "NON-VEG",
                TextColor = Colors.White, FontSize = 9, FontAttributes = FontAttributes.Bold
            }
        };

        var nameLabel = new Label
        {
            Text = item.Name,
            TextColor = Colors.Black,
            FontAttributes = FontAttributes.Bold,
            FontSize = 14,
            VerticalOptions = LayoutOptions.Center,
        };

        var priceLabel = new Label
        {
            Text = $"₹{item.BasePrice:F0}",
            TextColor = Color.FromArgb("#1B4332"),
            FontAttributes = FontAttributes.Bold,
            FontSize = 15,
            VerticalOptions = LayoutOptions.Center,
            MinimumWidthRequest = 70,
            HorizontalTextAlignment = TextAlignment.End,
        };

        var editPriceBtn = new Button
        {
            Text = "✏️",
            BackgroundColor = Color.FromArgb("#FFF9E6"),
            TextColor = Color.FromArgb("#856404"),
            CornerRadius = 6,
            FontSize = 14,
            HeightRequest = 36,
            WidthRequest = 44,
            Padding = new Thickness(0),
            VerticalOptions = LayoutOptions.Center,
        };
        editPriceBtn.Clicked += (s, e) => OpenEditPrice(item);

        var unavailBadge = new Border
        {
            IsVisible = !item.IsActive,
            BackgroundColor = Color.FromArgb("#FFF0F0"),
            StrokeShape = new Microsoft.Maui.Controls.Shapes.RoundRectangle { CornerRadius = 4 },
            Stroke = Color.FromArgb("#DC3545"),
            Padding = new Thickness(6, 2),
            VerticalOptions = LayoutOptions.Center,
            Content = new Label
            {
                Text = "Unavailable",
                TextColor = Color.FromArgb("#DC3545"),
                FontSize = 10,
                FontAttributes = FontAttributes.Bold
            }
        };

        var toggle = new Switch
        {
            IsToggled = item.IsActive,
            OnColor = Color.FromArgb("#28A745"),
            ThumbColor = Colors.White,
            Scale = 0.85,
            VerticalOptions = LayoutOptions.Center,
        };
        toggle.Toggled += async (s, e) =>
        {
            item.IsActive = e.Value;
            unavailBadge.IsVisible = !e.Value;
            await _api.ToggleItemAvailabilityAsync(item.Id, e.Value);
        };

        var row = new Grid { Padding = new Thickness(16, 12) };
        row.ColumnDefinitions.Add(new ColumnDefinition(GridLength.Auto));
        row.ColumnDefinitions.Add(new ColumnDefinition(GridLength.Star));
        row.ColumnDefinitions.Add(new ColumnDefinition(GridLength.Auto));
        row.ColumnDefinitions.Add(new ColumnDefinition(GridLength.Auto));
        row.ColumnDefinitions.Add(new ColumnDefinition(GridLength.Auto));
        row.ColumnDefinitions.Add(new ColumnDefinition(GridLength.Auto));
        row.ColumnSpacing = 10;

        row.Add(vegBadge, 0, 0);
        row.Add(nameLabel, 1, 0);
        row.Add(priceLabel, 2, 0);
        row.Add(editPriceBtn, 3, 0);
        row.Add(unavailBadge, 4, 0);
        row.Add(toggle, 5, 0);

        return row;
    }

    private void OpenEditPrice(PosMenuItem item)
    {
        _editPriceItemId = item.Id;
        EditPriceItemName.Text = item.Name;
        EditPriceEntry.Text = item.BasePrice.ToString("F0");
        EditPriceError.Text = "";
        EditPriceOverlay.IsVisible = true;
    }

    private void OnEditPriceCancel(object? s, EventArgs e) => EditPriceOverlay.IsVisible = false;

    private async void OnEditPriceConfirm(object? s, EventArgs e)
    {
        if (_editPriceItemId == null) return;
        if (!decimal.TryParse(EditPriceEntry.Text?.Trim(), out var newPrice) || newPrice <= 0)
        { EditPriceError.Text = "Enter a valid price."; return; }

        EditPriceError.Text = "";
        var ok = await _api.UpdateMenuItemPriceAsync(_editPriceItemId, newPrice);
        if (ok)
        {
            var item = _categories.SelectMany(c => c.Items).FirstOrDefault(i => i.Id == _editPriceItemId);
            if (item != null)
            {
                item.BasePrice = newPrice;
                item.Price = newPrice;
                BuildItemList();
            }
            EditPriceOverlay.IsVisible = false;
            ShowStatus($"Price updated to ₹{newPrice:F0}.");
        }
        else
        {
            EditPriceError.Text = "Failed to update. Check server connection.";
        }
    }

    private void OnBackClicked(object? s, EventArgs e) => BackRequested?.Invoke();

    // ── Add Dish ──────────────────────────────────────────────

    private void OnAddDishClicked(object? s, EventArgs e)
    {
        AddDishOverlay.IsVisible = true;
        AddDishStatus.Text = "";
        NewDishName.Text = "";
        NewDishPrice.Text = "";
        _newDishIsVeg = true;
        BtnVegSelect.BackgroundColor = Color.FromArgb("#28A745");
        BtnVegSelect.TextColor = Colors.White;
        BtnNonVegSelect.BackgroundColor = Color.FromArgb("#E8E8E8");
        BtnNonVegSelect.TextColor = Colors.Black;
    }

    private void OnCloseAddDishClicked(object? s, EventArgs e) => AddDishOverlay.IsVisible = false;

    private void OnVegSelectClicked(object? s, EventArgs e)
    {
        _newDishIsVeg = true;
        BtnVegSelect.BackgroundColor = Color.FromArgb("#28A745"); BtnVegSelect.TextColor = Colors.White;
        BtnNonVegSelect.BackgroundColor = Color.FromArgb("#E8E8E8"); BtnNonVegSelect.TextColor = Colors.Black;
    }

    private void OnNonVegSelectClicked(object? s, EventArgs e)
    {
        _newDishIsVeg = false;
        BtnNonVegSelect.BackgroundColor = Color.FromArgb("#DC3545"); BtnNonVegSelect.TextColor = Colors.White;
        BtnVegSelect.BackgroundColor = Color.FromArgb("#E8E8E8"); BtnVegSelect.TextColor = Colors.Black;
    }

    private async void OnConfirmAddDishClicked(object? s, EventArgs e)
    {
        var name = NewDishName.Text?.Trim();
        var priceText = NewDishPrice.Text?.Trim();
        var catName = NewDishCategory.SelectedItem?.ToString();

        if (string.IsNullOrEmpty(name))
        { AddDishStatus.Text = "Enter a dish name."; AddDishStatus.TextColor = Colors.Red; return; }
        if (!decimal.TryParse(priceText, out var price) || price <= 0)
        { AddDishStatus.Text = "Enter a valid price."; AddDishStatus.TextColor = Colors.Red; return; }
        if (catName == null)
        { AddDishStatus.Text = "Select a category."; AddDishStatus.TextColor = Colors.Red; return; }

        var catItem = _categoryItems.FirstOrDefault(c => c.Name == catName);
        if (catItem == null) { AddDishStatus.Text = "Category not found."; AddDishStatus.TextColor = Colors.Red; return; }

        var sc = string.Concat(name.Where(char.IsLetter).Take(4)).ToUpper();
        AddDishStatus.Text = "Adding..."; AddDishStatus.TextColor = Colors.Gray;

        var newItem = await _api.AddMenuItemAsync(catItem.Id, name, price, _newDishIsVeg, sc);
        if (newItem != null)
        {
            var cat = _categories.FirstOrDefault(c => c.Id == catItem.Id);
            if (cat == null)
            {
                cat = new MenuCategory { Id = catItem.Id, Name = catItem.Name };
                _categories.Add(cat);
            }
            newItem.CategoryId = catItem.Id;
            cat.Items.Add(newItem);
            BuildItemList();
            AddDishStatus.Text = $"'{name}' added!"; AddDishStatus.TextColor = Color.FromArgb("#28A745");
            await Task.Delay(1500);
            AddDishOverlay.IsVisible = false;
        }
        else
        {
            AddDishStatus.Text = "Failed. Check backend."; AddDishStatus.TextColor = Colors.Red;
        }
    }

    private async void ShowStatus(string msg, bool isError = false)
    {
        StatusLabel.Text = msg;
        StatusLabel.TextColor = isError ? Color.FromArgb("#DC3545") : Color.FromArgb("#28A745");
        await Task.Delay(3000);
        StatusLabel.Text = "";
    }
}
