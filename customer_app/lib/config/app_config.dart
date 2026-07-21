/// Central, swappable configuration for the CareVo Skip customer app.
///
/// The base URL defaults to the Android emulator loopback host
/// (`10.0.2.2`) which maps to the developer machine's `localhost`.
/// Override at build time with:
///   flutter run --dart-define=API_BASE_URL=http://192.168.1.10:8000/api/v1
class AppConfig {
  AppConfig._();

  /// Single source of truth for the backend base URL.
  static const String baseUrl = String.fromEnvironment(
    'API_BASE_URL',
    defaultValue: 'http://10.0.2.2:8000/api/v1',
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
