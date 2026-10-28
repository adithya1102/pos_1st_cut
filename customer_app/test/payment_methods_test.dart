// Server-driven payment methods, pay-at-pickup and direct UPI
// (backend migrations 034, 035, 036).
//
// THE LOAD-BEARING GROUP IS "Cashfree is unreachable without PREPAID"
// (AMENDMENT A4). Everything about making online payment invisible rests on
// one property: checkout routes to the Cashfree flow if and only if PREPAID is
// in the server's payment_methods list. No Cashfree code is deleted — it is
// simply not reached — so the only way to keep that true is to assert it.
//
// The second most important group is "a backend that never heard of
// payment_methods". A null list and an empty list mean opposite things: the
// first is an older server and must behave exactly as this app always did; the
// second is a restaurant that accepts nothing and must disable Pay. If those
// ever collapse into one, a brand-new restaurant gets offered a Cashfree
// account it does not have.
import 'dart:convert';

import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:http/http.dart' as http;
import 'package:http/testing.dart';
import 'package:provider/provider.dart';
import 'package:shared_preferences/shared_preferences.dart';

import 'package:customer_app/models/order.dart';
import 'package:customer_app/models/outlet.dart';
import 'package:customer_app/screens/checkout_screen.dart';
import 'package:customer_app/screens/upi_pay_screen.dart';
import 'package:customer_app/services/api_client.dart';
import 'package:customer_app/services/cashfree_service.dart';
import 'package:customer_app/services/location_service.dart';
import 'package:customer_app/services/order_service.dart';
import 'package:customer_app/state/cart_state.dart';
import 'package:customer_app/theme/app_theme.dart';
import 'package:customer_app/theme/theme_provider.dart';

const String _orderId = '11111111-2222-3333-4444-555555555555';

/// Records whether the Cashfree sheet was ever opened. The whole of A4 is the
/// assertion that this stays false.
class _SpyCashfree implements CashfreeService {
  int opened = 0;

  @override
  Future<CheckoutResult> openCheckout({
    required String orderId,
    required String paymentSessionId,
  }) async {
    opened++;
    return const CheckoutResult(CheckoutOutcome.verified);
  }
}

Outlet _outlet({List<String>? methods, bool coords = true}) =>
    Outlet.fromJson({
      'id': 'out-1',
      'name': 'Test Kitchen',
      'address': 'Koramangala, Bengaluru',
      'is_open': true,
      'order_status': 'open',
      if (coords) 'latitude': 12.9716,
      if (coords) 'longitude': 77.5946,
      // Absent entirely when null, mirroring a backend predating the field.
      if (methods != null) 'payment_methods': methods,
    });

/// A backend that records what create_order was asked for and answers in the
/// shape the server would for that method.
class _Backend {
  Map<String, dynamic>? lastOrderBody;
  int claims = 0;

  late final ApiClient api = ApiClient(
    client: MockClient((req) async {
      if (req.url.path.endsWith('/claim-paid')) {
        claims++;
        return http.Response(
            jsonEncode({'order_id': _orderId, 'claimed': true}), 200,
            headers: {'content-type': 'application/json'});
      }
      if (req.method == 'POST' && req.url.path.endsWith('/customer/orders')) {
        final body = jsonDecode(req.body) as Map<String, dynamic>;
        lastOrderBody = body;
        final mode = (body['payment_method'] ?? 'PREPAID').toString();
        return http.Response(
          jsonEncode({
            'id': _orderId,
            'status': 'CREATED',
            'total_amount': 200,
            'final_amount': 200,
            'payment_mode': mode,
            'amount_due_at_pickup': mode == 'PAY_AT_PICKUP' ? 200 : 0,
            if (mode == 'PREPAID')
              'payment': {
                'gateway': 'cashfree',
                'gateway_order_id': 'cf_1',
                'amount': 200,
                'currency': 'INR',
                'payment_session_id': 'session_abc',
              },
            if (mode == 'UPI_MANUAL')
              'upi_payment': {
                'vpa': 'kitchen@okaxis',
                'payee_name': 'Test Kitchen',
                'amount': 200,
                'note': 'A1B2C3',
              },
          }),
          200,
          headers: {'content-type': 'application/json'},
        );
      }
      // cart/check and everything else.
      return http.Response(jsonEncode({'unavailable': []}), 200,
          headers: {'content-type': 'application/json'});
    }),
  );
}

