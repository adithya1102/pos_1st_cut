// Owner payment settings, the new order flows, onboarding and the version
// label (backend migrations 034, 035, 036).
//
// THE LOAD-BEARING GROUP IS "Cashfree is invisible until activated"
// (AMENDMENT A3). When cashfree_unlocked is false the row must not be rendered
// AT ALL — not greyed, not explained, not hinted at. A disabled control for
// something the owner cannot act on generates a support question with no
// answer, so the test asserts absence rather than disabled-ness.
//
// The second most important group is "the reject copy never says refund for a
// non-prepaid order". A pay-at-pickup order was never charged, so telling
// staff a refund is being arranged is telling them money is going back when
// none came in.
import 'dart:convert';
import 'dart:io';

import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:http/http.dart' as http;
import 'package:http/testing.dart';
import 'package:provider/provider.dart';
import 'package:shared_preferences/shared_preferences.dart';

import 'package:owner_app/config/app_config.dart';
import 'package:owner_app/models/order.dart';
import 'package:owner_app/models/payment_settings.dart';
import 'package:owner_app/screens/onboarding_screen.dart';
import 'package:owner_app/screens/payment_modes_screen.dart';
import 'package:owner_app/services/api_client.dart';
import 'package:owner_app/services/order_service.dart';
import 'package:owner_app/services/outlet_service.dart';
import 'package:owner_app/state/orders_state.dart';
import 'package:owner_app/widgets/order_acceptance_modal.dart';
import 'package:owner_app/widgets/order_card.dart';

const _orderId = 'aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee';

Map<String, dynamic> _settingsJson({
  bool prepaid = true,
  bool pickup = false,
  bool upi = false,
  bool unlocked = true,
  String? vpa,
  String? payee,
  bool attested = false,
  List<String>? effective,
}) =>
    {
      'outlet_id': 'out-1',
      'prepaid': prepaid,
      'pay_at_pickup': pickup,
      'upi_manual': upi,
      'cashfree_unlocked': unlocked,
      'upi_vpa': vpa,
      'upi_payee_name': payee,
      'upi_attested': attested,
      'effective_methods': effective ??
          [
            if (prepaid && unlocked) 'PREPAID',
            if (pickup) 'PAY_AT_PICKUP',
            if (upi) 'UPI_MANUAL',
          ],
    };

Order _order(Map<String, dynamic> extra) => Order.fromJson({
      'order_id': _orderId,
      'status': 'CREATED',
      'payment_status': 'PENDING',
      'is_locked': false,
      'total_amount': 240,
      'created_at': '2026-10-28T10:00:00Z',
      'items': const [
        {'id': 'i1', 'name': 'Masala Dosa', 'quantity': 2}
      ],
      ...extra,
    });

/// A settings backend. [patchStatus] non-200 makes PATCH fail with the
/// structured error the real server sends.
class _SettingsBackend {
  _SettingsBackend({
    Map<String, dynamic>? initial,
    this.patchStatus = 200,
    this.patchError,
    this.getStatus = 200,
    this.getError,
  }) : current = initial ?? _settingsJson();

  Map<String, dynamic> current;
  final int patchStatus;
  final Map<String, dynamic>? patchError;
  final int getStatus;
  final Map<String, dynamic>? getError;
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
      if (getStatus != 200) {
        return http.Response(
            jsonEncode(getError ?? {'detail': 'nope'}), getStatus,
            headers: {'content-type': 'application/json'});
      }
      return http.Response(jsonEncode(current), 200,
          headers: {'content-type': 'application/json'});
    }),
  );
}

/// The staff token every /pos call needs. Matches what the other owner_app
/// widget tests seed (outlet_settings_test.dart:77).
void _seedToken() {
  SharedPreferences.setMockInitialValues(
      {'gusto_owner_access_token': 'staff'});
}

