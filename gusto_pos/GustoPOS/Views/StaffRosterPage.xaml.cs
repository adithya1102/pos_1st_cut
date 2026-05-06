using GustoPOS.Models;
using GustoPOS.Services;
using System.Collections.ObjectModel;

namespace GustoPOS.Views;

public partial class StaffRosterPage : ContentView
{
    private readonly ApiService _api;
    private readonly ObservableCollection<StaffMember> _staffList = new();
    private string? _resetPinTargetId;
    private string? _editTargetId;

    public event Action? BackRequested;

    public StaffRosterPage(ApiService api)
    {
        InitializeComponent();
        _api = api;
        StaffCollectionView.ItemsSource = _staffList;
    }

    public async void OnTabShown() => await LoadStaffAsync();

    private async Task LoadStaffAsync()
    {
        var staff = await _api.GetStaffAsync();
        _staffList.Clear();
        foreach (var s in staff) _staffList.Add(s);
    }

    private void OnBackClicked(object? s, EventArgs e) => BackRequested?.Invoke();

    // ── Add Staff ─────────────────────────────────────────────

    private void OnAddNewStaffClicked(object? s, EventArgs e)
    {
        NewStaffName.Text = "";
        NewStaffRole.SelectedIndex = -1;
        NewStaffPin.Text = "";
        AddStaffError.Text = "";
        AddStaffOverlay.IsVisible = true;
    }

    private void OnAddStaffCancel(object? s, EventArgs e) => AddStaffOverlay.IsVisible = false;

    private async void OnAddStaffConfirm(object? s, EventArgs e)
    {
        var name = NewStaffName.Text?.Trim();
        var role = NewStaffRole.SelectedItem as string;
        var pin = NewStaffPin.Text?.Trim();

        if (string.IsNullOrEmpty(name)) { AddStaffError.Text = "Full name is required."; return; }
        if (string.IsNullOrEmpty(role)) { AddStaffError.Text = "Please select a role."; return; }
        if (string.IsNullOrEmpty(pin) || pin.Length != 4 || !pin.All(char.IsDigit))
        { AddStaffError.Text = "PIN must be exactly 4 digits."; return; }

        AddStaffError.Text = "";
        var created = await _api.CreateStaffAsync(name, role, pin);
        if (created != null)
        {
            _staffList.Add(created);
            AddStaffOverlay.IsVisible = false;
            ShowStatus($"{created.Name} added successfully.");
        }
        else
        {
            AddStaffError.Text = "Failed to create staff. Check server connection.";
        }
    }

    // ── Reset PIN ─────────────────────────────────────────────

    private void OnResetPinClicked(object? s, EventArgs e)
    {
        if (s is not Button btn || btn.CommandParameter is not string staffId) return;
        _resetPinTargetId = staffId;
        var member = _staffList.FirstOrDefault(m => m.Id == staffId);
        ResetPinSubtitle.Text = member != null ? $"Setting new PIN for: {member.Name}" : "";
        NewPinEntry.Text = "";
        ResetPinError.Text = "";
        ResetPinOverlay.IsVisible = true;
    }

    private void OnResetPinCancel(object? s, EventArgs e) => ResetPinOverlay.IsVisible = false;

    private async void OnResetPinConfirm(object? s, EventArgs e)
    {
        var pin = NewPinEntry.Text?.Trim();
        if (string.IsNullOrEmpty(pin) || pin.Length != 4 || !pin.All(char.IsDigit))
        { ResetPinError.Text = "PIN must be exactly 4 digits."; return; }
        if (_resetPinTargetId == null) return;

        var ok = await _api.ResetStaffPinAsync(_resetPinTargetId, pin);
        if (ok) { ResetPinOverlay.IsVisible = false; ShowStatus("PIN reset successfully."); }
        else { ResetPinError.Text = "Failed to reset PIN. Check server connection."; }
    }

    // ── Edit Staff ────────────────────────────────────────────

    private void OnEditStaffClicked(object? s, EventArgs e)
    {
        if (s is not Button btn || btn.CommandParameter is not string staffId) return;
        _editTargetId = staffId;
        var member = _staffList.FirstOrDefault(m => m.Id == staffId);
        if (member == null) return;

        EditStaffSubtitle.Text = $"Editing: {member.Name}";
        EditAssignedTable.Text = member.AssignedTable ?? "";
        EditShiftStart.Text = member.ShiftStart ?? "";
        EditShiftEnd.Text = member.ShiftEnd ?? "";
        EditStaffError.Text = "";
        EditStaffOverlay.IsVisible = true;
    }

    private void OnEditStaffCancel(object? s, EventArgs e) => EditStaffOverlay.IsVisible = false;

    private async void OnEditStaffConfirm(object? s, EventArgs e)
    {
        if (_editTargetId == null) return;

        var table = string.IsNullOrWhiteSpace(EditAssignedTable.Text) ? null : EditAssignedTable.Text.Trim();
        var shiftStart = string.IsNullOrWhiteSpace(EditShiftStart.Text) ? null : EditShiftStart.Text.Trim();
        var shiftEnd = string.IsNullOrWhiteSpace(EditShiftEnd.Text) ? null : EditShiftEnd.Text.Trim();

        if (shiftStart != null && !IsValidTime(shiftStart))
        { EditStaffError.Text = "Shift start must be HH:MM (e.g. 09:00)."; return; }
        if (shiftEnd != null && !IsValidTime(shiftEnd))
        { EditStaffError.Text = "Shift end must be HH:MM (e.g. 17:00)."; return; }

        EditStaffError.Text = "";
        var updated = await _api.UpdateStaffAsync(_editTargetId, table, shiftStart, shiftEnd);
        if (updated != null)
        {
            var existing = _staffList.FirstOrDefault(m => m.Id == _editTargetId);
            if (existing != null)
            {
                var idx = _staffList.IndexOf(existing);
                if (idx >= 0) _staffList[idx] = updated;
            }
            EditStaffOverlay.IsVisible = false;
            ShowStatus("Staff details updated.");
        }
        else
        {
            EditStaffError.Text = "Failed to save. Check server connection.";
        }
    }

    private static bool IsValidTime(string t) =>
        t.Length == 5 && t[2] == ':' &&
        int.TryParse(t[..2], out var h) && h >= 0 && h <= 23 &&
        int.TryParse(t[3..], out var m) && m >= 0 && m <= 59;

    // ── Delete Staff ──────────────────────────────────────────

    private async void OnDeleteClicked(object? s, EventArgs e)
    {
        if (s is not Button btn || btn.CommandParameter is not string staffId) return;
        var member = _staffList.FirstOrDefault(m => m.Id == staffId);
        if (member == null) return;

        var ok = await _api.DeleteStaffAsync(staffId);
        if (ok) { _staffList.Remove(member); ShowStatus($"{member.Name} removed."); }
        else { ShowStatus("Delete failed. Check server connection.", isError: true); }
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
