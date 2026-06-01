using GustoPOS.Services;
using GustoPOS.ViewModels;

namespace GustoPOS.Views;

public partial class AskGustoPage : ContentView
{
    private readonly AskGustoViewModel _vm;

    public AskGustoPage(ApiService api)
    {
        InitializeComponent();
        _vm = new AskGustoViewModel(api);
        BindingContext = _vm;
        _vm.ChatHistory.CollectionChanged += (_, _) => ScrollToBottom();
    }

    public void OnTabShown() => ScrollToBottom();

    private void ScrollToBottom()
    {
        if (_vm.ChatHistory.Count == 0) return;
        Dispatcher.Dispatch(() =>
            ChatCollectionView.ScrollTo(_vm.ChatHistory[^1], animate: false));
    }
}
