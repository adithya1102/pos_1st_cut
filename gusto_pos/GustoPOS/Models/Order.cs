using System;
using System.Collections.Generic;
namespace GustoPOS.Models;
public class Order {
    public string Id { get; set; } = "";
    public int ReadableId { get; set; }
    public string OutletId { get; set; } = "";
    public string? TableId { get; set; }
    public decimal TotalAmount { get; set; }
    public string OrderStatus { get; set; } = "pending";
    public string? KitchenToken { get; set; }
    public string? PaymentMethod { get; set; }
    public DateTime CreatedAt { get; set; }
    public List<OrderItemDto> Items { get; set; } = new();
}
public class OrderItemDto {
    public string Id { get; set; } = "";
    public string OrderId { get; set; } = "";
    public string? MenuItemId { get; set; }
    public string? NameSnap { get; set; }
    public decimal? PriceSnap { get; set; }
    public int Quantity { get; set; } = 1;
}
public class BillResponse {
    public string PdfPath { get; set; } = "";
    public decimal Total { get; set; }
    public List<Dictionary<string, object>> Items { get; set; } = new();
    public string BillNo { get; set; } = "";
}
public class SettleResponse {
    public int SettledCount { get; set; }
    public decimal TotalAmount { get; set; }
    public string Message { get; set; } = "";
}
public class Table {
    public string Id { get; set; } = "";
    public string Name { get; set; } = "";
    public int Capacity { get; set; } = 4;
    public string Status { get; set; } = "free";
    public bool IsOccupied => Status == "occupied";
}
public class OrderSummary {
    public string Id { get; set; } = "";
    public int ReadableId { get; set; }
    public string? TableId { get; set; }
    public decimal TotalAmount { get; set; }
    public string Status { get; set; } = "pending";
    public string? PaymentMethod { get; set; }
    public DateTime CreatedAt { get; set; }
}
public class BillResult {
    public string PdfPath { get; set; } = "";
    public decimal Total { get; set; }
    public string BillNo { get; set; } = "";
}
public class OutletConfig {
    public int NormalTableCount { get; set; } = 10;
    public int AcTableCount { get; set; } = 10;
}
