// Smoke test: the app boots and shows the staff login screen.
import 'package:flutter_test/flutter_test.dart';

import 'package:owner_app/main.dart';
import 'package:owner_app/services/api_client.dart';

void main() {
  testWidgets('shows login screen on launch', (WidgetTester tester) async {
    await tester.pumpWidget(GustoOwnerApp(apiClient: ApiClient()));
    await tester.pump();

    expect(find.text('Log in'), findsWidgets);
    expect(find.text('Username'), findsOneWidget);
    expect(find.text('Password'), findsOneWidget);
  });
}
