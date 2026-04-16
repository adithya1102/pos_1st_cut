using Microsoft.Maui.Controls;
using GustoPOS.Services;
using GustoPOS.Views;
namespace GustoPOS;
public partial class App : Application {
    private readonly ApiService _api;
    public App(ApiService api) {
        InitializeComponent();
        _api = api;
    }
    protected override Window CreateWindow(IActivationState? activationState) {
        return new Window(new MainPage(_api)) {
            Title = "GustoPOS — Rudrarthi",
            Width = 1280,
            Height = 800,
            MinimumWidth = 1024,
            MinimumHeight = 600
        };
    }
}
