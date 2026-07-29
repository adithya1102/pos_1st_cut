/// Global, swappable configuration for the Gusto Owner App.
///
/// Change [baseUrl] in one place to point the app at a different backend.
/// Targets the deployed backend on Render. For a local backend use
/// `http://10.0.2.2:8000/api/v1` (the Android emulator's alias for the host's
/// `localhost`).
class AppConfig {
  const AppConfig._();

  /// Single source of truth for the backend base URL.
  static const String baseUrl = 'https://gusto-pos-backend.onrender.com/api/v1';

  /// Brand palette (used lightly for accents only).
  static const int brandPurple = 0xFF6B2FB3;
  static const int brandMint = 0xFF8FD6B0;
  static const int brandInk = 0xFF171512;

  /// Cloudinary unsigned upload (dish images). Cloud name + an *unsigned*
  /// upload preset — no API secret lives in the app. Overridable at build time
  /// with --dart-define=CLOUDINARY_CLOUD_NAME=... / CLOUDINARY_UPLOAD_PRESET=...
  static const String cloudinaryCloudName =
      String.fromEnvironment('CLOUDINARY_CLOUD_NAME', defaultValue: 'dglpn1zyi');
  static const String cloudinaryUploadPreset =
      String.fromEnvironment('CLOUDINARY_UPLOAD_PRESET', defaultValue: 'gusto1');

  static bool get cloudinaryConfigured =>
      cloudinaryCloudName.isNotEmpty && cloudinaryUploadPreset.isNotEmpty;
}
