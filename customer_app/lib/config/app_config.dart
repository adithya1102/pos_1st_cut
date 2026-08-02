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

  /// Google Maps/Places key for any Dart-side (REST) calls. Supplied at build
  /// time and never committed:
  ///   flutter build apk --dart-define=MAPS_API_KEY=AIza...
  /// On Android the native SDK reads its key from the manifest meta-data
  /// (injected via Gradle from local.properties) — this const is for Dart HTTP
  /// callers only. Empty string when not provided.
  static const String mapsApiKey = String.fromEnvironment('MAPS_API_KEY');
  static bool get hasMapsKey => mapsApiKey.isNotEmpty;

  /// Dev OTP code accepted by the stub auth service / backend stub.
  /// Only meaningful when [useFirebaseAuth] is false.
  static const String devOtpCode = '000000';

  /// Real Firebase phone OTP (default) vs the backend stub. Opt back into the
  /// stub for offline/dev work against a backend without FIREBASE_ENABLED:
  ///   flutter run --dart-define=USE_FIREBASE_AUTH=false
  static const bool useFirebaseAuth = bool.fromEnvironment(
    'USE_FIREBASE_AUTH',
    defaultValue: true,
  );

  /// How often the pickup screen polls order status.
  static const Duration pickupPollInterval = Duration(seconds: 4);

  /// Network request timeout.
  static const Duration requestTimeout = Duration(seconds: 20);

  /// App display name.
  static const String appName = 'CareVo Skip';
}
