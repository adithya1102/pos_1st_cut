// Three fixes to the phone/OTP entry step, each pinned against the specific
// real-world failure that prompted it.
//
//  1. The code cells sat just under the header — exactly where Android drops
//     its incoming-SMS heads-up banner, so the field was covered at the moment
//     the code arrived. They now sit toward the vertical middle.
//  2. A rejected code used to stay in the field. Retyping meant six deletions
//     first, and since the field auto-submits at six characters a half-corrected
//     code fires another doomed attempt — burning another try against the
//     per-hour OTP rate limit. It now clears and refocuses.
//  3. The phone placeholder was a realistic-looking number, which reads as a
//     pre-filled value at a glance.
import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:provider/provider.dart';
import 'package:shared_preferences/shared_preferences.dart';

import 'package:customer_app/screens/login_screen.dart';
import 'package:customer_app/screens/otp_screen.dart';
import 'package:customer_app/services/api_client.dart';
import 'package:customer_app/services/google_auth_service.dart';
import 'package:customer_app/services/otp_auth_service.dart';
import 'package:customer_app/services/push_service.dart';
import 'package:customer_app/state/auth_state.dart';
import 'package:customer_app/state/cart_state.dart';
import 'package:customer_app/theme/app_theme.dart';
import 'package:customer_app/theme/theme_provider.dart';

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
      themeMode: ThemeMode.light,
      home: home,
    ),
  );
}

void main() {
  group('fix 1 — the code cells clear the notification shade', () {
    testWidgets('the entry row sits below the top quarter of the screen',
        (tester) async {
      _sizeSurface(tester);
      await tester.pumpWidget(_host(const OtpScreen()));
      await tester.pump();

      final screenHeight = tester.view.physicalSize.height /
          tester.view.devicePixelRatio;
      final box = tester.getRect(find.byKey(const Key('otp_code_field')));

      // Android's heads-up SMS banner occupies roughly the top eighth. A
      // quarter is the assertion because it is comfortably clear of that while
      // still failing loudly if the field is ever moved back under the header.
      expect(
        box.top,
        greaterThan(screenHeight * 0.25),
        reason: 'the OTP field must not sit where the SMS banner lands — it '
            'was covered at exactly the moment the code arrived',
      );
    });

    testWidgets('the whole screen still fits without overflowing',
        (tester) async {
      _sizeSurface(tester);
      await tester.pumpWidget(_host(const OtpScreen()));
      await tester.pump();

      // The Spacer/IntrinsicHeight arrangement is the kind of change that
      // overflows on a short viewport. tester fails the test on an overflow
      // exception, so simply pumping a small surface is the assertion.
      tester.view.physicalSize = const Size(1080, 1600);
      await tester.pumpAndSettle();
      expect(tester.takeException(), isNull);
    });
  });

  group('fix 2 — a rejected code clears itself', () {
    testWidgets('wrong code is wiped and the error stays on screen',
        (tester) async {
      _sizeSurface(tester);
      await tester.pumpWidget(_host(const OtpScreen()));
      await tester.pump();

      // StubOtpService accepts only AppConfig.devOtpCode, so anything else is
      // rejected through the real verify path rather than a mocked failure.
      await tester.enterText(
        find.byKey(const Key('otp_code_field')),
        '123456',
      );
      await tester.pumpAndSettle();

      final field = tester.widget<TextField>(
        find.byKey(const Key('otp_code_field')),
      );
      expect(field.controller?.text, isEmpty,
          reason: 'a rejected code must not be left for manual deletion — the '
              'field auto-submits at six characters, so a half-corrected code '
              'fires another doomed attempt');

      // Cleared, but not silently: without a persistent message the user is
      // left with an empty field and no reason for it.
      expect(find.byKey(const Key('otp_error')), findsOneWidget);
    });

    testWidgets('typing again dismisses the previous error', (tester) async {
      _sizeSurface(tester);
      await tester.pumpWidget(_host(const OtpScreen()));
      await tester.pump();

      await tester.enterText(
        find.byKey(const Key('otp_code_field')),
        '123456',
      );
      await tester.pumpAndSettle();
      expect(find.byKey(const Key('otp_error')), findsOneWidget);

      await tester.enterText(find.byKey(const Key('otp_code_field')), '9');
      await tester.pump();
      expect(find.byKey(const Key('otp_error')), findsNothing,
          reason: 'a stale rejection must not hang over a fresh code');
    });
  });

  group('fix 3 — the phone placeholder instructs, it does not specimen', () {
    testWidgets('no realistic-looking number is offered as a hint',
        (tester) async {
      _sizeSurface(tester);
      await tester.pumpWidget(_host(const LoginScreen()));
      await tester.pump();

      // Hint text changed with the phone-only redesign; the POINT of the test
      // — that the hint instructs rather than showing a specimen number — is
      // unchanged and still enforced by the digit-run sweep below.
      expect(find.text('Phone number'), findsNWidgets(2));

      // The specific old value, and any digit-run that would read as a
      // pre-filled number.
      expect(find.text('98765 43210'), findsNothing);
      final digitRun = RegExp(r'\d{5}');
      for (final t in tester.widgetList<Text>(find.byType(Text))) {
        final data = t.data;
        if (data != null) {
          expect(digitRun.hasMatch(data), isFalse,
              reason: 'a long digit run in the phone step reads as a value '
                  'already entered, got "$data"');
        }
      }
    });
  });
}
