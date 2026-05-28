using System;
using System.Collections.Generic;
using System.Text.Json.Serialization;
namespace GustoPOS.Models;
public class Order {
    [JsonPropertyName("id")]          public string Id { get; set; } = "";
    [JsonPropertyName("readable_id")] public int ReadableId { get; set; }
    [JsonPropertyName("outlet_id")]   public string OutletId { get; set; } = "";
    [JsonPropertyName("table_id")]    public string? TableId { get; set; }
    [JsonPropertyName("total_amount")]public decimal TotalAmount { get; set; }
    [JsonPropertyName("order_status")]public string OrderStatus { get; set; } = "pending";
    [JsonPropertyName("kitchen_token")]public string? KitchenToken { get; set; }
    [JsonPropertyName("payment_method")]public string? PaymentMethod { get; set; }
    [JsonPropertyName("created_at")]  public DateTime CreatedAt { get; set; }
    [JsonPropertyName("items")]       public List<OrderItemDto> Items { get; set; } = new();
}
public class OrderItemDto {
    [JsonPropertyName("id")]          public string Id { get; set; } = "";
    [JsonPropertyName("order_id")]    public string OrderId { get; set; } = "";
    [JsonPropertyName("menu_item_id")]public string? MenuItemId { get; set; }
    [JsonPropertyName("name_snap")]   public string? NameSnap { get; set; }
    [JsonPropertyName("price_snap")]  public decimal? PriceSnap { get; set; }
    [JsonPropertyName("quantity")]    public int Quantity { get; set; } = 1;
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
    [JsonPropertyName("normal_table_count")] public int NormalTableCount { get; set; } = 10;
    [JsonPropertyName("ac_table_count")]     public int AcTableCount { get; set; } = 10;
}
