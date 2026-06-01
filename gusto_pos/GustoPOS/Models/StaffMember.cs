namespace GustoPOS.Models;

public class StaffMember
{
    public string Id { get; set; } = "";
    public string Name { get; set; } = "";
    public string Role { get; set; } = "";
    public string? AssignedTable { get; set; }
    public string? ShiftStart { get; set; }
    public string? ShiftEnd { get; set; }
    public decimal EarningsToday { get; set; }

    public string ShiftDisplay =>
        ShiftStart != null && ShiftEnd != null
            ? $"{ShiftStart}–{ShiftEnd}"
            : ShiftStart ?? ShiftEnd ?? "—";
}
