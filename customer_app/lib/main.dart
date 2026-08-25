import 'dart:async';

import 'package:firebase_core/firebase_core.dart';
import 'package:flutter/material.dart';
import 'package:provider/provider.dart';

import 'config/app_config.dart';
import 'services/api_client.dart';
import 'services/catalog_service.dart';
import 'services/customer_service.dart';
import 'services/firebase_otp_service.dart';
import 'services/google_auth_service.dart';
import 'services/location_service.dart';
import 'services/cashfree_service.dart';
import 'services/order_service.dart';
import 'services/otp_auth_service.dart';
import 'services/payment_service.dart';
import 'services/places_service.dart';
import 'services/push_service.dart';
import 'state/auth_state.dart';
import 'widgets/focus_release.dart';
import 'state/cart_identity_sync.dart';
import 'state/cart_state.dart';
import 'screens/login_screen.dart';
import 'screens/splash_screen.dart';
import 'theme/app_theme.dart';
import 'theme/theme_provider.dart';

Future<void> main() async {
  WidgetsFlutterBinding.ensureInitialized();

  // Reads android/app/google-services.json (Firebase project carevo-pos).
  // Required before FirebaseAuth.instance is touched.
  if (AppConfig.useFirebaseAuth) {
    await Firebase.initializeApp();
  }

  // Build the single API client and restore any persisted token.
  final api = ApiClient();
  await api.loadToken();

  // Restore the persisted cart before the first frame, so a relaunch shows the
  // basket immediately rather than flashing an empty one. `restore()` adopts
  // the scope the last session left behind, so this is that customer's basket
  // and not a global one — see CartState's docs on why the key carries an
  // identity.
  final cartState = CartState();
  await cartState.restore();

  // Load the persisted theme preference.
  final themeProvider = ThemeProvider();
  await themeProvider.load();

  // Real Firebase phone OTP by default; the backend stub stays reachable via
  // --dart-define=USE_FIREBASE_AUTH=false for offline/dev work.
  final OtpAuthService otpService =
      AppConfig.useFirebaseAuth ? FirebaseOtpService(api) : StubOtpService(api);
  final PaymentService paymentService = StubPaymentService(api);
  final googleAuth = GoogleAuthService(api);
  final push = PushService(api);

  runApp(
    MultiProvider(
      providers: [
        ChangeNotifierProvider.value(value: themeProvider),
        Provider<ApiClient>.value(value: api),
        Provider<OtpAuthService>.value(value: otpService),
        Provider<PaymentService>.value(value: paymentService),
        Provider<CatalogService>(create: (_) => CatalogService(api)),
        Provider<OrderService>(create: (_) => OrderService(api)),
        // Constructed once: the Cashfree SDK exposes a single global callback
        // pair, so a per-checkout instance would have later instances silently
        // overwrite the callbacks of an in-flight one.
        Provider<CashfreeService>(create: (_) => CashfreeService()),
        Provider<CustomerService>(create: (_) => CustomerService(api)),
        // ChangeNotifier, not a plain Provider: the app-resume re-check can
        // change the permission answer with no screen having asked for it, and
        // a screen showing "location is off" has to stop showing that once it
        // isn't true any more.
        ChangeNotifierProvider<LocationService>(create: (_) => LocationService()),
        Provider<PlacesService>(create: (_) => PlacesService()),
        Provider<GoogleAuthService>.value(value: googleAuth),
        Provider<PushService>.value(value: push),
        ChangeNotifierProvider(
          create: (_) => AuthState(api, otpService, googleAuth, push),
        ),
        ChangeNotifierProvider.value(value: cartState),
      ],
      child: const CareVoApp(),
    ),
  );
}

/// Navigator key, so a dead session can route to login from anywhere.
///
/// The 401 can surface on any request from any screen — including ones with no
/// BuildContext to hand, like a background poll — so the redirect cannot depend
/// on where the failure happened.
final GlobalKey<NavigatorState> appNavigatorKey = GlobalKey<NavigatorState>();

class CareVoApp extends StatefulWidget {
  const CareVoApp({super.key});

  @override
  State<CareVoApp> createState() => _CareVoAppState();
}

class _CareVoAppState extends State<CareVoApp> with WidgetsBindingObserver {
  late final ApiClient _api;
  late final CartState _cart;
  late final LocationService _location;
  late final CartIdentitySync _cartIdentity;

