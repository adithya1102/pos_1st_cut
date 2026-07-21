import '../models/customer.dart';
import 'api_client.dart';

/// Result of a successful OTP verification.
class AuthResult {
  const AuthResult({required this.accessToken, required this.customer});
  final String accessToken;
  final Customer customer;
}

/// Abstraction over the OTP flow so a real Firebase implementation can be
/// dropped in later WITHOUT touching any UI code.
abstract class OtpAuthService {
  /// Requests an OTP for [phoneNumber]. Returns an opaque request id.
  Future<String> requestOtp(String phoneNumber);

  /// Verifies [otp] for [phoneNumber]. Returns token + customer on success.
  Future<AuthResult> verifyOtp(String phoneNumber, String otp);
}

/// Backend-backed stub used for this run (dev OTP is `000000`).
/// Mirrors the CareVo Skip API contract exactly.
class StubOtpService implements OtpAuthService {
  StubOtpService(this._api);
  final ApiClient _api;

  @override
  Future<String> requestOtp(String phoneNumber) async {
    final res = await _api.post(
      '/customer/auth/request-otp',
      body: {'phone_number': phoneNumber},
    );
    final map = (res as Map).cast<String, dynamic>();
    return map['request_id']?.toString() ?? '';
  }

  @override
  Future<AuthResult> verifyOtp(String phoneNumber, String otp) async {
    final res = await _api.post(
      '/customer/auth/verify-otp',
      body: {'phone_number': phoneNumber, 'otp': otp},
    );
    final map = (res as Map).cast<String, dynamic>();
    final token = map['access_token']?.toString() ?? '';
    if (token.isEmpty) {
      throw ApiException('Verification failed: no token returned.');
    }
    await _api.setToken(token);
    final customerJson = (map['customer'] as Map?)?.cast<String, dynamic>() ?? {};
    return AuthResult(
      accessToken: token,
      customer: Customer.fromJson(customerJson),
    );
  }
}
