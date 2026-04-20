namespace GustoPOS.Models;

public class StaffProfile {
    public string Id { get; set; } = "";
    public string Name { get; set; } = "";
    public string Role { get; set; } = "";
}

public class PinLoginResponse {
    public string AccessToken { get; set; } = "";
    public string TokenType { get; set; } = "bearer";
    public StaffProfile Staff { get; set; } = new();
}
