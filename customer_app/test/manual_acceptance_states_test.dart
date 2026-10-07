// Customer-facing states for manual order acceptance (backend migration 032).
//
// THE LOAD-BEARING TEST IS THE LAST GROUP: "auto outlets are untouched".
// Everything in this feature is gated on `acceptance_state` being PRESENT on
// the order payload, and it is null for every order at an outlet on automatic
// acceptance — which is every outlet until one opts in. If a future change
// starts keying off a STATUS instead, the auto-mode group fails, because an
// awaiting order's status is `PAID` exactly like an auto order's.
//
// Why gate on the field and not the status: `PAID` means "the money arrived".
// It says nothing about whether a human agreed to cook, and at an auto outlet
// those two facts are deliberately fused. Only the presence of
// acceptance_state separates them.
import 'dart:convert';

import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:http/http.dart' as http;
import 'package:http/testing.dart';
import 'package:provider/provider.dart';
import 'package:shared_preferences/shared_preferences.dart';

import 'package:customer_app/models/order.dart';
import 'package:customer_app/screens/pickup_screen.dart';
import 'package:customer_app/services/api_client.dart';
import 'package:customer_app/services/cashfree_service.dart';
import 'package:customer_app/services/location_service.dart';
import 'package:customer_app/services/order_service.dart';
import 'package:customer_app/state/cart_state.dart';
import 'package:customer_app/theme/app_theme.dart';
import 'package:customer_app/theme/theme_provider.dart';

const String _orderId = '11111111-2222-3333-4444-555555555555';
const String _code = '234567';

class _NoCashfree implements CashfreeService {
  @override
  Future<CheckoutResult> openCheckout({
    required String orderId,
    required String paymentSessionId,
  }) async =>
      const CheckoutResult(CheckoutOutcome.notStarted);
}

/// A backend for one order. [acceptanceState] of null models an AUTO outlet,
/// which is the default everywhere.
ApiClient _api({
  String status = 'PAID',
  String? acceptanceState,
  bool refundRequired = false,
  String? pickupCode = _code,
}) {
  return ApiClient(
    client: MockClient((req) async {
      if (req.method == 'POST') {
        return http.Response(jsonEncode({'ok': true}), 200,
            headers: {'content-type': 'application/json'});
      }
      final paid = const {'PAID', 'RECEIVED', 'PREPARING', 'READY', 'COMPLETED'}
          .contains(status);
      return http.Response(
        jsonEncode({
          'id': _orderId,
          'status': status,
          'payment_status': paid ? 'PAID' : 'PENDING',
          'pickup_code': paid ? pickupCode : null,
          'total_amount': 240,
          // Absent entirely when null, mirroring an auto-mode response and an
          // older backend that has never heard of the field.
          if (acceptanceState != null) 'acceptance_state': acceptanceState,
          'refund_required': refundRequired,
          'items': [
            {'name': 'Masala Dosa', 'quantity': 2}
          ],
        }),
        200,
        headers: {'content-type': 'application/json'},
      );
    }),
  );
}

Widget _host(ApiClient api, {String? outletName}) {
  return MultiProvider(
    providers: [
      Provider<ApiClient>.value(value: api),
      Provider<OrderService>(create: (_) => OrderService(api)),
      Provider<CashfreeService>(create: (_) => _NoCashfree()),
      Provider<LocationService>(create: (_) => LocationService()),
      ChangeNotifierProvider<CartState>(create: (_) => CartState()),
      ChangeNotifierProvider<ThemeProvider>(create: (_) => ThemeProvider()),
    ],
    child: MaterialApp(
      theme: AppTheme.light(),
      home: PickupScreen(orderId: _orderId, outletName: outletName),
    ),
  );
}

Future<void> _open(WidgetTester tester, Widget w) async {
  SharedPreferences.setMockInitialValues({'carevo_access_token': 't'});
  await tester.pumpWidget(w);
  await tester.pump();
  await tester.pump();
}

Future<void> _close(WidgetTester tester) async {
  await tester.pumpWidget(const SizedBox.shrink());
  await tester.pumpAndSettle();
}

