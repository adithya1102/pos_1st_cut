// owner_app's splash shows the Gusto brand lockup as an IMAGE.
//
// Mirrors customer_app/test/splash_logo_test.dart. The point is the same: a
// wordmark that is a Text cannot fail to load, but an Image.asset whose path is
// missing from pubspec.yaml's `assets:` list throws only when the screen is
// actually built. owner_app had NO `assets:` block at all before this screen
// existed, so that declaration is new and worth a test that fails loudly if it
// is ever dropped.
//
// The handoff assertions matter as much as the logo ones: this splash exists in
// front of the app's only auth gate, and a splash that renders beautifully but
// never advances would brick the app on launch.
import 'package:flutter/material.dart';
import 'package:flutter/services.dart' show rootBundle;
import 'package:flutter_test/flutter_test.dart';

import 'package:owner_app/config/app_config.dart';
import 'package:owner_app/screens/splash_screen.dart';

class _Destination extends StatelessWidget {
  const _Destination();

  @override
  Widget build(BuildContext context) =>
      const Scaffold(body: Center(child: Text('arrived')));
}

Widget _host() => MaterialApp(
      home: SplashScreen(next: (_) => const _Destination()),
    );

void main() {
  testWidgets('renders the brand lockup', (tester) async {
    await tester.pumpWidget(_host());
    await tester.pump();

    expect(find.byKey(SplashScreen.logoKey), findsOneWidget);
    expect(tester.takeException(), isNull);

    await tester.pumpAndSettle(const Duration(seconds: 2));
  });

  testWidgets('the lockup points at the declared asset', (tester) async {
    await tester.pumpWidget(_host());
    await tester.pump();

    final image = tester.widget<Image>(find.byKey(SplashScreen.logoKey));
    expect((image.image as AssetImage).assetName, SplashScreen.logoAsset);

    await tester.pumpAndSettle(const Duration(seconds: 2));
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
    // The lockup is artwork, so the semantic label is the only thing announcing
    // the app. Losing it would make the splash silent.
    await tester.pumpWidget(_host());
    await tester.pump();

    final image = tester.widget<Image>(find.byKey(SplashScreen.logoKey));
    expect(image.semanticLabel, AppConfig.appName);

    await tester.pumpAndSettle(const Duration(seconds: 2));
  });

  testWidgets('labels itself OWNER, since the lockup reads "Gusto Skip"',
      (tester) async {
    // Without this the staff app and the customer app show the same words on
    // launch, and the tablet gives no hint which one opened.
    await tester.pumpWidget(_host());
    await tester.pump();

    expect(find.text('OWNER'), findsOneWidget);

    await tester.pumpAndSettle(const Duration(seconds: 2));
  });

  testWidgets('hands off to the gate it was given', (tester) async {
    await tester.pumpWidget(_host());
    await tester.pump();
    expect(find.text('arrived'), findsNothing);

    await tester.pumpAndSettle(const Duration(seconds: 2));

    expect(find.text('arrived'), findsOneWidget);
    // Replaced, not stacked — the splash must not be reachable by back.
    expect(find.byKey(SplashScreen.logoKey), findsNothing);
  });
}
