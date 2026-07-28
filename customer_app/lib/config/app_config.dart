/// Central, swappable configuration for the CareVo Skip customer app.
///
/// The base URL defaults to the deployed backend on Render.
/// Override at build time to target a local backend, e.g.:
///   flutter run --dart-define=API_BASE_URL=http://10.0.2.2:8000/api/v1
/// (`10.0.2.2` is the Android emulator's alias for the host's `localhost`.)
class AppConfig {
  AppConfig._();

  /// Single source of truth for the backend base URL.
  static const String baseUrl = String.fromEnvironment(
    'API_BASE_URL',
    defaultValue: 'https://gusto-pos-backend.onrender.com/api/v1',
  );

  /// Dev OTP code accepted by the stub auth service / backend stub.
  static const String devOtpCode = '000000';

  /// How often the pickup screen polls order status.
  static const Duration pickupPollInterval = Duration(seconds: 4);

  /// Network request timeout.
  static const Duration requestTimeout = Duration(seconds: 20);

  /// App display name.
  static const String appName = 'CareVo Skip';
}
