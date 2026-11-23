import 'package:firebase_core/firebase_core.dart';
import 'package:firebase_messaging/firebase_messaging.dart';
import 'package:flutter/foundation.dart';
import 'package:flutter/material.dart';
import 'package:provider/provider.dart';
import 'package:provider/single_child_widget.dart';

import 'config/app_config.dart';
import 'services/api_client.dart';
import 'services/auth_service.dart';
import 'services/location_service.dart';
import 'services/meal_slot_service.dart';
import 'services/menu_ocr_service.dart';
import 'services/menu_service.dart';
import 'services/offer_service.dart';
import 'services/order_service.dart';
import 'services/outlet_service.dart';
import 'services/pos_link_service.dart';
import 'services/staff_push_service.dart';
import 'screens/home_screen.dart';
import 'screens/login_screen.dart';
import 'screens/splash_screen.dart';
import 'state/auth_state.dart';
import 'state/home_state.dart';
import 'state/offers_state.dart';
import 'state/orders_state.dart';

Future<void> main() async {
  WidgetsFlutterBinding.ensureInitialized();

  // Reads android/app/google-services.json (Firebase project carevo-pos,
  // package com.carevo.owner_app). Required before FirebaseMessaging is
  // touched. Wrapped because a device with no Play Services must still be able
  // to run the restaurant — it just won't get order notifications.
  try {
    await Firebase.initializeApp();

    // Registered BEFORE runApp, and only after init succeeded: FCM binds the
    // background entry point during plugin startup, so a handler attached
    // later is not there when the process is spawned cold to deliver a
    // message.
    //
    // This does not control whether backgrounded alerts appear — the backend
    // sends a `notification` block and Android draws that itself. It is the
    // hook for the `data` half. See staffBackgroundHandler.
    FirebaseMessaging.onBackgroundMessage(staffBackgroundHandler);
  } catch (e) {
    if (kDebugMode) debugPrint('Firebase init failed (push disabled): $e');
  }

  final apiClient = ApiClient();

  runApp(GustoOwnerApp(apiClient: apiClient));
}

/// The app's provider list, shared by [main] and by widget tests that need
/// the real tree rather than a hand-picked subset — a subset is exactly how
/// the OutletService gap (missing from this list, see payment_modes_screen.dart
/// and payment_tab_screen.dart) went unnoticed by the existing test suite.
List<SingleChildWidget> buildAppProviders(ApiClient apiClient) {
  // One instance, shared between HomeState's constructor and its own
  // Provider — PaymentModesScreen and PaymentTabScreen look this up directly
  // via context.read<OutletService>() and need it exposed on its own, not
  // just buried inside HomeState's constructor arguments.
  final outletService = OutletService(apiClient);
  return [
    ChangeNotifierProvider(
      create: (_) => AuthState(AuthService(apiClient))..bootstrap(),
    ),
    Provider<OutletService>.value(value: outletService),
    ChangeNotifierProvider(
      create: (_) => HomeState(
        outletService,
        MenuService(apiClient),
        // Meal slots (migration 043). Optional on HomeState so the dozens of
        // existing two-argument call sites keep compiling; the real app always
        // passes it, and a server without the routes degrades to no chip row.
        MealSlotService(apiClient),
      ),
    ),
    ChangeNotifierProvider(
      create: (_) => OrdersState(OrderService(apiClient)),
    ),
    ChangeNotifierProvider(
      create: (_) => OffersState(OfferService(apiClient)),
    ),
    // Not a ChangeNotifier — it holds no UI state, it just registers this
    // device's token after login and clears it on logout.
    Provider(
      create: (_) => StaffPushService(OrderService(apiClient)),
    ),
    // Registered app-wide, exactly as customer_app registers it: the
    // one-prompt latch inside is app-wide bookkeeping, and a per-screen
    // instance would reset it and re-raise the OS dialog.
    ChangeNotifierProvider<LocationService>(create: (_) => LocationService()),
    // Menu photo import. Holds no state — it uploads and returns
    // suggestions; the review screen owns them until they are approved.
    Provider(create: (_) => MenuOcrService(apiClient)),
    // POS registration link ("Connect your POS"). Holds no state — it mints
    // a fresh code on demand; the screen owns the countdown.
    Provider(create: (_) => PosLinkService(apiClient)),
  ];
}

class GustoOwnerApp extends StatelessWidget {
  final ApiClient apiClient;

  const GustoOwnerApp({super.key, required this.apiClient});

  @override
  Widget build(BuildContext context) {
    return MultiProvider(
      providers: buildAppProviders(apiClient),
      child: MaterialApp(
        title: AppConfig.appName,
        debugShowCheckedModeBanner: false,
        theme: _buildTheme(),
        // The splash only delays _Root, it does not replace it. _Root stays the
        // single auth gate and stays reactive after the handoff, so logout
        // still flips it back to LoginScreen on its own.
        home: SplashScreen(next: (_) => const _Root()),
      ),
    );
  }

  ThemeData _buildTheme() {
    final scheme = ColorScheme.fromSeed(
      seedColor: const Color(AppConfig.brandPurple),
      brightness: Brightness.light,
    ).copyWith(
      secondary: const Color(AppConfig.brandMint),
    );

    return ThemeData(
      useMaterial3: true,
      colorScheme: scheme,
      scaffoldBackgroundColor: const Color(0xFFF7F6F9),
      appBarTheme: AppBarTheme(
        backgroundColor: scheme.surface,
        foregroundColor: const Color(AppConfig.brandInk),
        elevation: 0,
        centerTitle: false,
      ),
      cardTheme: CardThemeData(
        elevation: 0,
        color: scheme.surface,
        shape: RoundedRectangleBorder(
          borderRadius: BorderRadius.circular(12),
          side: BorderSide(color: scheme.outlineVariant),
        ),
        margin: const EdgeInsets.symmetric(horizontal: 12, vertical: 6),
      ),
      inputDecorationTheme: const InputDecorationTheme(
        border: OutlineInputBorder(),
        isDense: true,
      ),
    );
  }
}

/// Chooses Login vs Home based on stored auth.
class _Root extends StatelessWidget {
  const _Root();

  @override
  Widget build(BuildContext context) {
    final loggedIn = context.select<AuthState, bool>((s) => s.loggedIn);
    return loggedIn ? const HomeScreen() : const LoginScreen();
  }
}
