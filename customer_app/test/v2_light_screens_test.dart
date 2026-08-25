// The v2 light-theme screens: login, OTP, cart, checkout.
//
// Two of these assertions exist to pin an EXCLUSION rather than a feature:
//
//  * the OTP screen must keep the SYSTEM keyboard. The prototype's in-app
//    numeric keypad was rejected because Android's system keyboard is what
//    delivers SMS one-time-code autofill. A future "let's match the mockup"
//    change now breaks a test instead of silently making sign-in slower.
//  * the app is single-theme LIGHT. The dark shell was reviewed and dropped.
import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:provider/provider.dart';
import 'package:shared_preferences/shared_preferences.dart';

import 'package:customer_app/models/menu.dart';
import 'package:customer_app/screens/cart_screen.dart';
import 'package:customer_app/screens/login_screen.dart';
import 'package:customer_app/screens/otp_screen.dart';
import 'package:customer_app/services/api_client.dart';
import 'package:customer_app/services/google_auth_service.dart';
import 'package:customer_app/services/otp_auth_service.dart';
import 'package:customer_app/services/push_service.dart';
import 'package:customer_app/state/auth_state.dart';
import 'package:customer_app/state/cart_state.dart';
import 'package:customer_app/theme/app_colors.dart';
import 'package:customer_app/theme/app_theme.dart';
import 'package:customer_app/theme/theme_provider.dart';
import 'package:customer_app/theme/widgets/neo_card.dart';

void _sizeSurface(WidgetTester tester) {
  tester.view.physicalSize = const Size(1080, 2400);
  tester.view.devicePixelRatio = 3.0;
  addTearDown(tester.view.reset);
}

Widget _host(Widget home) {
  SharedPreferences.setMockInitialValues({});
  final api = ApiClient();
  return MultiProvider(
    providers: [
      Provider<ApiClient>.value(value: api),
      Provider<OtpAuthService>(create: (_) => StubOtpService(api)),
      Provider<GoogleAuthService>(create: (_) => GoogleAuthService(api)),
      Provider<PushService>(create: (_) => PushService(api)),
      ChangeNotifierProvider<ThemeProvider>(create: (_) => ThemeProvider()),
      ChangeNotifierProvider<CartState>(create: (_) => CartState()),
      ChangeNotifierProvider<AuthState>(
        create: (_) => AuthState(
          api,
          StubOtpService(api),
          GoogleAuthService(api),
          PushService(api),
        ),
      ),
    ],
    child: MaterialApp(
      theme: AppTheme.light(),
      darkTheme: AppTheme.dark(),
      themeMode: ThemeMode.light,
      home: home,
    ),
  );
}