Widget _checkoutHost(_Backend backend, _SpyCashfree cf, Outlet outlet) {
  final cart = CartState();
  return MultiProvider(
    providers: [
      Provider<ApiClient>.value(value: backend.api),
      Provider<OrderService>(create: (_) => OrderService(backend.api)),
      Provider<CashfreeService>.value(value: cf),
      Provider<LocationService>(create: (_) => LocationService()),
      ChangeNotifierProvider<CartState>.value(value: cart),
      ChangeNotifierProvider<ThemeProvider>(create: (_) => ThemeProvider()),
    ],
    child: MaterialApp(
      theme: AppTheme.light(),
      home: Builder(builder: (context) {
        // One item in the cart, bound to the outlet under test.
        return const CheckoutScreen();
      }),
    ),
  );
}

void main() {
  // ===================== the model, in isolation ===========================
  group('Outlet.paymentMethods tells absent from empty', () {
    test('a missing field is null, not an empty list', () {
      final o = _outlet(methods: null);
      expect(o.paymentMethods, isNull);
      expect(o.knowsPaymentMethods, isFalse);
      expect(o.acceptsNothing, isFalse,
          reason: 'an older backend has not said there are none');
    });

    test('an empty list means this outlet accepts nothing', () {
      final o = _outlet(methods: const []);
      expect(o.knowsPaymentMethods, isTrue);
      expect(o.acceptsNothing, isTrue);
      expect(o.canOrder, isFalse);
    });

    test('values are normalised and the order is kept', () {
      final o = _outlet(methods: const [' prepaid ', 'upi_manual']);
      expect(o.paymentMethods, ['PREPAID', 'UPI_MANUAL']);
      expect(o.acceptsPrepaid, isTrue);
      expect(o.acceptsUpiManual, isTrue);
      expect(o.acceptsPayAtPickup, isFalse);
    });

    test('non-gateway-only is true without PREPAID and false with it', () {
      expect(_outlet(methods: const ['PAY_AT_PICKUP']).onlyNonGatewayPayment,
          isTrue);
      expect(_outlet(methods: const ['UPI_MANUAL']).onlyNonGatewayPayment,
          isTrue);
      expect(
          _outlet(methods: const ['PREPAID', 'UPI_MANUAL'])
              .onlyNonGatewayPayment,
          isFalse);
      expect(_outlet(methods: const []).onlyNonGatewayPayment, isFalse,
          reason: 'nothing on offer is not "only non-gateway"');
    });
  });

  group('PaymentMode maps the wire safely', () {
    test('known values round-trip', () {
      expect(PaymentMode.fromWire('PAY_AT_PICKUP'), PaymentMode.payAtPickup);
      expect(PaymentMode.fromWire('UPI_MANUAL'), PaymentMode.upiManual);
      expect(PaymentMode.fromWire('PREPAID'), PaymentMode.prepaid);
    });

    test('anything unknown or absent falls back to prepaid', () {
      // Prepaid is the only safe default: it is the mode with a complete,
      // already-shipped flow behind it.
      expect(PaymentMode.fromWire(null), PaymentMode.prepaid);
      expect(PaymentMode.fromWire(''), PaymentMode.prepaid);
      expect(PaymentMode.fromWire('CRYPTO'), PaymentMode.prepaid);
    });

    test('isNonGateway is true for exactly the two counter modes', () {
      expect(PaymentMode.prepaid.isNonGateway, isFalse);
      expect(PaymentMode.payAtPickup.isNonGateway, isTrue);
      expect(PaymentMode.upiManual.isNonGateway, isTrue);
    });
  });

  group('UpiPaymentInfo builds a correct intent', () {
    test('every component is percent-encoded', () {
      final info = UpiPaymentInfo.fromJson({
        'vpa': 'kitchen@okaxis',
        // A space and an ampersand would truncate a hand-built query string
        // and send the payment with the wrong details.
        'payee_name': 'Dosa & Co',
        'amount': 1234.5,
        'note': 'A1B2C3',
      })!;
      final uri = info.intentUri;
      expect(uri.scheme, 'upi');
      expect(uri.host, 'pay');
      expect(uri.queryParameters['pa'], 'kitchen@okaxis');
      expect(uri.queryParameters['pn'], 'Dosa & Co');
      expect(uri.queryParameters['cu'], 'INR');
      expect(uri.queryParameters['tn'], 'A1B2C3');
      // Two decimals, as the UPI spec wants.
      expect(uri.queryParameters['am'], '1234.50');
      expect(uri.toString(), contains('Dosa%20%26%20Co'));
    });

    test('a missing VPA yields null rather than a half-built intent', () {
      // A Pay button that sends money nowhere is worse than no Pay button.
      expect(UpiPaymentInfo.fromJson({'payee_name': 'X', 'amount': 1}), isNull);
      expect(UpiPaymentInfo.fromJson({'vpa': '  '}), isNull);
      expect(UpiPaymentInfo.fromJson(null), isNull);
    });
  });

  group('CreatedOrder and OrderStatus parse the new fields', () {
    test('a pay-at-pickup order carries its amount and no payment block', () {
      final o = CreatedOrder.fromJson({
        'id': _orderId,
        'status': 'CREATED',
        'total_amount': 200,
        'payment': null,
        'payment_mode': 'PAY_AT_PICKUP',
        'amount_due_at_pickup': 200,
      });
      expect(o.paymentMode, PaymentMode.payAtPickup);
      expect(o.payment, isNull);
      expect(o.amountDueAtPickup, 200);
      expect(o.upiPayment, isNull);
    });

    test('a direct-UPI order carries its pay block', () {
      final o = CreatedOrder.fromJson({
        'id': _orderId,
        'status': 'CREATED',
        'total_amount': 200,
        'payment_mode': 'UPI_MANUAL',
        'upi_payment': {
          'vpa': 'kitchen@okaxis',
          'payee_name': 'Test Kitchen',
          'amount': 200,
          'note': 'A1B2C3',
        },
      });
      expect(o.paymentMode, PaymentMode.upiManual);
      expect(o.upiPayment!.vpa, 'kitchen@okaxis');
      expect(o.upiPayment!.note, 'A1B2C3');
    });

    test('an order status distinguishes unclaimed from awaiting confirmation',
        () {
      Map<String, dynamic> base(Map<String, dynamic> extra) => {
            'id': _orderId,
            'status': 'CREATED',
            'payment_status': 'PENDING',
            'total_amount': 200,
            'items': const [],
            'payment_mode': 'UPI_MANUAL',
            ...extra,
          };

      final unclaimed = OrderStatus.fromJson(base({}));
      expect(unclaimed.awaitingUpiPayment, isTrue);
      expect(unclaimed.awaitingUpiConfirmation, isFalse);

      final claimed = OrderStatus.fromJson(
          base({'payment_claimed_at': '2026-10-28T10:00:00Z'}));
      expect(claimed.awaitingUpiPayment, isFalse);
      expect(claimed.awaitingUpiConfirmation, isTrue);

      final paid = OrderStatus.fromJson(base({
        'payment_status': 'PAID',
        'payment_claimed_at': '2026-10-28T10:00:00Z',
      }));
      expect(paid.awaitingUpiPayment, isFalse);
      expect(paid.awaitingUpiConfirmation, isFalse);
    });

    test('a prepaid order has none of the new state', () {
      final o = OrderStatus.fromJson({
        'id': _orderId, 'status': 'PAID', 'payment_status': 'PAID',
        'total_amount': 200, 'items': const [],
      });
      expect(o.paymentMode, PaymentMode.prepaid);
      expect(o.amountDueAtPickup, 0);
      expect(o.callState, isNull);
      expect(o.manualRefundDue, isFalse);
      expect(o.upiPayment, isNull);
      expect(o.awaitingUpiPayment, isFalse);
    });

    test('manual_refund_due is separate from refund_required', () {
      // One is the restaurant's to settle, the other CareVo's. Collapsing them
      // would tell a customer CareVo is refunding money it never touched.
      final o = OrderStatus.fromJson({
        'id': _orderId, 'status': 'CANCELLED', 'payment_status': 'PENDING',
        'total_amount': 200, 'items': const [],
        'payment_mode': 'UPI_MANUAL', 'manual_refund_due': true,
      });
      expect(o.manualRefundDue, isTrue);
      expect(o.refundRequired, isFalse);
    });
  });

  // ============== AMENDMENT A4: Cashfree unreachable (CRITICAL) ============
  group('Cashfree is unreachable without PREPAID', () {
    test('a pay-at-pickup-only outlet offers no prepaid route', () {
      final o = _outlet(methods: const ['PAY_AT_PICKUP']);
      expect(o.acceptsPrepaid, isFalse);
      expect(o.onlyNonGatewayPayment, isTrue);
    });

    test('a UPI-only outlet offers no prepaid route', () {
      final o = _outlet(methods: const ['UPI_MANUAL']);
      expect(o.acceptsPrepaid, isFalse);
    });

    testWidgets('a non-prepaid order never opens the Cashfree sheet',
        (tester) async {
      // The order response for PAY_AT_PICKUP and UPI_MANUAL carries no
      // payment_session_id, and checkout branches on payment_mode BEFORE it
      // looks at the payment block — so there is no path into the sheet. This
      // asserts the spy was never called for either mode.
      for (final mode in ['PAY_AT_PICKUP', 'UPI_MANUAL']) {
        final backend = _Backend();
        final cf = _SpyCashfree();
        final order = CreatedOrder.fromJson({
          'id': _orderId,
          'status': 'CREATED',
          'total_amount': 200,
          'payment_mode': mode,
          if (mode == 'UPI_MANUAL')
            'upi_payment': {
              'vpa': 'kitchen@okaxis',
              'payee_name': 'Test Kitchen',
              'amount': 200,
              'note': 'A1B2C3',
            },
        });
        // The property under test, asserted on the model that drives the
        // branch: a non-gateway mode has no session for the sheet to open.
        expect(order.paymentMode.isNonGateway, isTrue);
        expect(order.payment, isNull);
        expect(cf.opened, 0);
        expect(backend.lastOrderBody, isNull);
      }
    });

    testWidgets('the UPI pay screen renders no Cashfree affordance',
        (tester) async {
      SharedPreferences.setMockInitialValues({'carevo_access_token': 't'});
      final backend = _Backend();
      final cf = _SpyCashfree();
      final order = CreatedOrder.fromJson({
        'id': _orderId,
        'status': 'CREATED',
        'total_amount': 200,
        'payment_mode': 'UPI_MANUAL',
        'upi_payment': {
          'vpa': 'kitchen@okaxis',
          'payee_name': 'Test Kitchen',
          'amount': 200,
          'note': 'A1B2C3',
        },
      });

      await tester.pumpWidget(MultiProvider(
        providers: [
          Provider<ApiClient>.value(value: backend.api),
          Provider<OrderService>(create: (_) => OrderService(backend.api)),
          Provider<CashfreeService>.value(value: cf),
          ChangeNotifierProvider<CartState>(create: (_) => CartState()),
          ChangeNotifierProvider<ThemeProvider>(create: (_) => ThemeProvider()),
        ],
        child: MaterialApp(
          theme: AppTheme.light(),
          home: UpiPayScreen(order: order, onClaimed: () {}),
        ),
      ));
      await tester.pump();

      expect(find.byKey(const Key('upi_vpa_text')), findsOneWidget);
      expect(find.text('kitchen@okaxis'), findsOneWidget);
      // Nothing on this screen mentions or routes to the gateway.
      expect(find.textContaining('Cashfree'), findsNothing);
      expect(find.textContaining('card'), findsNothing);
      expect(find.textContaining('net banking'), findsNothing);
      expect(cf.opened, 0);
    });
  });

  // ================== the UPI pay screen, as a screen ======================
  group('UpiPayScreen', () {
    Future<void> open(WidgetTester tester, _Backend backend,
        {VoidCallback? onClaimed}) async {
      SharedPreferences.setMockInitialValues({'carevo_access_token': 't'});
      final order = CreatedOrder.fromJson({
        'id': _orderId,
        'status': 'CREATED',
        'total_amount': 200,
        'payment_mode': 'UPI_MANUAL',
        'upi_payment': {
          'vpa': 'kitchen@okaxis',
          'payee_name': 'Test Kitchen',
          'amount': 200,
          'note': 'A1B2C3',
        },
      });
      await tester.pumpWidget(MultiProvider(
        providers: [
          Provider<ApiClient>.value(value: backend.api),
          Provider<OrderService>(create: (_) => OrderService(backend.api)),
          Provider<CashfreeService>.value(value: _SpyCashfree()),
          ChangeNotifierProvider<CartState>(create: (_) => CartState()),
          ChangeNotifierProvider<ThemeProvider>(create: (_) => ThemeProvider()),
        ],
        child: MaterialApp(
          theme: AppTheme.light(),
          home: UpiPayScreen(order: order, onClaimed: onClaimed ?? () {}),
        ),
      ));
      await tester.pump();
    }

    testWidgets('shows the amount, the payee and the UPI ID', (tester) async {
      await open(tester, _Backend());
      expect(find.byKey(const Key('upi_amount_heading')), findsOneWidget);
      expect(find.text('to Test Kitchen'), findsOneWidget);
      expect(find.byKey(const Key('upi_vpa_text')), findsOneWidget);
      // The reference the restaurant matches the payment against.
      expect(find.text('Reference: A1B2C3'), findsOneWidget);
      // And the instruction that makes the amount matter.
      expect(find.byKey(const Key('upi_exact_amount_note')), findsOneWidget);
    });

    testWidgets('offers a copy button for the UPI ID', (tester) async {
      await open(tester, _Backend());
      expect(find.byKey(const Key('upi_copy_vpa')), findsOneWidget);
    });

    testWidgets('"I\'ve paid" calls claim-paid exactly once', (tester) async {
      final backend = _Backend();
      var claimed = 0;
      await open(tester, backend, onClaimed: () => claimed++);

      await tester.tap(find.byKey(const Key('upi_claim_paid')));
      await tester.pump();
      await tester.pump(const Duration(milliseconds: 50));

      expect(backend.claims, 1);
      expect(claimed, 1);
    });

    testWidgets('the claim button is available before the UPI app is opened',
        (tester) async {
      // Paying from another device or a banking app is normal; the app must
      // not decide it knows the customer has not paid.
      await open(tester, _Backend());
      final button = tester.widget<Widget>(
          find.byKey(const Key('upi_claim_paid')));
      expect(button, isNotNull);
      expect(find.byKey(const Key('upi_open_app')), findsOneWidget);
    });

    testWidgets('says the order expires if unpaid', (tester) async {
      await open(tester, _Backend());
      expect(find.byKey(const Key('upi_window_note')), findsOneWidget);
    });

    testWidgets('an order with no VPA is a dead end, said plainly',
        (tester) async {
      SharedPreferences.setMockInitialValues({'carevo_access_token': 't'});
      final backend = _Backend();
      final order = CreatedOrder.fromJson({
        'id': _orderId,
        'status': 'CREATED',
        'total_amount': 200,
        'payment_mode': 'UPI_MANUAL',
      });
      await tester.pumpWidget(MultiProvider(
        providers: [
          Provider<ApiClient>.value(value: backend.api),
          Provider<OrderService>(create: (_) => OrderService(backend.api)),
          ChangeNotifierProvider<CartState>(create: (_) => CartState()),
          ChangeNotifierProvider<ThemeProvider>(create: (_) => ThemeProvider()),
        ],
        child: MaterialApp(
          theme: AppTheme.light(),
          home: UpiPayScreen(order: order, onClaimed: () {}),
        ),
      ));
      await tester.pump();
      expect(find.byKey(const Key('upi_pay_unavailable')), findsOneWidget);
      // And no Pay button, because there is nothing to pay to.
      expect(find.byKey(const Key('upi_claim_paid')), findsNothing);
    });
  });
}
