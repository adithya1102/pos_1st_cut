using GustoPOS.Models;
using GustoPOS.Services;
using System.Collections.ObjectModel;

namespace GustoPOS.Views;

public partial class CategoryManagementPage : ContentView
{
    private readonly ApiService _api;
    private readonly ObservableCollection<CategoryItem> _categories = new();
    private string? _renameTargetId;

    public event Action? BackRequested;

    public CategoryManagementPage(ApiService api)
    {
        InitializeComponent();
        _api = api;
        CategoryCollectionView.ItemsSource = _categories;
    }

    public async void OnTabShown() => await LoadCategoriesAsync();

    private async Task LoadCategoriesAsync()
    {
        var cats = await _api.GetCategoriesForMenuAsync();
        _categories.Clear();
        foreach (var c in cats) _categories.Add(c);
    }

    private void OnBackClicked(object? s, EventArgs e) => BackRequested?.Invoke();

    // ── Add Category ──────────────────────────────────────────

    private void OnAddCategoryClicked(object? s, EventArgs e)
    {
        NewCategoryName.Text = "";
        AddCategoryError.Text = "";
        AddCategoryOverlay.IsVisible = true;
    }

    private void OnAddCategoryCancel(object? s, EventArgs e) => AddCategoryOverlay.IsVisible = false;

    private async void OnAddCategoryConfirm(object? s, EventArgs e)
    {
        var name = NewCategoryName.Text?.Trim();
        if (string.IsNullOrEmpty(name))
        { AddCategoryError.Text = "Category name is required."; return; }

        AddCategoryError.Text = "";
        var created = await _api.CreateCategoryAsync(name);
        if (created != null)
        {
            _categories.Add(created);
            AddCategoryOverlay.IsVisible = false;
            ShowStatus($"'{created.Name}' added.");
        }
        else
        {
            AddCategoryError.Text = "Failed to create category. Check server connection.";
        }
    }

    // ── Rename Category ───────────────────────────────────────

    private void OnRenameCategoryClicked(object? s, EventArgs e)
    {
        if (s is not Button btn || btn.CommandParameter is not string catId) return;
        _renameTargetId = catId;
        var cat = _categories.FirstOrDefault(c => c.Id == catId);
        RenameCategoryEntry.Text = cat?.Name ?? "";
        RenameCategoryError.Text = "";
        RenameCategoryOverlay.IsVisible = true;
    }

    private void OnRenameCategoryCancel(object? s, EventArgs e) => RenameCategoryOverlay.IsVisible = false;

    private async void OnRenameCategoryConfirm(object? s, EventArgs e)
    {
        var name = RenameCategoryEntry.Text?.Trim();
        if (string.IsNullOrEmpty(name)) { RenameCategoryError.Text = "Name is required."; return; }
        if (_renameTargetId == null) return;

        RenameCategoryError.Text = "";
        var ok = await _api.UpdateCategoryAsync(_renameTargetId, name);
        if (ok)
        {
            var cat = _categories.FirstOrDefault(c => c.Id == _renameTargetId);
            if (cat != null)
            {
                var idx = _categories.IndexOf(cat);
                _categories[idx] = new CategoryItem { Id = cat.Id, Name = name, MenuId = cat.MenuId };
            }
            RenameCategoryOverlay.IsVisible = false;
            ShowStatus($"Category renamed to '{name}'.");
        }
        else
        {
            RenameCategoryError.Text = "Failed to rename. Check server connection.";
        }
    }

    // ── Delete Category ───────────────────────────────────────

    private async void OnDeleteCategoryClicked(object? s, EventArgs e)
    {
        if (s is not Button btn || btn.CommandParameter is not string catId) return;
        var cat = _categories.FirstOrDefault(c => c.Id == catId);
        if (cat == null) return;

        var ok = await _api.DeleteCategoryAsync(catId);
        if (ok) { _categories.Remove(cat); ShowStatus($"'{cat.Name}' deleted."); }
        else { ShowStatus("Delete failed — category may have items attached.", isError: true); }
    }

    // ── Status toast ──────────────────────────────────────────

    private async void ShowStatus(string msg, bool isError = false)
    {
        StatusLabel.Text = msg;
        StatusLabel.TextColor = isError
            ? Microsoft.Maui.Graphics.Color.FromArgb("#DC3545")
            : Microsoft.Maui.Graphics.Color.FromArgb("#28A745");
        await Task.Delay(3000);
        StatusLabel.Text = "";
    }
}
