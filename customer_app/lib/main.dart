import 'package:flutter/material.dart';
import 'package:provider/provider.dart';

import 'config/app_config.dart';
import 'services/api_client.dart';
import 'services/catalog_service.dart';
import 'services/location_service.dart';
import 'services/order_service.dart';
import 'services/otp_auth_service.dart';
import 'services/payment_service.dart';
import 'services/places_service.dart';
import 'state/auth_state.dart';
import 'state/cart_state.dart';
import 'screens/splash_screen.dart';
import 'theme/app_theme.dart';
import 'theme/theme_provider.dart';

Future<void> main() async {
  WidgetsFlutterBinding.ensureInitialized();

  // Build the single API client and restore any persisted token.
  final api = ApiClient();
  await api.loadToken();

  // Load the persisted theme preference.
  final themeProvider = ThemeProvider();
  await themeProvider.load();

  // Wire the service stubs. Swapping to Firebase/Razorpay later means
  // changing only these two lines.
  final OtpAuthService otpService = StubOtpService(api);
  final PaymentService paymentService = StubPaymentService(api);

  runApp(
    MultiProvider(
      providers: [
        ChangeNotifierProvider.value(value: themeProvider),
        Provider<ApiClient>.value(value: api),
        Provider<OtpAuthService>.value(value: otpService),
        Provider<PaymentService>.value(value: paymentService),
        Provider<CatalogService>(create: (_) => CatalogService(api)),
        Provider<OrderService>(create: (_) => OrderService(api)),
        Provider<LocationService>(create: (_) => LocationService()),
        Provider<PlacesService>(create: (_) => PlacesService()),
        ChangeNotifierProvider(
          create: (_) => AuthState(api, otpService),
        ),
        ChangeNotifierProvider(create: (_) => CartState()),
      ],
      child: const CareVoApp(),
    ),
  );
}

class CareVoApp extends StatelessWidget {
  const CareVoApp({super.key});

  @override
  Widget build(BuildContext context) {
    final themeMode = context.watch<ThemeProvider>().mode;
    return MaterialApp(
      title: AppConfig.appName,
      debugShowCheckedModeBanner: false,
      theme: AppTheme.light(),
      darkTheme: AppTheme.dark(),
      themeMode: themeMode,
      home: const SplashScreen(),
    );
  }
}