  @override
  void initState() {
    super.initState();
    _api = context.read<ApiClient>();
    _cart = context.read<CartState>();
    _location = context.read<LocationService>();
    _api.authFailures.addListener(_onAuthFailure);
    // Re-scopes the cart whenever the signed-in customer changes, by whatever
    // route — sign-in, logout, a second sign-in over a live session, account
    // deletion, or a 401. Started here rather than per screen: the identity can
    // change from a background request with no screen mounted to notice.
    _cartIdentity = CartIdentitySync(context.read<AuthState>(), _cart)..start();
    // The app's ONLY lifecycle observer. Both things it drives are state that
    // the OS can change while the app is not looking, and neither belongs to
    // any one screen — see didChangeAppLifecycleState.
    WidgetsBinding.instance.addObserver(this);
  }

  @override
  void dispose() {
    WidgetsBinding.instance.removeObserver(this);
    _api.authFailures.removeListener(_onAuthFailure);
    _cartIdentity.dispose();
    super.dispose();
  }

  /// Re-sync everything the OS may have changed behind our back.
  ///
  /// Two separate bug families share this one hook, because both were the same
  /// underlying gap — the app read a piece of external state exactly once at
  /// launch and then trusted it forever:
  ///
  ///  * **Cart** — reading it only in `main()` meant a write that had not yet
  ///    landed was lost, and nothing ever re-read afterwards. Flushing on the
  ///    way out and re-reading on the way in closes both halves. Doing this
  ///    here rather than in a screen's `initState` is the point: a per-screen
  ///    re-read fixes that screen and leaves every other one stale.
  ///  * **Location permission** — a grant or revocation made in system settings
  ///    used to need an app restart to be noticed, because the cached status
  ///    was never re-read. It is refreshed here instead.
  ///
  /// Nothing here can raise a permission dialog: [LocationService.refreshPermission]
  /// only reads. An app returning to the foreground must never be the reason a
  /// system prompt appears.
  @override
  void didChangeAppLifecycleState(AppLifecycleState state) {
    super.didChangeAppLifecycleState(state);
    switch (state) {
      case AppLifecycleState.resumed:
        unawaited(_cart.syncFromDisk());
        unawaited(_location.refreshPermission());
      case AppLifecycleState.inactive:
      case AppLifecycleState.paused:
      case AppLifecycleState.hidden:
      case AppLifecycleState.detached:
        // Last chance before the process may be killed. `paused` is the latest
        // callback Android reliably delivers, so the flush has to happen no
        // later than here.
        unawaited(_cart.flush());
    }
  }

  /// Session died -> drop the whole stack and show login.
  ///
  /// pushAndRemoveUntil, not push: leaving the old screens underneath would let
  /// a back-press return to a screen that can no longer load anything, and the
  /// cart/checkout routes behind it are meaningless without a session.
  void _onAuthFailure() {
    final nav = appNavigatorKey.currentState;
    if (nav == null) return;

    // A burst of simultaneous 401s is the NORMAL case — several screens poll at
    // once, so one dead token produces several failures within milliseconds.
    // Matching on the route name keeps that to a single redirect instead of one
    // per failed request (which would visibly flicker).
    if (_currentRouteName == loginRouteName) return;

    nav.pushAndRemoveUntil(
      MaterialPageRoute(
        builder: (_) => const LoginScreen(),
        settings: const RouteSettings(name: loginRouteName),
      ),
      (route) => false,
    );
  }

  String? _currentRouteName;

  @override
  Widget build(BuildContext context) {
    // v2 is SINGLE-THEME and that theme is LIGHT: both ThemeData entry points
    // build the same scheme, so themeMode is pinned rather than followed.
    // Leaving it on ThemeMode.system would imply a dark variant that does not
    // exist — the dark shell was reviewed and dropped.
    context.watch<ThemeProvider>();
    return MaterialApp(
      title: AppConfig.appName,
      navigatorKey: appNavigatorKey,
      debugShowCheckedModeBanner: false,
      theme: AppTheme.light(),
      darkTheme: AppTheme.dark(),
      themeMode: ThemeMode.light,
      navigatorObservers: [
        _RouteNameObserver((name) => _currentRouteName = name),
        FocusReleasingObserver(),
      ],
      home: const SplashScreen(),
    );
  }
}

/// Route name given to the login screen when the session-expiry redirect pushes
/// it, so repeated 401s can tell "already on login" without inspecting widgets.
const String loginRouteName = 'login';

/// Records the current route's name. Deliberately trivial — it exists only so
/// the redirect above is idempotent.
class _RouteNameObserver extends NavigatorObserver {
  _RouteNameObserver(this.onChanged);
  final void Function(String?) onChanged;

  @override
  void didPush(Route<dynamic> route, Route<dynamic>? previousRoute) =>
      onChanged(route.settings.name);

  @override
  void didPop(Route<dynamic> route, Route<dynamic>? previousRoute) =>
      onChanged(previousRoute?.settings.name);

  @override
  void didReplace({Route<dynamic>? newRoute, Route<dynamic>? oldRoute}) =>
      onChanged(newRoute?.settings.name);
}
