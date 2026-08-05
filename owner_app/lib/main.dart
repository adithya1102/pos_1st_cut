import 'package:flutter/material.dart';
import 'package:provider/provider.dart';

import 'config/app_config.dart';
import 'services/api_client.dart';
import 'services/auth_service.dart';
import 'services/menu_service.dart';
import 'services/order_service.dart';
import 'services/outlet_service.dart';
import 'screens/home_screen.dart';
import 'screens/login_screen.dart';
import 'state/auth_state.dart';
import 'state/home_state.dart';
import 'state/orders_state.dart';

void main() {
  final apiClient = ApiClient();

  runApp(GustoOwnerApp(apiClient: apiClient));
}

class GustoOwnerApp extends StatelessWidget {
  final ApiClient apiClient;

  const GustoOwnerApp({super.key, required this.apiClient});

  @override
  Widget build(BuildContext context) {
    return MultiProvider(
      providers: [
        ChangeNotifierProvider(
          create: (_) => AuthState(AuthService(apiClient))..bootstrap(),
        ),
        ChangeNotifierProvider(
          create: (_) => HomeState(
            OutletService(apiClient),
            MenuService(apiClient),
          ),
        ),
        ChangeNotifierProvider(
          create: (_) => OrdersState(OrderService(apiClient)),
        ),
      ],
      child: MaterialApp(
        title: 'CareVo Owner',
        debugShowCheckedModeBanner: false,
        theme: _buildTheme(),
        home: const _Root(),
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
