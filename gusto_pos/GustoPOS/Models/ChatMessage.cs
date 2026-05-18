using System.Collections.Generic;

namespace GustoPOS.Models;

public class ChatMessage
{
    public string Text { get; set; } = "";
    public bool IsUser { get; set; }
    public List<string> Suggestions { get; set; } = new();
    public bool HasSuggestions => Suggestions != null && Suggestions.Count > 0;
}
