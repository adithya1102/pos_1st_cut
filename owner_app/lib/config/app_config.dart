/// Global, swappable configuration for the Gusto Owner App.
///
/// Change [baseUrl] in one place to point the app at a different backend.
/// Default targets the Android emulator loopback (`10.0.2.2`) which maps to
/// the host machine's `localhost`.
class AppConfig {
  const AppConfig._();

  /// Single source of truth for the backend base URL.
  static const String baseUrl = 'http://10.0.2.2:8000/api/v1';

  /// Brand palette (used lightly for accents only).
  static const int brandPurple = 0xFF6B2FB3;
  static const int brandMint = 0xFF8FD6B0;
  static const int brandInk = 0xFF171512;
}
