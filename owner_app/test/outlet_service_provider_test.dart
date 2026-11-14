// Guards the real app provider tree (lib/main.dart's buildAppProviders),
// not a hand-picked test harness. payment_modes_test.dart's own
// _settingsHost wires Provider<OutletService> by hand, which is exactly why
// the real tree's missing registration went unnoticed: every other test
// re-supplied the dependency it was supposed to be checking for.
import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:provider/provider.dart';
import 'package:shared_preferences/shared_preferences.dart';

import 'package:owner_app/main.dart';
import 'package:owner_app/screens/payment_modes_screen.dart';
import 'package:owner_app/services/api_client.dart';

void main() {
  testWidgets(
    'the real app provider tree provides OutletService to PaymentModesScreen',
    (tester) async {
      SharedPreferences.setMockInitialValues(
          {'gusto_owner_access_token': 'staff'});

      final apiClient = ApiClient();

      await tester.pumpWidget(MultiProvider(
        providers: buildAppProviders(apiClient),
        child: const MaterialApp(home: PaymentModesScreen()),
      ));
      await tester.pump();

      // A ProviderNotFoundException thrown inside _load() is caught by
      // PaymentModesScreen's own try/catch, not by the test framework, so it
      // never reaches tester.takeException(). What it DOES do is skip the
      // real HTTP call and land on the screen's generic fallback message —
      // that text is the externally-visible proof of the gap.
      expect(find.text('Could not load your payment settings.'), findsNothing);
    },
  );
}