void main() {
  // ======================= the model, in isolation =========================
  group('OrderStatus gates on the field, not the status', () {
    test('an auto-mode order requires no confirmation', () {
      final o = OrderStatus.fromJson({
        'id': _orderId, 'status': 'PAID', 'payment_status': 'PAID',
        'total_amount': 100, 'items': const [],
      });
      expect(o.requiresConfirmation, isFalse);
      expect(o.isAwaitingConfirmation, isFalse);
      expect(o.isConfirmed, isFalse);
      expect(o.isConfirmationExpired, isFalse);
      expect(o.pickupCodeHidden, isFalse);
      expect(o.refundRequired, isFalse);
    });

    test('AWAITING is distinguished despite the status being PAID', () {
      final o = OrderStatus.fromJson({
        'id': _orderId, 'status': 'PAID', 'payment_status': 'PAID',
        'acceptance_state': 'AWAITING', 'total_amount': 100, 'items': const [],
      });
      // The crux: identical status to the auto order above.
      expect(o.status, 'PAID');
      expect(o.requiresConfirmation, isTrue);
      expect(o.isAwaitingConfirmation, isTrue);
      expect(o.pickupCodeHidden, isTrue);
    });

    test('ACCEPTED is confirmed and no longer hides the code', () {
      final o = OrderStatus.fromJson({
        'id': _orderId, 'status': 'RECEIVED', 'payment_status': 'PAID',
        'acceptance_state': 'ACCEPTED', 'total_amount': 100, 'items': const [],
      });
      expect(o.isConfirmed, isTrue);
      expect(o.isAwaitingConfirmation, isFalse);
      expect(o.pickupCodeHidden, isFalse);
    });

    test('EXPIRED is reported, and separately from REJECTED', () {
      final expired = OrderStatus.fromJson({
        'id': _orderId, 'status': 'CANCELLED', 'payment_status': 'PAID',
        'acceptance_state': 'EXPIRED', 'refund_required': true,
        'total_amount': 100, 'items': const [],
      });
      expect(expired.isConfirmationExpired, isTrue);
      expect(expired.refundRequired, isTrue);

      final rejected = OrderStatus.fromJson({
        'id': _orderId, 'status': 'CANCELLED', 'payment_status': 'PAID',
        'acceptance_state': 'REJECTED', 'refund_required': true,
        'total_amount': 100, 'items': const [],
      });
      expect(rejected.isConfirmationExpired, isFalse,
          reason: 'a rejection is not an expiry');
      expect(rejected.refundRequired, isTrue);
    });

    test('an empty string is not a confirmation requirement', () {
      final o = OrderStatus.fromJson({
        'id': _orderId, 'status': 'PAID', 'payment_status': 'PAID',
        'acceptance_state': '', 'total_amount': 100, 'items': const [],
      });
      expect(o.requiresConfirmation, isFalse);
    });
  });

  // ============================== AWAITING =================================
  group('AWAITING', () {
    testWidgets('names the restaurant it is waiting for', (tester) async {
      await _open(tester,
          _host(_api(acceptanceState: 'AWAITING'), outletName: 'Dosa Corner'));
      expect(find.textContaining('Waiting for Dosa Corner to confirm'),
          findsOneWidget);
      await _close(tester);
    });

    testWidgets('falls back to "the restaurant" with no name', (tester) async {
      await _open(tester, _host(_api(acceptanceState: 'AWAITING')));
      expect(find.textContaining('Waiting for the restaurant to confirm'),
          findsOneWidget);
      await _close(tester);
    });

    testWidgets('HIDES the pickup code even though the server sent one',
        (tester) async {
      // The server allocates the code at payment, so it IS in the payload.
      // Showing it would invite the customer to walk to a restaurant that has
      // not agreed to make the food.
      await _open(tester, _host(_api(acceptanceState: 'AWAITING')));

      expect(find.text(_code), findsNothing,
          reason: 'the pickup code was shown before confirmation');
      expect(find.text(kCodeHiddenUntilConfirmed), findsOneWidget);
      expect(find.byKey(const Key('pickup_code_hidden_awaiting')),
          findsOneWidget);
      await _close(tester);
    });

    testWidgets('does not claim the order is confirmed', (tester) async {
      await _open(tester, _host(_api(acceptanceState: 'AWAITING')));
      expect(find.textContaining('Order\nconfirmed.'), findsNothing);
      expect(find.textContaining('Just a\nmoment.'), findsOneWidget);
      await _close(tester);
    });

    testWidgets('does not tell them to show a code at the counter',
        (tester) async {
      await _open(tester, _host(_api(acceptanceState: 'AWAITING')));
      expect(find.textContaining('Show or say your pickup code'), findsNothing);
      await _close(tester);
    });

    testWidgets('says the PAYMENT succeeded — only confirmation is pending',
        (tester) async {
      await _open(tester, _host(_api(acceptanceState: 'AWAITING')));
      expect(find.textContaining('Your payment went through'), findsOneWidget);
      // And must NOT reuse the pre-payment copy, which would be a lie here.
      expect(find.textContaining('will confirm your payment shortly'),
          findsNothing);
      await _close(tester);
    });
  });

  // ============================== ACCEPTED =================================
  group('ACCEPTED is the ordinary screen', () {
    testWidgets('shows the code and the usual instruction', (tester) async {
      await _open(tester,
          _host(_api(status: 'RECEIVED', acceptanceState: 'ACCEPTED')));
      expect(find.text(_code), findsOneWidget);
      expect(find.textContaining('Show or say your pickup code'),
          findsOneWidget);
      expect(find.text(kCodeHiddenUntilConfirmed), findsNothing);
      await _close(tester);
    });

    testWidgets('renders the same as an auto order at the same status',
        (tester) async {
      await _open(tester,
          _host(_api(status: 'RECEIVED', acceptanceState: 'ACCEPTED')));
      final manual = find.textContaining('Order\nconfirmed.').evaluate().length;
      await _close(tester);

      await _open(tester, _host(_api(status: 'RECEIVED')));
      final auto = find.textContaining('Order\nconfirmed.').evaluate().length;
      await _close(tester);

      expect(manual, auto,
          reason: 'a confirmed manual order should look like an auto order');
    });
  });

  // ================== CANCELLED with a refund outstanding ==================
  group('CANCELLED with refund_required', () {
    testWidgets('uses the single approval-pending copy constant',
        (tester) async {
      await _open(tester, _host(_api(
        status: 'CANCELLED', acceptanceState: 'EXPIRED',
        refundRequired: true, pickupCode: null,
      )));
      expect(find.text(kRefundCopyTodo), findsOneWidget);
      await _close(tester);
    });

    test('the constant is still an unapproved placeholder', () {
      // Deliberately asserted. This copy commits the restaurant to returning
      // money the app never sees move, and shipping a placeholder would be
      // worse than shipping nothing. When the real wording is approved, this
      // expectation is the thing that tells you to delete it.
      expect(kRefundCopyTodo, startsWith('REFUND_COPY_TODO:'),
          reason: 'if the copy has been approved, update this test too');
      expect(kRefundCopyTodo.toLowerCase(), isNot(contains('within')),
          reason: 'the copy must not promise a refund timeline');
      expect(kRefundCopyTodo.toLowerCase(), isNot(contains('hours')));
      expect(kRefundCopyTodo.toLowerCase(), isNot(contains('days')));
    });

    testWidgets('says cancelled, not ready', (tester) async {
      await _open(tester, _host(_api(
        status: 'CANCELLED', acceptanceState: 'EXPIRED',
        refundRequired: true, pickupCode: null,
      )));
      expect(find.textContaining('Order\ncancelled.'), findsOneWidget);
      expect(find.textContaining('Ready to\ncollect!'), findsNothing);
      await _close(tester);
    });

    testWidgets('a REJECTED order shows the refund copy too', (tester) async {
      // From the customer's side being turned down and being ignored are the
      // same event, so the copy does not labour the difference.
      await _open(tester, _host(_api(
        status: 'CANCELLED', acceptanceState: 'REJECTED',
        refundRequired: true, pickupCode: null,
      )));
      expect(find.text(kRefundCopyTodo), findsOneWidget);
      await _close(tester);
    });

    testWidgets('an AUTO order rejected by staff also shows it',
        (tester) async {
      // refund_required is not manual-mode-only: an auto-mode reject of a paid
      // order flags it as well, and the customer deserves the same message.
      await _open(tester, _host(_api(
        status: 'CANCELLED', refundRequired: true, pickupCode: null,
      )));
      expect(find.text(kRefundCopyTodo), findsOneWidget);
      await _close(tester);
    });
  });

  // ================ THE REGRESSION GUARD: auto is untouched ================
  group('auto outlets are untouched', () {
    testWidgets('a PAID auto order reads "Order confirmed" and shows the code',
        (tester) async {
      await _open(tester, _host(_api(status: 'PAID')));

      expect(find.textContaining('Order\nconfirmed.'), findsOneWidget);
      expect(find.text(_code), findsOneWidget);
      expect(find.textContaining('Show or say your pickup code'),
          findsOneWidget);

      // None of the new states may appear.
      expect(find.textContaining('Waiting for'), findsNothing);
      expect(find.text(kCodeHiddenUntilConfirmed), findsNothing);
      expect(find.text(kRefundCopyTodo), findsNothing);
      expect(find.textContaining('Just a\nmoment.'), findsNothing);
      await _close(tester);
    });

    testWidgets('a READY auto order still says ready', (tester) async {
      await _open(tester, _host(_api(status: 'READY')));
      expect(find.textContaining('Ready to\ncollect!'), findsOneWidget);
      expect(find.text(_code), findsOneWidget);
      await _close(tester);
    });

    testWidgets('a COMPLETED auto order still says collected', (tester) async {
      await _open(tester, _host(_api(status: 'COMPLETED')));
      expect(find.textContaining('Enjoy your\nfood!'), findsOneWidget);
      await _close(tester);
    });

    testWidgets('an unpaid auto order still says almost there', (tester) async {
      await _open(tester, _host(_api(status: 'CREATED', pickupCode: null)));
      expect(find.textContaining('Almost\nthere.'), findsOneWidget);
      // The PRE-payment placeholder, not the awaiting-confirmation one.
      expect(find.text('Appears after payment'), findsOneWidget);
      expect(find.text(kCodeHiddenUntilConfirmed), findsNothing);
      await _close(tester);
    });

    testWidgets('a payload with no acceptance_state key at all is fine',
        (tester) async {
      // An older backend, or any auto outlet. The field is absent rather than
      // null, which is the case a required-field parse would crash on.
      await _open(tester, _host(_api(status: 'PAID')));
      expect(find.text(_code), findsOneWidget);
      await _close(tester);
    });
  });
}
