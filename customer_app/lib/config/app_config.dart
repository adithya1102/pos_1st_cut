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

  /// Web OAuth client id for Google Sign-In. Normally left empty: on Android
  /// the plugin reads `default_web_client_id`, which the google-services Gradle
  /// plugin generates from android/app/google-services.json. Override only for
  /// a build that must use a different OAuth client:
  ///   flutter build apk --dart-define=GOOGLE_SERVER_CLIENT_ID=...apps.googleusercontent.com
  static const String googleServerClientId =
      String.fromEnvironment('GOOGLE_SERVER_CLIENT_ID');

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

  /// Android only. Forces phone verification down the web reCAPTCHA flow
  /// instead of Play Integrity.
  ///
  /// Play Integrity can only vouch for an app distributed through the Play
  /// Store. This app is sideloaded, so the integrity token comes back with no
  /// usable app info and Firebase rejects it (`17028 Invalid app info in
  /// play_integrity_token`) — real numbers never get an SMS. Firebase does not
  /// fall back on its own here: reCAPTCHA is automatic only when Play Integrity
  /// is *unavailable*, not when it returns a token that is refused.
  ///
  /// FLIPPED TO false on 2026-08-21. The condition this comment set out — "once
  /// the app ships on a Play track" — is met: the build on the test device is
  /// `installerPackageName=com.android.vending`, i.e. genuinely Play-installed
  /// and therefore vouchable by Play Integrity.
  ///
  /// The 17028 rejection above was a SIDELOADING artefact plus a second cause
  /// found later: the Play App Signing certificate's SHA-1 was not registered in
  /// Firebase, so `/getProjectConfig` answered `INVALID_CERT_HASH 400` and phone
  /// auth died before any SMS. Registering `FA:68:1F:7C:...` fixed that, and
  /// three phone sign-ins then succeeded on the Play build — 2026-08-21 01:31,
  /// 01:44 and 15:20, the last after a 13.5-hour gap and a cold start.
  ///
  /// Restore the reCAPTCHA path for a SIDELOADED build, where Play Integrity
  /// still cannot vouch for the app:
  ///   flutter run --dart-define=FORCE_RECAPTCHA_FLOW=true
  static const bool forceRecaptchaFlow = bool.fromEnvironment(
    'FORCE_RECAPTCHA_FLOW',
    defaultValue: false,
  );

  /// How often the pickup screen polls order status.
  /// Cashfree environment. Mirrors the backend's CASHFREE_ENV so the app and
  /// the server cannot disagree about which Cashfree they are talking to —
  /// a sandbox session id is rejected by production and vice versa.
  ///
  /// Defaults to sandbox. Going live is an explicit
  /// `--dart-define=CASHFREE_ENV=production` at build time, never a default:
  /// the failure mode of getting this wrong is real money.
  static const String cashfreeEnv = String.fromEnvironment(
    'CASHFREE_ENV',
    defaultValue: 'sandbox',
  );

  static bool get cashfreeIsProduction => cashfreeEnv.toLowerCase() == 'production';

  static const Duration pickupPollInterval = Duration(seconds: 4);

  /// Network request timeout.
  static const Duration requestTimeout = Duration(seconds: 20);

  /// App display name.
  static const String appName = 'Gusto Skip';
}
