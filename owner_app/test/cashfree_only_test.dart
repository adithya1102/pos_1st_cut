// CASHFREE_ONLY (backend config.py) — the platform-wide switch that makes
// Cashfree prepaid the only payment path. When the server reports
// `cashfree_only: true` on GET /pos/outlet/payment-methods, the Payment
// modes screen must hide the pay-at-pickup and UPI controls entirely and
// show a plain note instead — tapping a toggle that is guaranteed to 403
// is worse than not showing it.
//
// Switch OFF (the default, `cashfree_only` absent or false) must render
// exactly as payment_modes_test.dart already proves — this file does not
// touch that behaviour.
import 'dart:convert';

import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:http/http.dart' as http;
import 'package:http/testing.dart';
import 'package:provider/provider.dart';
import 'package:shared_preferences/shared_preferences.dart';

import 'package:owner_app/models/payment_settings.dart';
import 'package:owner_app/screens/payment_modes_screen.dart';
import 'package:owner_app/services/api_client.dart';
import 'package:owner_app/services/outlet_service.dart';

Map<String, dynamic> _settingsJson({
  bool prepaid = true,
  bool pickup = false,
  bool upi = false,
  bool unlocked = true,
  bool cashfreeOnly = false,
}) =>
    {
      'outlet_id': 'out-1',
      'prepaid': prepaid,
      'pay_at_pickup': pickup,
      'upi_manual': upi,
      'cashfree_unlocked': unlocked,
      'upi_vpa': null,
      'upi_payee_name': null,
      'upi_attested': false,
      'cashfree_only': cashfreeOnly,
      'effective_methods': [
        if (prepaid && unlocked) 'PREPAID',
        if (!cashfreeOnly && pickup) 'PAY_AT_PICKUP',
        if (!cashfreeOnly && upi) 'UPI_MANUAL',
      ],
    };

class _SettingsBackend {
  _SettingsBackend({Map<String, dynamic>? initial, this.patchStatus = 200,
      this.patchError})
      : current = initial ?? _settingsJson();

  Map<String, dynamic> current;
  final int patchStatus;
  final Map<String, dynamic>? patchError;
  Map<String, dynamic>? lastPatchBody;

  late final ApiClient api = ApiClient(
    httpClient: MockClient((req) async {
      if (req.method == 'PATCH') {
        lastPatchBody = jsonDecode(req.body) as Map<String, dynamic>;
        if (patchStatus != 200) {
          return http.Response(
              jsonEncode({'detail': patchError ?? {'message': 'nope'}}),
              patchStatus,
              headers: {'content-type': 'application/json'});
        }
        current = {...current, ...?lastPatchBody};
        return http.Response(jsonEncode(current), 200,
            headers: {'content-type': 'application/json'});
      }
      return http.Response(jsonEncode(current), 200,
          headers: {'content-type': 'application/json'});
    }),
  );
}

void _seedToken() {
  SharedPreferences.setMockInitialValues(
      {'gusto_owner_access_token': 'staff'});
}

Future<void> _tapSave(WidgetTester tester) async {
  await tester.scrollUntilVisible(
      find.byKey(const Key('payment_modes_save')), 200,
      scrollable: find.byType(Scrollable).first);
  await tester.pumpAndSettle();
  await tester.tap(find.byKey(const Key('payment_modes_save')));
  await tester.pumpAndSettle();
}

Widget _settingsHost(_SettingsBackend backend) => MultiProvider(
      providers: [
        Provider<ApiClient>.value(value: backend.api),
        Provider<OutletService>(create: (_) => OutletService(backend.api)),
      ],
      child: const MaterialApp(home: PaymentModesScreen()),
    );

void main() {
  group('PaymentSettings.cashfreeOnly', () {
    test('parses true from the server', () {
      final s = PaymentSettings.fromJson(_settingsJson(cashfreeOnly: true));
      expect(s.cashfreeOnly, isTrue);
    });

    test('defaults to false when the backend predates the field', () {
      final s = PaymentSettings.fromJson({
        'outlet_id': 'o', 'prepaid': true, 'pay_at_pickup': false,
        'upi_manual': false,
      });
      expect(s.cashfreeOnly, isFalse);
    });
  });

  group('CASHFREE_ONLY on', () {
    testWidgets('hides pickup and UPI controls and shows the note',
        (tester) async {
      final backend =
          _SettingsBackend(initial: _settingsJson(cashfreeOnly: true));
      _seedToken();
      await tester.pumpWidget(_settingsHost(backend));
      await tester.pumpAndSettle();

      expect(find.byKey(const Key('toggle_pay_at_pickup')), findsNothing);
      expect(find.byKey(const Key('toggle_upi_manual')), findsNothing);
      expect(find.byKey(const Key('upi_vpa_field')), findsNothing);
      expect(find.byKey(const Key('cashfree_only_note')), findsOneWidget);
      // Cashfree itself is unaffected — still a normal working toggle.
      expect(find.byKey(const Key('toggle_cashfree')), findsOneWidget);
    });

    testWidgets('saving sends pay_at_pickup=false and upi_manual=false '
        'even if they were true before the cutover', (tester) async {
      final backend = _SettingsBackend(
          initial: _settingsJson(
              cashfreeOnly: true, pickup: true, upi: true));
      _seedToken();
      await tester.pumpWidget(_settingsHost(backend));
      await tester.pumpAndSettle();

      await _tapSave(tester);

      expect(backend.lastPatchBody!['pay_at_pickup'], isFalse);
      expect(backend.lastPatchBody!['upi_manual'], isFalse);
    });

    testWidgets('a 403 from the server is shown, not swallowed',
        (tester) async {
      // Defence in depth: even if the UI is somehow bypassed, the server's
      // own refusal must still surface legibly rather than looking like a
      // generic failure.
      final backend = _SettingsBackend(
        initial: _settingsJson(cashfreeOnly: true),
        patchStatus: 403,
        patchError: {
          'error': 'CASHFREE_ONLY_MODE',
          'message': 'Pay at pickup and UPI are switched off platform-wide '
              'while Cashfree-only mode is active.',
        },
      );
      _seedToken();
      await tester.pumpWidget(_settingsHost(backend));
      await tester.pumpAndSettle();

      await _tapSave(tester);

      expect(find.textContaining('Cashfree-only mode is active'),
          findsOneWidget);
    });
  });

  group('CASHFREE_ONLY off (unchanged)', () {
    testWidgets('pickup and UPI controls render normally', (tester) async {
      final backend =
          _SettingsBackend(initial: _settingsJson(cashfreeOnly: false));
      _seedToken();
      await tester.pumpWidget(_settingsHost(backend));
      await tester.pumpAndSettle();

      expect(find.byKey(const Key('toggle_pay_at_pickup')), findsOneWidget);
      expect(find.byKey(const Key('toggle_upi_manual')), findsOneWidget);
      expect(find.byKey(const Key('cashfree_only_note')), findsNothing);
    });
  });
}
