// The splash now shows the Gusto brand lockup as an IMAGE, where it used to
// typeset the word "CareVo"/"Gusto" in Bevan.
//
// That swap moved a whole class of failure from compile time to run time: a
// wordmark that is a Text cannot fail to load, but an Image.asset whose path is
// missing from pubspec.yaml's `assets:` list throws only when the screen is
// actually built. Nothing else in the suite renders SplashScreen, so without
// these tests a mis-declared asset ships silently and the first thing every
// user sees is a red error box.
//
// SplashScreen starts a 900ms timer in initState and then navigates, so every
// test here asserts on the first frame and afterwards drains that timer — hence
// the full provider set, which the screen it navigates TO needs in order to
// build.
import 'package:flutter/material.dart';
import 'package:flutter/services.dart' show rootBundle;
import 'package:flutter_test/flutter_test.dart';
import 'package:provider/provider.dart';
import 'package:shared_preferences/shared_preferences.dart';

import 'package:customer_app/screens/splash_screen.dart';
import 'package:customer_app/services/api_client.dart';
import 'package:customer_app/services/google_auth_service.dart';
import 'package:customer_app/services/otp_auth_service.dart';
import 'package:customer_app/services/push_service.dart';
import 'package:customer_app/state/auth_state.dart';
import 'package:customer_app/state/cart_state.dart';
import 'package:customer_app/theme/app_theme.dart';
import 'package:customer_app/theme/theme_provider.dart';

Widget _host() {
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
      home: const SplashScreen(),
    ),
  );
}

/// Let the 900ms boot timer fire and the replacement route settle, so the test
/// does not end with a pending timer.
Future<void> _drainBoot(WidgetTester tester) async {
  await tester.pump(const Duration(seconds: 1));
  await tester.pumpAndSettle();
}

void main() {
  testWidgets('renders the brand lockup', (tester) async {
    await tester.pumpWidget(_host());
    await tester.pump();

    expect(find.byKey(SplashScreen.logoKey), findsOneWidget);
    expect(tester.takeException(), isNull);

    await _drainBoot(tester);
  });

  testWidgets('the lockup points at the declared asset', (tester) async {
    await tester.pumpWidget(_host());
    await tester.pump();

    final image = tester.widget<Image>(find.byKey(SplashScreen.logoKey));
    expect((image.image as AssetImage).assetName, SplashScreen.logoAsset);

    await _drainBoot(tester);
  });

  testWidgets('that asset is actually bundled', (tester) async {
    // The Image.asset constructor happily accepts a path that does not exist;
    // only loading it proves pubspec.yaml declares the file.
    await tester.runAsync(() async {
      final data = await rootBundle.load(SplashScreen.logoAsset);
      expect(data.lengthInBytes, greaterThan(0));
    });
  });

  testWidgets('carries the app name for screen readers', (tester) async {
    // The name is artwork now, not text, so the semantic label is the only
    // thing announcing it. Losing it would make the splash silent.
    await tester.pumpWidget(_host());
    await tester.pump();

    final image = tester.widget<Image>(find.byKey(SplashScreen.logoKey));
    expect(image.semanticLabel, contains('Gusto'));

    await _drainBoot(tester);
  });

  testWidgets('does not also print the name as text beside the logo',
      (tester) async {
    // Guards the duplicate the logo swap removed: the lockup already spells
    // "Gusto Skip", so a Text saying it again is a regression, not a signature.
    await tester.pumpWidget(_host());
    await tester.pump();

    expect(find.text('Gusto Skip'), findsNothing);
    expect(find.text('Gusto'), findsNothing);

    await _drainBoot(tester);
  });
}
