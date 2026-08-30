// Smoke test: the app boots, shows the branded splash, then falls through to
// the staff login screen.
//
// The splash is a pause in front of the auth gate, not a replacement for it, so
// the original assertion still holds — a launch with no stored token must end on
// LoginScreen. It just no longer holds on the FIRST frame, which is what this
// test used to check.
import 'package:flutter_test/flutter_test.dart';

import 'package:owner_app/main.dart';
import 'package:owner_app/screens/splash_screen.dart';
import 'package:owner_app/services/api_client.dart';

void main() {
  testWidgets('shows the splash, then the login screen', (tester) async {
    await tester.pumpWidget(GustoOwnerApp(apiClient: ApiClient()));
    await tester.pump();

    // The splash owns the first frame.
    expect(find.byKey(SplashScreen.logoKey), findsOneWidget);

    // Let the boot pause elapse and the replacement route settle.
    await tester.pump(const Duration(seconds: 1));
    await tester.pumpAndSettle();

    expect(find.byKey(SplashScreen.logoKey), findsNothing);
    expect(find.text('Log in'), findsWidgets);
    expect(find.text('Username'), findsOneWidget);
    expect(find.text('Password'), findsOneWidget);
  });
}
