using System.Collections.ObjectModel;
using System.ComponentModel;
using System.Runtime.CompilerServices;
using System.Threading.Tasks;
using Microsoft.Maui.Controls;
using GustoPOS.Models;
using GustoPOS.Services;

namespace GustoPOS.ViewModels;

public class AskGustoViewModel : INotifyPropertyChanged
{
    private readonly ApiService _api;
    private string _chatQuery = "";
    private bool _isBusy;

    public event PropertyChangedEventHandler? PropertyChanged;

    public ObservableCollection<ChatMessage> ChatHistory { get; set; } = new();

    public AskGustoViewModel(ApiService api)
    {
        _api = api;
        ChatHistory.Add(new ChatMessage
        {
            Text = "Hi! I'm Gusto AI. Ask me anything about your restaurant, or tap a chip below.",
            IsUser = false
        });

        FreeTablesCommand  = new Command(async () => await FetchAsync("free-tables",   "Free Tables"),    () => IsNotBusy);
        TotalTablesCommand = new Command(async () => await FetchAsync("total-tables",  "Total Tables"),   () => IsNotBusy);
        TopDishCommand     = new Command(async () => await FetchAsync("top-dish",      "Top Dish Today"), () => IsNotBusy);
        RevenueCommand     = new Command(async () => await FetchAsync("todays-revenue","Today's Revenue"),() => IsNotBusy);
        AskGustoCommand    = new Command<string>(
            async (param) => await RunAskGustoAsync(param),
            (param) => IsNotBusy && (!string.IsNullOrWhiteSpace(param) || !string.IsNullOrWhiteSpace(ChatQuery)));
    }

    public string ChatQuery
    {
        get => _chatQuery;
        set
        {
            _chatQuery = value;
            OnPropertyChanged();
            AskGustoCommand.ChangeCanExecute();
        }
    }

    public bool IsBusy
    {
        get => _isBusy;
        set
        {
            _isBusy = value;
            OnPropertyChanged();
            OnPropertyChanged(nameof(IsNotBusy));
            FreeTablesCommand.ChangeCanExecute();
            TotalTablesCommand.ChangeCanExecute();
            TopDishCommand.ChangeCanExecute();
            RevenueCommand.ChangeCanExecute();
            AskGustoCommand.ChangeCanExecute();
        }
    }

    public bool IsNotBusy => !_isBusy;

    public Command FreeTablesCommand      { get; }
    public Command TotalTablesCommand     { get; }
    public Command TopDishCommand         { get; }
    public Command RevenueCommand         { get; }
    public Command<string> AskGustoCommand { get; }

    private async Task FetchAsync(string key, string displayLabel)
    {
        IsBusy = true;
        ChatHistory.Add(new ChatMessage { Text = displayLabel, IsUser = true });

        var thinking = new ChatMessage { Text = "Gusto is thinking...", IsUser = false };
        ChatHistory.Add(thinking);

        string result = key switch
        {
            "free-tables"    => await _api.GetFreeTablesAsync(),
            "total-tables"   => await _api.GetTotalTablesAsync(),
            "top-dish"       => await _api.GetTopDishAsync(),
            "todays-revenue" => await _api.GetTodaysRevenueAsync(),
            _                => "Unknown query.",
        };

        var idx = ChatHistory.IndexOf(thinking);
        if (idx >= 0)
            ChatHistory[idx] = new ChatMessage { Text = result, IsUser = false };

        IsBusy = false;
    }

    private async Task RunAskGustoAsync(string? explicitQuery = null)
    {
        var query = string.IsNullOrWhiteSpace(explicitQuery) ? ChatQuery.Trim() : explicitQuery.Trim();
        if (string.IsNullOrWhiteSpace(query)) return;

        ChatHistory.Add(new ChatMessage { Text = query, IsUser = true });
        if (string.IsNullOrWhiteSpace(explicitQuery))
            ChatQuery = "";

        IsBusy = true;
        var thinking = new ChatMessage { Text = "Gusto is thinking...", IsUser = false };
        ChatHistory.Add(thinking);

        var response = await _api.AskGustoAsync(query);

        var idx = ChatHistory.IndexOf(thinking);
        if (idx >= 0)
            ChatHistory[idx] = new ChatMessage
            {
                Text = response?.Answer ?? "No answer returned.",
                IsUser = false,
                Suggestions = response?.Suggestions ?? new()
            };

        IsBusy = false;
    }

    protected void OnPropertyChanged([CallerMemberName] string? name = null)
        => PropertyChanged?.Invoke(this, new PropertyChangedEventArgs(name));
}
