using System.Collections.Generic;

namespace GustoPOS.Models;

public class ChatResponse
{
    public string Answer { get; set; } = "";
    public string? Intent { get; set; }
    public float? Confidence { get; set; }
    public List<string> Suggestions { get; set; } = new();
}
