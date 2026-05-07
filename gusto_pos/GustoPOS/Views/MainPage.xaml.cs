using System;
using Microsoft.Maui.Controls;
using Microsoft.Maui.Graphics;
using GustoPOS.Services;
namespace GustoPOS.Views;
public partial class MainPage : ContentPage {
    private readonly ApiService _api;
    private PosTerminalPage? _pos;
    private FloorViewPage? _floor;
    private BillingPage? _billing;
    private ManagementPage? _mgmt;
    public MainPage(ApiService api) {
        InitializeComponent();
        _api = api;
        ShowPOS();
    }
    private void ShowPOS() { _pos ??= new PosTerminalPage(_api); ContentArea.Content = _pos; _pos.OnTabShown(); SetActive(BtnPOS); }
    private void ShowFloor() { _floor ??= new FloorViewPage(_api); ContentArea.Content = _floor; _floor.OnTabShown(); SetActive(BtnFloor); }
    private void ShowBilling() { _billing ??= new BillingPage(_api); ContentArea.Content = _billing; _billing.OnTabShown(); SetActive(BtnBilling); }
    private void ShowMgmt() { _mgmt ??= new ManagementPage(_api); ContentArea.Content = _mgmt; SetActive(BtnMgmt); }
    private void SetActive(Button active) {
        foreach (var b in new[] { BtnPOS, BtnFloor, BtnBilling, BtnMgmt })
            b.BackgroundColor = Color.FromArgb("#00000000");
        active.BackgroundColor = Color.FromArgb("#28A745");
    }
    private void OnPosClicked(object s, EventArgs e) => ShowPOS();
    private void OnFloorClicked(object s, EventArgs e) => ShowFloor();
    private void OnBillingClicked(object s, EventArgs e) => ShowBilling();
    private void OnMgmtClicked(object s, EventArgs e) => ShowMgmt();
}
