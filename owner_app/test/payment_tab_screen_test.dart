// The Payment tab (bottom nav, between Menu and Offers) — three independent
// switches, each saving itself the instant it is flipped.
//
// THE GROUP THAT MATTERS MOST is "a server error reverts the switch": a
// switch that visibly moved and then silently failed to save is a worse bug
// than the screen not moving at all, because the owner walks away believing
// a setting took effect that never did.
import 'dart:convert';

import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:http/http.dart' as http;
import 'package:http/testing.dart';
import 'package:provider/provider.dart';
import 'package:shared_preferences/shared_preferences.dart';

import 'package:owner_app/screens/payment_tab_screen.dart';
import 'package:owner_app/services/api_client.dart';
import 'package:owner_app/services/outlet_service.dart';

Map<String, dynamic> _settingsJson({
  bool prepaid = false,
  bool pickup = false,
  bool upi = false,
  String? vpa,
  String? payee,
  bool attested = false,
  bool gatewayAvailable = true,
  String? gatewayUnavailableReason,
}) =>
    {
      'outlet_id': 'out-1',
      'prepaid': prepaid,
      'pay_at_pickup': pickup,
      'upi_manual': upi,
      'cashfree_unlocked': gatewayAvailable,
      'upi_vpa': vpa,
      'upi_payee_name': payee,
      'upi_attested': attested,
      'effective_methods': [
        if (prepaid && gatewayAvailable) 'PREPAID',
        if (pickup) 'PAY_AT_PICKUP',
        if (upi) 'UPI_MANUAL',
      ],
      'gateway_available': gatewayAvailable,
      'gateway_unavailable_reason': gatewayUnavailableReason,
      'pay_at_pickup_available': true,
      'pay_at_pickup_unavailable_reason': null,
      'upi_manual_available': upi || (vpa != null && payee != null && attested),
      'upi_manual_unavailable_reason':
          (upi || (vpa != null && payee != null && attested))
              ? null
              : 'UPI_NOT_SET_UP',
    };

class _Backend {
  _Backend({Map<String, dynamic>? initial, this.patchStatus = 200, this.patchError})
      : current = initial ?? _settingsJson();

  Map<String, dynamic> current;
  final int patchStatus;
  final Map<String, dynamic>? patchError;
  Map<String, dynamic>? lastPatchBody;
  int patchCalls = 0;

