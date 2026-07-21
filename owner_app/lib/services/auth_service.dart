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

  Future<bool> hasToken() async {
    final token = await _client.readToken();
    return token != null && token.isNotEmpty;
  }

  Future<void> logout() => _client.clearToken();
}