void main() {
  // testWidgets, not test: AppTheme._build calls GoogleFonts, which tries to
  // fetch a webfont. Under a widget binding that failure is caught and the
  // theme still builds; in a plain `test` it throws before any assertion runs.
  group('the app is single-theme LIGHT', () {
    testWidgets('both ThemeData entry points build at Brightness.light',
        (tester) async {
      expect(AppTheme.light().brightness, Brightness.light);
      expect(AppTheme.dark().brightness, Brightness.light,
          reason: 'darkTheme must not reintroduce the dropped dark shell');
    });

    testWidgets('the scaffold background is the warm-white shell',
        (tester) async {
      expect(AppTheme.light().scaffoldBackgroundColor, AppColors.v2.background);
    });

    testWidgets('the status bar is asked for DARK icons, as a light bar needs',
        (tester) async {
      final overlay = AppTheme.light().appBarTheme.systemOverlayStyle;
      expect(overlay?.statusBarIconBrightness, Brightness.dark);
    });
  });

  group('login (frame 01)', () {
    testWidgets('shows the wordmark and both sign-in routes', (tester) async {
      _sizeSurface(tester);
      await tester.pumpWidget(_host(const LoginScreen()));
      await tester.pump();

      expect(find.text('CareVo Skip'), findsOneWidget);
      expect(find.text('Skip the queue.'), findsOneWidget);
      expect(find.text('Welcome back'), findsOneWidget);
      // Phone-only since 2026-08-25; `login_identifier_field` was the
      // combined phone-or-email box that replaced.
      expect(find.byKey(const Key('login_phone_field')), findsOneWidget);
      expect(find.text('Continue with Google'), findsOneWidget);
    });

    testWidgets('carries no theme toggle — there is nothing to toggle',
        (tester) async {
      _sizeSurface(tester);
      await tester.pumpWidget(_host(const LoginScreen()));
      await tester.pump();

      // The control was removed rather than left as a button that visibly does
      // nothing. Its old home was the app bar, which this screen no longer has.
      expect(find.byType(AppBar), findsNothing);
      expect(find.byIcon(Icons.dark_mode), findsNothing);
      expect(find.byIcon(Icons.light_mode), findsNothing);
    });
  });

  group('OTP (frame 02) — system keyboard, NOT the prototype keypad', () {
    testWidgets('the code field is a single one-time-code autofill target',
        (tester) async {
      _sizeSurface(tester);
      await tester.pumpWidget(_host(const OtpScreen()));
      await tester.pump();

      final field = tester.widget<TextField>(
        find.byKey(const Key('otp_code_field')),
      );
      expect(field.autofillHints, contains(AutofillHints.oneTimeCode),
          reason: 'SMS autofill is the reason the system keyboard was kept');
      expect(field.keyboardType, TextInputType.number);

      // ONE field, not six: one-time-code autofill fills a single field, so
      // splitting the code across six would break the very thing being
      // protected here.
      expect(find.byType(TextField), findsOneWidget);
    });

    testWidgets('no in-app numeric keypad is rendered', (tester) async {
      _sizeSurface(tester);
      await tester.pumpWidget(_host(const OtpScreen()));
      await tester.pump();

      // The rejected design put 1-9, 0 and a backspace key on screen. If any
      // of those digit keys ever appear as tappable text, the keypad is back.
      for (final digit in ['1', '2', '3', '4', '5', '6', '7', '8', '9', '0']) {
        expect(find.widgetWithText(InkWell, digit), findsNothing,
            reason: 'digit key "$digit" suggests the custom keypad returned');
      }
      expect(find.text('⌫'), findsNothing);
    });

    testWidgets('typed digits appear in the six cells', (tester) async {
      _sizeSurface(tester);
      await tester.pumpWidget(_host(const OtpScreen()));
      await tester.pump();

      await tester.enterText(
        find.byKey(const Key('otp_code_field')),
        '4192',
      );
      await tester.pump();

      for (final ch in ['4', '1', '9', '2']) {
        expect(find.text(ch), findsOneWidget);
      }
    });
  });

  group('cart (frame 07)', () {
    CartState cartWithOneLine() {
      final cart = CartState();
      cart.addItem(
        const MenuItem(
          id: 'm1',
          name: 'Veg Dum Biryani',
          basePrice: 220,
          isVeg: true,
          isAvailable: true,
          prepTimeMinutes: 12,
          imageUrl: null,
          tags: [],
          customizations: [],
        ),
        quantity: 2,
      );
      return cart;
    }

    testWidgets('the bill ends in a "To pay" band, not a plain total row',
        (tester) async {
      _sizeSurface(tester);
      SharedPreferences.setMockInitialValues({});
      final api = ApiClient();
      await tester.pumpWidget(
        MultiProvider(
          providers: [
            Provider<ApiClient>.value(value: api),
            ChangeNotifierProvider<ThemeProvider>(
                create: (_) => ThemeProvider()),
            ChangeNotifierProvider<CartState>.value(value: cartWithOneLine()),
          ],
          child: MaterialApp(
            theme: AppTheme.light(),
            home: const CartScreen(),
          ),
        ),
      );
      await tester.pump();

      expect(find.text('Your order'), findsOneWidget);
      expect(find.text('To pay'), findsOneWidget);
      expect(find.text('Item total'), findsOneWidget);
      expect(find.text('Taxes & fees'), findsOneWidget);
      expect(find.text('Continue to payment'), findsOneWidget);
      expect(find.byType(NeoCard), findsWidgets);
    });
  });
}
