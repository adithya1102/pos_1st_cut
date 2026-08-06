import 'api_client.dart';

/// Wraps the EXISTING staff auth endpoint. No new auth system is introduced.
class AuthService {
  final ApiClient _client;

  AuthService(this._client);

  /// Logs a staff member in via `POST /auth/login`
  /// (OAuth2PasswordRequestForm — form-encoded username/password).
  /// On success the access token is persisted and returned.
  Future<String> login(String username, String password) async {
    final data = await _client.postForm('/auth/login', {
      'username': username,
      'password': password,
    });

    final token = (data is Map) ? data['access_token']?.toString() : null;
    if (token == null || token.isEmpty) {
      throw ApiException(500, 'Login response did not include an access token.');
    }
    await _client.saveToken(token);
    return token;
  }

  /// Public owner self-signup via `POST /register`. Does NOT log the user in
  /// (the new outlet is pending admin verification). Throws [ApiException] on
  /// failure (409 username taken, 429 rate-limited, etc.).
  Future<void> register({
    required String restaurantName,
    String? city,
    String? requestedCity,
    required String phoneNumber,
    required String username,
    required String password,
    required String upiId,
  }) async {
    await _client.post('/register', body: {
      'restaurant_name': restaurantName,
      // Exactly one of city / requested_city — the server rejects both-or-
      // neither. `city` must already be an approved city; `requested_city`
      // files a new-city request for admin approval.
      if (city != null && city.trim().isNotEmpty) 'city': city.trim(),
      if (requestedCity != null && requestedCity.trim().isNotEmpty)
        'requested_city': requestedCity.trim(),
      // Now mandatory server-side, so always sent.
      'phone_number': phoneNumber.trim(),
      'username': username,
      'password': password,
      'upi_id': upiId.trim(),
    });
  }

  /// Cities selectable at signup. Public endpoint — no token needed, which is
  /// required since this populates the form before an account exists.
  Future<List<String>> fetchCities() async {
    final data = await _client.get('/cities');
    return ((data as List?) ?? const [])
        .whereType<Map>()
        .map((m) => m['name']?.toString() ?? '')
        .where((n) => n.isNotEmpty)
        .toList();
  }

  Future<bool> hasToken() async {
    final token = await _client.readToken();
    return token != null && token.isNotEmpty;
  }

  Future<void> logout() => _client.clearToken();
}
