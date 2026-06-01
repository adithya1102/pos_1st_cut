using System.Collections.Generic;

namespace GustoPOS.Models;

public class FreeTablesResponse
{
    public int Count { get; set; }
    public List<int> TableNumbers { get; set; } = new();
}

public class TotalTablesResponse
{
    public int Count { get; set; }
}

public class TopDishResponse
{
    public string? Dish { get; set; }
    public int Quantity { get; set; }
}

public class RevenueResponse
{
    public decimal Revenue { get; set; }
}