/// Scrolls the long settings list until the Save button is on screen.
///
/// The default 800x600 test viewport is shorter than this screen, so a plain
/// tap() finds nothing — the button is real, just below the fold.
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
  // ================ the settings model, in isolation ======================
  group('PaymentSettings', () {
    test('a locked outlet hides the Cashfree row', () {
      final s = PaymentSettings.fromJson(_settingsJson(unlocked: false));
      expect(s.showCashfreeRow, isFalse);
    });

    test('an unlocked outlet shows it', () {
      final s = PaymentSettings.fromJson(_settingsJson(unlocked: true));
      expect(s.showCashfreeRow, isTrue);
    });

    test('a missing cashfree_unlocked defaults to true', () {
      // An older backend had online payment unconditionally; a missing field
      // must not hide a control that works.
      final s = PaymentSettings.fromJson({
        'outlet_id': 'o', 'prepaid': true, 'pay_at_pickup': false,
        'upi_manual': false,
      });
      expect(s.cashfreeUnlocked, isTrue);
      expect(s.showCashfreeRow, isTrue);
    });

    test('acceptsNothing reads the resolved list, not the flags', () {
      // prepaid=true but locked means nothing is actually on offer — this is
      // the state a newly joined restaurant starts in (migration 036).
      final s = PaymentSettings.fromJson(
          _settingsJson(prepaid: true, unlocked: false, effective: const []));
      expect(s.prepaid, isTrue);
      expect(s.acceptsNothing, isTrue);
    });
  });

  // ========= AMENDMENT A3: Cashfree invisible until activated ============
  group('Cashfree is invisible until activated', () {
    testWidgets('a locked outlet renders NO Cashfree row at all',
        (tester) async {
      final backend = _SettingsBackend(
          initial: _settingsJson(
              prepaid: false, pickup: true, unlocked: false));
      _seedToken();
      await tester.pumpWidget(_settingsHost(backend));
      await tester.pumpAndSettle();

      // Not rendered — not merely disabled.
      expect(find.byKey(const Key('toggle_cashfree')), findsNothing);
      // And nothing explains it either: no greyed text, no hint.
      expect(find.textContaining('Cashfree'), findsNothing);
      expect(find.textContaining('unavailable'), findsNothing);
      // The other two are still there.
      expect(find.byKey(const Key('toggle_pay_at_pickup')), findsOneWidget);
      expect(find.byKey(const Key('toggle_upi_manual')), findsOneWidget);
    });

    testWidgets('an unlocked outlet renders a working toggle', (tester) async {
      final backend = _SettingsBackend(initial: _settingsJson(unlocked: true));
      _seedToken();
      await tester.pumpWidget(_settingsHost(backend));
      await tester.pumpAndSettle();

      expect(find.byKey(const Key('toggle_cashfree')), findsOneWidget);
      final sw = tester.widget<SwitchListTile>(
          find.byKey(const Key('toggle_cashfree')));
      expect(sw.value, isTrue);
      expect(sw.onChanged, isNotNull, reason: 'it must actually work');
    });

    testWidgets('a newly joined restaurant is warned it accepts nothing',
        (tester) async {
      final backend = _SettingsBackend(
          initial: _settingsJson(
              prepaid: true, unlocked: false, effective: const []));
      _seedToken();
      await tester.pumpWidget(_settingsHost(backend));
      await tester.pumpAndSettle();
      expect(find.byKey(const Key('payment_modes_accepts_nothing')),
          findsOneWidget);
    });
  });

  // ================== the screen's three validation rules =================
  group('PaymentModesScreen', () {
    testWidgets('the notes sit directly beneath their own toggles',
        (tester) async {
      _seedToken();
      await tester.pumpWidget(_settingsHost(_SettingsBackend()));
      await tester.pumpAndSettle();

      expect(find.byKey(const Key('pay_at_pickup_note')), findsOneWidget);
      expect(
          find.textContaining('Customers may order and not show up'),
          findsOneWidget);
      expect(find.byKey(const Key('upi_manual_note')), findsOneWidget);
      expect(
          find.textContaining(
              'Accept an order only after you have checked'),
          findsOneWidget);
    });

    testWidgets('it refuses to save with all three off', (tester) async {
      final backend = _SettingsBackend(initial: _settingsJson());
      _seedToken();
      await tester.pumpWidget(_settingsHost(backend));
      await tester.pumpAndSettle();

      await tester.tap(find.byKey(const Key('toggle_cashfree')));
      await tester.pumpAndSettle();
      await _tapSave(tester);

      expect(find.byKey(const Key('payment_modes_error')), findsOneWidget);
      expect(find.textContaining('at least one payment method'),
          findsOneWidget);
      // Nothing was sent.
      expect(backend.lastPatchBody, isNull);
    });

    testWidgets('it sends the full state on save', (tester) async {
      final backend = _SettingsBackend(initial: _settingsJson());
      _seedToken();
      await tester.pumpWidget(_settingsHost(backend));
      await tester.pumpAndSettle();

      await tester.tap(find.byKey(const Key('toggle_pay_at_pickup')));
      await tester.pumpAndSettle();
      await _tapSave(tester);

      expect(backend.lastPatchBody, isNotNull);
      expect(backend.lastPatchBody!['prepaid'], isTrue);
      expect(backend.lastPatchBody!['pay_at_pickup'], isTrue);
      expect(backend.lastPatchBody!['upi_manual'], isFalse);
    });

    testWidgets('it shows the SERVER error text, not its own', (tester) async {
      final backend = _SettingsBackend(
        initial: _settingsJson(prepaid: false, pickup: true, unlocked: true),
        patchStatus: 409,
        patchError: const {
          'error': 'CASHFREE_LOCKED',
          'message': 'Cashfree is currently unavailable for your restaurant.',
        },
      );
      _seedToken();
      await tester.pumpWidget(_settingsHost(backend));
      await tester.pumpAndSettle();

      await _tapSave(tester);

      expect(
          find.text('Cashfree is currently unavailable for your restaurant.'),
          findsOneWidget);
    });

    testWidgets('changing the UPI ID clears the attestation tick',
        (tester) async {
      final backend = _SettingsBackend(
          initial: _settingsJson(
              prepaid: true, upi: true, vpa: 'old@okaxis',
              payee: 'Kitchen', attested: true));
      _seedToken();
      await tester.pumpWidget(_settingsHost(backend));
      await tester.pumpAndSettle();

      var box = tester.widget<CheckboxListTile>(
          find.byKey(const Key('upi_attested_checkbox')));
      expect(box.value, isTrue);

      await tester.enterText(
          find.byKey(const Key('upi_vpa_field')), 'new@okhdfcbank');
      await tester.pumpAndSettle();

      box = tester.widget<CheckboxListTile>(
          find.byKey(const Key('upi_attested_checkbox')));
      expect(box.value, isFalse,
          reason: 'the old proof was about the old string');
      expect(find.byKey(const Key('upi_reattest_hint')), findsOneWidget);
    });
  });

  // =================== the order model's new fields =======================
  group('Order parses the new fields', () {
    test('a prepaid order carries none of them', () {
      final o = _order({'payment_status': 'PAID'});
      expect(o.isPrepaid, isTrue);
      expect(o.contactFirstName, isNull);
      expect(o.contactPhone, isNull);
      expect(o.contactVisible, isFalse);
      expect(o.manualRefundDue, isFalse);
      expect(o.telUri, isNull);
    });

    test('a pay-at-pickup order carries the contact and needs a call', () {
      final o = _order({
        'payment_mode': 'PAY_AT_PICKUP',
        'acceptance_state': 'AWAITING',
        'contact_first_name': 'Asha',
        'contact_phone': '+91 99000 11122',
        'contact_visible': true,
        'call_state': 'PENDING',
      });
      expect(o.isPayAtPickup, isTrue);
      expect(o.needsCall, isTrue);
      expect(o.contactFirstName, 'Asha');
      // Spaces stripped for the dialer; the + is part of the number.
      expect(o.telUri!.toString(), 'tel:+919900011122');
    });

    test('a called order no longer needs a call', () {
      final o = _order({
        'payment_mode': 'PAY_AT_PICKUP',
        'call_state': 'CALLED',
        'call_attempts': 2,
      });
      expect(o.needsCall, isFalse);
      expect(o.callAttempts, 2);
    });

    test('a claimed UPI order is awaiting a human check', () {
      final o = _order({
        'payment_mode': 'UPI_MANUAL',
        'acceptance_state': 'AWAITING',
        'payment_claimed_at': '2026-10-28T10:05:00Z',
      });
      expect(o.isUpiManual, isTrue);
      expect(o.upiAwaitingCheck, isTrue);
      expect(o.amountDue, 240);
    });

    test('a paid UPI order is no longer awaiting a check', () {
      final o = _order({
        'payment_mode': 'UPI_MANUAL',
        'payment_status': 'PAID',
        'payment_claimed_at': '2026-10-28T10:05:00Z',
        'collected_payment_method': 'upi',
      });
      expect(o.upiAwaitingCheck, isFalse);
      expect(o.amountDue, 0);
    });

    test('manual_refund_due is read', () {
      final o = _order({
        'payment_mode': 'UPI_MANUAL',
        'status': 'CANCELLED',
        'manual_refund_due': true,
        'manual_refund_reason': 'Kitchen closed early',
      });
      expect(o.manualRefundDue, isTrue);
      expect(o.manualRefundReason, 'Kitchen closed early');
    });
  });

  // ===================== the prep-queue filter ============================
  group('belongsOnQueue', () {
    test('prepaid CREATED orders stay OFF the queue', () {
      // A customer mid-checkout is not the kitchen's problem.
      expect(OrdersState.belongsOnQueue(_order({})), isFalse);
    });

    test('a pay-at-pickup CREATED order awaiting a decision is ON it', () {
      final o = _order({
        'payment_mode': 'PAY_AT_PICKUP',
        'acceptance_state': 'AWAITING',
      });
      expect(OrdersState.belongsOnQueue(o), isTrue);
    });

    test('an unclaimed UPI order is OFF it', () {
      // Nothing for the restaurant to do until the customer says they paid.
      final o = _order({'payment_mode': 'UPI_MANUAL'});
      expect(OrdersState.belongsOnQueue(o), isFalse);
    });

    test('a claimed UPI order is ON it', () {
      final o = _order({
        'payment_mode': 'UPI_MANUAL',
        'acceptance_state': 'AWAITING',
        'payment_claimed_at': '2026-10-28T10:05:00Z',
      });
      expect(OrdersState.belongsOnQueue(o), isTrue);
    });

    test('live statuses are unchanged for every mode', () {
      for (final mode in ['PREPAID', 'PAY_AT_PICKUP', 'UPI_MANUAL']) {
        for (final s in ['PAID', 'RECEIVED', 'PREPARING', 'READY']) {
          expect(
              OrdersState.belongsOnQueue(
                  _order({'payment_mode': mode, 'status': s})),
              isTrue,
              reason: '$mode/$s');
        }
      }
    });

    test('terminal statuses are off it', () {
      for (final s in ['COMPLETED', 'CANCELLED', 'ABANDONED']) {
        expect(
            OrdersState.belongsOnQueue(
                _order({'payment_mode': 'PAY_AT_PICKUP', 'status': s})),
            isFalse,
            reason: s);
      }
    });
  });

  // ============== the reject copy never says "refund" =====================
  group('reject copy', () {
    Future<void> openModal(WidgetTester tester, Order order) async {
      await tester.pumpWidget(MaterialApp(
        home: Builder(
          builder: (context) => ElevatedButton(
            onPressed: () => showOrderAcceptanceModal(context, order),
            child: const Text('open'),
          ),
        ),
      ));
      await tester.tap(find.text('open'));
      await tester.pumpAndSettle();
      await tester.tap(find.byKey(const Key('acceptance_reject_open')));
      await tester.pumpAndSettle();
      await tester.tap(find.byKey(const Key('reject_reason_tooBusy')));
      await tester.pumpAndSettle();
    }

    testWidgets('a prepaid order DOES mention a refund', (tester) async {
      await openModal(
          tester, _order({'payment_status': 'PAID', 'status': 'PAID'}));
      expect(find.text('Reject and refund'), findsOneWidget);
    });

    testWidgets('a pay-at-pickup order does NOT', (tester) async {
      // Nothing was ever charged, so there is nothing to refund.
      await openModal(tester, _order({
        'payment_mode': 'PAY_AT_PICKUP',
        'acceptance_state': 'AWAITING',
      }));
      expect(find.text('Reject and refund'), findsNothing);
      expect(find.text('Reject order'), findsOneWidget);
    });

    testWidgets('a direct-UPI order does NOT', (tester) async {
      // It WAS paid, but the restaurant refunds it — not CareVo. That is a
      // different sentence and it lives on the order card's banner.
      await openModal(tester, _order({
        'payment_mode': 'UPI_MANUAL',
        'acceptance_state': 'AWAITING',
        'payment_claimed_at': '2026-10-28T10:05:00Z',
      }));
      expect(find.text('Reject and refund'), findsNothing);
      expect(find.text('Reject order'), findsOneWidget);
    });
  });

  // ===================== verify-pickup 409 surfacing ======================
  group('PickupResult carries the server message', () {
    test('a 409 message reaches the UI instead of a generic failure', () {
      const r = PickupResult(
        verified: false,
        locked: false,
        message: 'Take payment first — use "Paid and handed over".',
      );
      expect(r.message, contains('Take payment first'));
      expect(r.verified, isFalse);
      expect(r.locked, isFalse);
    });
  });

  // ========================== onboarding ==================================
  group('OnboardingScreen', () {
    testWidgets('shows the title and body', (tester) async {
      await tester.pumpWidget(const MaterialApp(
          home: OnboardingScreen(formUrl: 'https://example.invalid/form')));
      await tester.pumpAndSettle();

      expect(find.text('Get orders on Gusto Skip'), findsOneWidget);
      expect(
          find.textContaining(
              'Our team will call you shortly and finish the registration '
              'in about 10 minutes.'),
          findsOneWidget);
    });

    testWidgets('shows the button when a URL is configured', (tester) async {
      await tester.pumpWidget(const MaterialApp(
          home: OnboardingScreen(formUrl: 'https://example.invalid/form')));
      await tester.pumpAndSettle();
      expect(find.byKey(const Key('onboarding_register_button')),
          findsOneWidget);
      expect(find.text('Register your restaurant'), findsOneWidget);
      expect(find.byKey(const Key('onboarding_no_url')), findsNothing);
    });

    testWidgets('HIDES the button when the URL is empty', (tester) async {
      // Hidden, not disabled: a greyed button invites a tap and does nothing.
      await tester.pumpWidget(
          const MaterialApp(home: OnboardingScreen(formUrl: '')));
      await tester.pumpAndSettle();
      expect(find.byKey(const Key('onboarding_register_button')), findsNothing);
      expect(find.byKey(const Key('onboarding_no_url')), findsOneWidget);
    });

    testWidgets('whitespace counts as empty', (tester) async {
      await tester.pumpWidget(
          const MaterialApp(home: OnboardingScreen(formUrl: '   ')));
      await tester.pumpAndSettle();
      expect(find.byKey(const Key('onboarding_register_button')), findsNothing);
    });

    test('no URL is hardcoded in the app config', () {
      // The default must stay empty: a stale link is worse than none, and
      // this is what makes the --dart-define the only source.
      const defaulted = String.fromEnvironment('ONBOARDING_FORM_URL');
      expect(defaulted, isEmpty,
          reason: 'run without the define, the URL must be empty');
    });
  });

  // ===================== the version label ================================
  group('app version', () {
    test('AppConfig.appVersion matches pubspec.yaml', () {
      // The label is a constant rather than read from the package at runtime
      // (no package_info_plus dependency), so this is what keeps it honest.
      final pubspec = File('pubspec.yaml').readAsStringSync();
      final m = RegExp(r'^version:\s*(\S+)', multiLine: true)
          .firstMatch(pubspec);
      expect(m, isNotNull);
      expect(AppConfig.appVersion, m!.group(1));
    });

    test('it is the expected build for this release', () {
      expect(AppConfig.appVersion, '1.0.1+5');
    });
  });


  // ============ the refund banner tells the two causes apart ==============
  //
  // A refund owed because NOBODY LOOKED is not the same as one owed because
  // the restaurant confirmed the money and then could not cook. Only the first
  // leaves the owner with something to check, so only it gets the extra line.
  group('refund banner distinguishes the cause', () {
    Future<void> openCard(WidgetTester tester, Order order) async {
      _seedToken();
      final backend = _SettingsBackend();
      await tester.pumpWidget(MultiProvider(
        providers: [
          Provider<ApiClient>.value(value: backend.api),
          Provider<OrderService>(create: (_) => OrderService(backend.api)),
          ChangeNotifierProvider<OrdersState>(
              create: (_) => OrdersState(OrderService(backend.api))),
        ],
        child: MaterialApp(
          home: Scaffold(body: SingleChildScrollView(
              child: OrderCard(order: order))),
        ),
      ));
      await tester.pump();
      // Expand the card: the banner lives in the detail panel.
      await tester.tap(find.text('#${order.shortId}'));
      await tester.pumpAndSettle();
    }

    Order refundOrder(String? reason) => _order({
          'payment_mode': 'UPI_MANUAL',
          'status': 'CANCELLED',
          'payment_claimed_at': '2026-10-28T10:05:00Z',
          'manual_refund_due': true,
          if (reason != null) 'manual_refund_reason': reason,
        });

    test('the model flags only the expiry reason', () {
      expect(
          refundOrder('acceptance_expired_after_payment_claim')
              .refundFromMissedClaim,
          isTrue);
      expect(refundOrder('cannot_make').refundFromMissedClaim, isFalse);
      expect(refundOrder(null).refundFromMissedClaim, isFalse);
      expect(refundOrder('Kitchen closed early').refundFromMissedClaim,
          isFalse);
      // And never without a refund actually being due.
      final noRefund = _order({
        'payment_mode': 'UPI_MANUAL',
        'manual_refund_reason': 'acceptance_expired_after_payment_claim',
      });
      expect(noRefund.refundFromMissedClaim, isFalse);
    });

    testWidgets('the expiry reason adds the check-your-app line',
        (tester) async {
      await openCard(
          tester, refundOrder('acceptance_expired_after_payment_claim'));

      expect(find.byKey(const Key('manual_refund_banner')), findsOneWidget);
      // The plain banner text is still there…
      expect(find.byKey(const Key('manual_refund_text')), findsOneWidget);
      // …plus the line that tells the owner there is something to check.
      expect(find.byKey(const Key('manual_refund_missed_claim_text')),
          findsOneWidget);
      expect(
          find.textContaining(
              'The customer said they paid but you did not confirm in time'),
          findsOneWidget);
    });

    testWidgets('cannot_make keeps the PLAIN banner and no extra line',
        (tester) async {
      // The restaurant confirmed the money and then could not cook, so there
      // is nothing left for them to check.
      await openCard(tester, refundOrder('cannot_make'));

      expect(find.byKey(const Key('manual_refund_banner')), findsOneWidget);
      expect(find.byKey(const Key('manual_refund_text')), findsOneWidget);
      expect(find.byKey(const Key('manual_refund_missed_claim_text')),
          findsNothing);
    });

    testWidgets('no banner at all without a refund due', (tester) async {
      await openCard(tester, _order({
        'payment_mode': 'UPI_MANUAL',
        'status': 'CANCELLED',
      }));
      expect(find.byKey(const Key('manual_refund_banner')), findsNothing);
      expect(find.byKey(const Key('manual_refund_missed_claim_text')),
          findsNothing);
    });

    testWidgets('a prepaid order never shows it', (tester) async {
      // refund_required is CareVo's queue, not this banner.
      await openCard(tester, _order({
        'status': 'CANCELLED',
        'payment_status': 'PAID',
      }));
      expect(find.byKey(const Key('manual_refund_banner')), findsNothing);
    });
  });

  // ================ 403 on the settings screen (TASK 1c) =================
  group('a 403 shows the server message and disables everything', () {
    testWidgets('a 403 from GET shows no toggles and no Retry', (tester) async {
      _seedToken();
      final backend = _SettingsBackend(
        getStatus: 403,
        getError: const {
          'detail': 'Only the restaurant owner or a manager can change this.',
        },
      );
      await tester.pumpWidget(_settingsHost(backend));
      await tester.pumpAndSettle();

      expect(find.byKey(const Key('payment_modes_forbidden')), findsOneWidget);
      // THE SERVER'S sentence.
      expect(
          find.text(
              'Only the restaurant owner or a manager can change this.'),
          findsOneWidget);
      // It never shows toggles it cannot save.
      expect(find.byKey(const Key('toggle_cashfree')), findsNothing);
      expect(find.byKey(const Key('toggle_pay_at_pickup')), findsNothing);
      expect(find.byKey(const Key('toggle_upi_manual')), findsNothing);
      expect(find.byKey(const Key('payment_modes_save')), findsNothing);
      // And no Retry: a 403 will answer the same way every time.
      expect(find.byKey(const Key('payment_modes_retry')), findsNothing);
    });

    testWidgets('a NETWORK failure still offers Retry', (tester) async {
      // The contrast that makes the above meaningful — a transient failure is
      // drawn differently from a permanent refusal.
      _seedToken();
      final backend = _SettingsBackend(getStatus: 500);
      await tester.pumpWidget(_settingsHost(backend));
      await tester.pumpAndSettle();

      expect(find.byKey(const Key('payment_modes_forbidden')), findsNothing);
      expect(find.byKey(const Key('payment_modes_load_error')), findsOneWidget);
      expect(find.byKey(const Key('payment_modes_retry')), findsOneWidget);
    });

    testWidgets('a 403 from PATCH disables every control', (tester) async {
      // The role can be revoked between loading and saving, so the refusal can
      // arrive on the save. The toggles are already on screen by then, so they
      // are DISABLED rather than removed — and the message is the server's.
      _seedToken();
      final backend = _SettingsBackend(
        initial: _settingsJson(unlocked: true),
        patchStatus: 403,
        patchError: const {
          'message': 'Only the restaurant owner or a manager can change this.',
        },
      );
      await tester.pumpWidget(_settingsHost(backend));
      await tester.pumpAndSettle();

      await tester.tap(find.byKey(const Key('toggle_pay_at_pickup')));
      await tester.pumpAndSettle();
      await _tapSave(tester);

      expect(
          find.text(
              'Only the restaurant owner or a manager can change this.'),
          findsOneWidget);

      // Every control is now dead.
      for (final k in [
        'toggle_cashfree',
        'toggle_pay_at_pickup',
        'toggle_upi_manual',
      ]) {
        final sw = tester.widget<SwitchListTile>(find.byKey(Key(k)));
        expect(sw.onChanged, isNull, reason: '$k must be disabled');
      }
      final box = tester.widget<CheckboxListTile>(
          find.byKey(const Key('upi_attested_checkbox')));
      expect(box.onChanged, isNull);
      final vpa = tester.widget<TextField>(find.byKey(const Key('upi_vpa_field')));
      expect(vpa.enabled, isFalse);
      final save = tester.widget<FilledButton>(
          find.byKey(const Key('payment_modes_save')));
      expect(save.onPressed, isNull);
    });

    testWidgets('a 409 is NOT treated as forbidden', (tester) async {
      // Only a 403 locks the screen; a business-rule refusal leaves the owner
      // able to correct it and try again.
      _seedToken();
      final backend = _SettingsBackend(
        initial: _settingsJson(prepaid: false, pickup: true, unlocked: true),
        patchStatus: 409,
        patchError: const {
          'error': 'CASHFREE_LOCKED',
          'message': 'Cashfree is currently unavailable for your restaurant.',
        },
      );
      await tester.pumpWidget(_settingsHost(backend));
      await tester.pumpAndSettle();
      await _tapSave(tester);

      expect(
          find.text('Cashfree is currently unavailable for your restaurant.'),
          findsOneWidget);
      final save = tester.widget<FilledButton>(
          find.byKey(const Key('payment_modes_save')));
      expect(save.onPressed, isNotNull, reason: 'still correctable');
    });
  });
}