  late final ApiClient api = ApiClient(
    httpClient: MockClient((req) async {
      if (req.method == 'PATCH') {
        patchCalls++;
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

/// The list is taller than the default 800x600 test viewport once the UPI
/// card's fields are rendered, so the error/summary text below the cards is
/// off-screen until scrolled into view.
Future<void> _scrollTo(WidgetTester tester, Key key) async {
  await tester.scrollUntilVisible(find.byKey(key), 200,
      scrollable: find.byType(Scrollable).first);
  await tester.pumpAndSettle();
}

Widget _host(_Backend backend) => MultiProvider(
      providers: [
        Provider<ApiClient>.value(value: backend.api),
        Provider<OutletService>(create: (_) => OutletService(backend.api)),
      ],
      child: const MaterialApp(home: Scaffold(body: PaymentTabScreen())),
    );

void main() {
  group('Pay when collecting card', () {
    testWidgets('OFF renders the switch off with its risk note',
        (tester) async {
      _seedToken();
      await tester.pumpWidget(_host(_Backend(initial: _settingsJson())));
      await tester.pumpAndSettle();

      final sw = tester.widget<Switch>(
          find.byKey(const Key('payment_tab_pickup_switch')));
      expect(sw.value, isFalse);
      expect(find.textContaining('At your own risk'), findsOneWidget);
    });

    testWidgets('ON sends the PATCH and flips the switch', (tester) async {
      _seedToken();
      final backend = _Backend(initial: _settingsJson());
      await tester.pumpWidget(_host(backend));
      await tester.pumpAndSettle();

      await tester.tap(find.byKey(const Key('payment_tab_pickup_switch')));
      await tester.pumpAndSettle();

      expect(backend.lastPatchBody!['pay_at_pickup'], isTrue);
      final sw = tester.widget<Switch>(
          find.byKey(const Key('payment_tab_pickup_switch')));
      expect(sw.value, isTrue);
    });
  });

  group('Your own UPI card', () {
    testWidgets('not set up: off, empty fields, UPI note shown',
        (tester) async {
      _seedToken();
      await tester.pumpWidget(_host(_Backend(initial: _settingsJson())));
      await tester.pumpAndSettle();

      final sw = tester.widget<Switch>(
          find.byKey(const Key('payment_tab_upi_switch')));
      expect(sw.value, isFalse);
      final vpaField = tester.widget<TextField>(
          find.byKey(const Key('payment_tab_upi_vpa_field')));
      expect(vpaField.controller!.text, isEmpty);
      expect(find.textContaining('not confirmed automatically'),
          findsOneWidget);
    });

    testWidgets(
        'turning ON without details is refused and the switch snaps back',
        (tester) async {
      _seedToken();
      final backend = _Backend(
        initial: _settingsJson(),
        patchStatus: 422,
        patchError: const {
          'error': 'UPI_DETAILS_REQUIRED',
          'message': 'Add your UPI ID and the name on the account before '
              'turning this on.',
        },
      );
      await tester.pumpWidget(_host(backend));
      await tester.pumpAndSettle();

      await tester.tap(find.byKey(const Key('payment_tab_upi_switch')));
      await tester.pumpAndSettle();

      // THE REVERT: the switch is back off, not stuck on.
      final sw = tester.widget<Switch>(
          find.byKey(const Key('payment_tab_upi_switch')));
      expect(sw.value, isFalse,
          reason: 'a failed save must not leave the switch looking ON');
      await _scrollTo(tester, const Key('payment_tab_error'));
      expect(
          find.text('Add your UPI ID and the name on the account before '
              'turning this on.'),
          findsOneWidget);
    });

    testWidgets('ON with a complete, attested VPA succeeds', (tester) async {
      _seedToken();
      final backend = _Backend(
          initial: _settingsJson(
              vpa: 'restaurant@okaxis', payee: 'Test Kitchen'));
      await tester.pumpWidget(_host(backend));
      await tester.pumpAndSettle();

      await tester.tap(
          find.byKey(const Key('payment_tab_upi_attested_checkbox')));
      await tester.pumpAndSettle();
      await tester.tap(find.byKey(const Key('payment_tab_upi_switch')));
      await tester.pumpAndSettle();

      expect(backend.lastPatchBody!['upi_manual'], isTrue);
      expect(backend.lastPatchBody!['upi_attested'], isTrue);
      final sw = tester.widget<Switch>(
          find.byKey(const Key('payment_tab_upi_switch')));
      expect(sw.value, isTrue);
    });

    testWidgets('changing the VPA clears the attestation tick',
        (tester) async {
      _seedToken();
      final backend = _Backend(
          initial: _settingsJson(
              upi: true,
              vpa: 'old@okaxis',
              payee: 'Kitchen',
              attested: true));
      await tester.pumpWidget(_host(backend));
      await tester.pumpAndSettle();

      var box = tester.widget<CheckboxListTile>(
          find.byKey(const Key('payment_tab_upi_attested_checkbox')));
      expect(box.value, isTrue);

      await tester.enterText(
          find.byKey(const Key('payment_tab_upi_vpa_field')), 'new@okhdfcbank');
      await tester.pumpAndSettle();

      box = tester.widget<CheckboxListTile>(
          find.byKey(const Key('payment_tab_upi_attested_checkbox')));
      expect(box.value, isFalse);
      expect(find.byKey(const Key('payment_tab_upi_reattest_hint')),
          findsOneWidget);
    });
  });

  group('Payment gateway card', () {
    testWidgets('available: switch works, encouraging note shown',
        (tester) async {
      _seedToken();
      final backend = _Backend(initial: _settingsJson(gatewayAvailable: true));
      await tester.pumpWidget(_host(backend));
      await tester.pumpAndSettle();

      final sw = tester.widget<Switch>(
          find.byKey(const Key('payment_tab_gateway_switch')));
      expect(sw.onChanged, isNotNull);
      expect(find.text('Customers pay online and it is confirmed '
          'automatically.'), findsOneWidget);
    });

    testWidgets('locked: switch greyed/disabled, "coming soon" shown',
        (tester) async {
      _seedToken();
      final backend = _Backend(
          initial: _settingsJson(
              gatewayAvailable: false,
              gatewayUnavailableReason: 'CASHFREE_LOCKED'));
      await tester.pumpWidget(_host(backend));
      await tester.pumpAndSettle();

      final sw = tester.widget<Switch>(
          find.byKey(const Key('payment_tab_gateway_switch')));
      expect(sw.onChanged, isNull,
          reason: 'a locked gateway must not look tappable');
      expect(find.text('Temporarily unavailable. Coming soon.'),
          findsOneWidget);
      // The encouraging copy must NOT also be shown for this card.
      expect(
          find.text(
              'Customers pay online and it is confirmed automatically.'),
          findsNothing);
    });

    testWidgets('a locked gateway reverts a stray toggle attempt is moot '
        '(disabled, so tapping is a no-op)', (tester) async {
      _seedToken();
      final backend = _Backend(
          initial: _settingsJson(
              gatewayAvailable: false,
              gatewayUnavailableReason: 'CASHFREE_LOCKED'));
      await tester.pumpWidget(_host(backend));
      await tester.pumpAndSettle();

      await tester.tap(find.byKey(const Key('payment_tab_gateway_switch')));
      await tester.pumpAndSettle();

      expect(backend.patchCalls, 0,
          reason: 'a disabled switch must never reach the server');
    });
  });

  group('the summary line', () {
    testWidgets('lists exactly what customers currently see',
        (tester) async {
      _seedToken();
      await tester.pumpWidget(_host(
          _Backend(initial: _settingsJson(pickup: true, upi: true))));
      await tester.pumpAndSettle();
      await _scrollTo(tester, const Key('payment_tab_summary'));

      expect(
          find.text('Customers can pay: Pay when collecting, Your own UPI'),
          findsOneWidget);
    });

    testWidgets('warns when nothing is on offer', (tester) async {
      _seedToken();
      await tester.pumpWidget(_host(_Backend(initial: _settingsJson())));
      await tester.pumpAndSettle();
      await _scrollTo(tester, const Key('payment_tab_summary'));

      expect(find.byKey(const Key('payment_tab_summary')), findsOneWidget);
      expect(find.textContaining('cannot pay you anything'), findsOneWidget);
    });
  });

  group('errors restore the previous state', () {
    testWidgets('a 403 on save disables every switch and shows the message',
        (tester) async {
      _seedToken();
      final backend = _Backend(
        initial: _settingsJson(),
        patchStatus: 403,
        patchError: const {
          'message': 'Only the restaurant owner or a manager can change this.',
        },
      );
      await tester.pumpWidget(_host(backend));
      await tester.pumpAndSettle();

      await tester.tap(find.byKey(const Key('payment_tab_pickup_switch')));
      await tester.pumpAndSettle();

      // Checked BEFORE scrolling: the switches sit above the error text, and
      // scrolling far enough to see it can unbuild an offscreen switch.
      final pickupSw = tester.widget<Switch>(
          find.byKey(const Key('payment_tab_pickup_switch')));
      expect(pickupSw.value, isFalse, reason: 'reverted');
      final upiSw = tester.widget<Switch>(
          find.byKey(const Key('payment_tab_upi_switch')));
      expect(upiSw.onChanged, isNull, reason: 'every switch now disabled');

      await _scrollTo(tester, const Key('payment_tab_error'));
      expect(
          find.text('Only the restaurant owner or a manager can change this.'),
          findsOneWidget);
    });
  });
}
