import 'api_client.dart';

/// One POS registration code, as minted by
/// `POST /owner/pos-registration-code`.
class PosRegistrationCode {
  final String code;
  final DateTime expiresAt;

  const PosRegistrationCode({required this.code, required this.expiresAt});

  factory PosRegistrationCode.fromJson(Map<String, dynamic> json) {
    return PosRegistrationCode(
      code: json['code'] as String,
      expiresAt: DateTime.parse(json['expires_at'] as String),
    );
  }
}

/// Mints the one-time Registration ID a POS install needs to link to this
/// outlet. No code is ever generated client-side — every code comes from the
/// backend, which is also the only place that decides whether this outlet is
/// approved to receive one.
class PosLinkService {
  final ApiClient _client;

  PosLinkService(this._client);

  /// `POST /owner/pos-registration-code`. Owner-authenticated. A fresh call
  /// mints a NEW code and revokes any earlier unused one for this outlet —
  /// the server does this unconditionally, so simply opening this screen
  /// again is what regenerates the code.
  ///
  /// Throws [ApiException] with statusCode 403 when the outlet has not yet
  /// been admin-approved — callers show that message rather than a form.
  Future<PosRegistrationCode> mintCode() async {
    final data = await _client.post('/owner/pos-registration-code');
    return PosRegistrationCode.fromJson((data as Map).cast<String, dynamic>());
  }
}
