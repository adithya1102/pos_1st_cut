using System;
using Microsoft.Maui.Controls;
using GustoWaiter.Models;
using GustoWaiter.Services;
using GustoWaiter.ViewModels;

namespace GustoWaiter.Views;

public partial class ApprovalChecklistPage : ContentPage {
    private readonly ApprovalChecklistViewModel _vm;

    public ApprovalChecklistPage(ApiService api, Notification notif) {
        InitializeComponent();
        _vm = new ApprovalChecklistViewModel(api, notif);
        BindingContext = _vm;

        _vm.ShowAlert += (title, msg, btn) =>
            DisplayAlertAsync(title, msg, btn);

        _vm.ApprovalSucceeded += async () => {
            await DisplayAlertAsync("Sent to Kitchen! ✅",
                $"Order for Table {_vm.TableNumber} has been approved.", "OK");
            await Navigation.PopAsync();
        };

        _ = _vm.InitializeAsync();
    }

    private async void OnBackClicked(object sender, EventArgs e) {
        try { await Navigation.PopAsync(); }
        catch (Exception ex) { CrashLogger.Log(ex, "ApprovalChecklistPage.BackClicked"); }
    }

    // Override DisplayAlertAsync to resolve base-class ambiguity
    private new System.Threading.Tasks.Task DisplayAlertAsync(
        string title, string message, string cancel) =>
        Application.Current!.Windows[0].Page!.DisplayAlertAsync(title, message, cancel);
}
