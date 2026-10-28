/// Global, swappable configuration for the Gusto Restaurant app.
///
/// Change [baseUrl] in one place to point the app at a different backend.
/// Targets the deployed backend on Render. For a local backend use
/// `http://10.0.2.2:8000/api/v1` (the Android emulator's alias for the host's
/// `localhost`).
class AppConfig {
  const AppConfig._();

  /// Single source of truth for the backend base URL.
  ///
  /// Overridable at build time with
  /// `--dart-define=API_BASE_URL=https://.../api/v1`. It was previously a bare
  /// literal, so that flag was accepted by the tool and then silently ignored —
  /// a build that looked repointed and was not.
  static const String baseUrl = String.fromEnvironment(
    'API_BASE_URL',
    defaultValue: 'https://gusto-pos-backend.onrender.com/api/v1',
  );

  /// App display name. Mirrors customer_app's AppConfig.appName. Used for the
  /// MaterialApp title and as the splash logo's semantic label — the lockup is
  /// artwork, so this is the only thing announcing the app to a screen reader.
  static const String appName = 'Gusto Restaurant';

  /// Where "Register your restaurant" sends a prospective owner.
  ///
  /// A --dart-define with NO default, deliberately. There is no sign-up
  /// endpoint in this app and no native form; onboarding is a conversation
  /// that CareVo's team finishes by phone, and the link points at whatever
  /// form they are currently using. Hardcoding one would mean a store release
  /// every time that changes, and shipping a stale link is worse than shipping
  /// none.
  ///
  /// Empty means the button is HIDDEN rather than dead — see
  /// [hasOnboardingForm] and OnboardingScreen.
  static const String onboardingFormUrl = String.fromEnvironment(
    'ONBOARDING_FORM_URL',
    defaultValue: '',
  );

  static bool get hasOnboardingForm => onboardingFormUrl.trim().isNotEmpty;

  /// Version shown in the app, so a tester can say which build they are on.
  ///
  /// Kept in step with pubspec.yaml by a test (see version_display_test.dart)
  /// rather than read from the package at runtime: package_info_plus is not a
  /// dependency here, and adding a plugin to render six characters would be a
  /// poor trade.
  static const String appVersion = '1.0.1+5';

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
