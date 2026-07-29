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
    required String username,
    required String password,
    required String upiId,
  }) async {
    await _client.post('/register', body: {
      'restaurant_name': restaurantName,
      if (city != null && city.trim().isNotEmpty) 'city': city.trim(),
      'username': username,
      'password': password,
      'upi_id': upiId.trim(),
    });
  }

  Future<bool> hasToken() async {
    final token = await _client.readToken();
    return token != null && token.isNotEmpty;
  }

  Future<void> logout() => _client.clearToken();
}
