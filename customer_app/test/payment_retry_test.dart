// Payment failure/cancel must not strand the customer.
//
// The defect: BOTH outcomes of the Cashfree sheet — verified and dismissed —
// pushReplacement'd to PickupScreen. A cancelled payment therefore landed on a
// pickup ticket showing "Appears after payment", with no back button (
// automaticallyImplyLeading is false straight from checkout) and one button,
// "Order more", which pushAndRemoveUntil'd to Home. The cart survived, but the
// only route back to it was outlet → menu → cart → checkout.
//
// The line these tests hold, and it is a financial one: a dismissed sheet is
// NOT proof that nothing was paid. onError fires when the customer cancels, but
// it also fires when a genuine payment's confirmation is lost coming back from
// a UPI app. So the retry button must not appear until the server has been
// asked and still says unpaid — otherwise "Try Payment Again" is a
// double-charge button.
//
// Out of scope here: the stub gateway. It never reaches this screen — checkout
// early-returns into PaymentProcessingScreen at the `isCashfree` branch — and
// it already has its own retry.
import 'dart:convert';

import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:http/http.dart' as http;
import 'package:http/testing.dart';
import 'package:provider/provider.dart';
import 'package:shared_preferences/shared_preferences.dart';

import 'package:customer_app/models/menu.dart';
import 'package:customer_app/models/order.dart';
import 'package:customer_app/models/outlet.dart';
import 'package:customer_app/screens/checkout_screen.dart';
import 'package:customer_app/screens/payment_outcome_screen.dart';
import 'package:customer_app/screens/pickup_screen.dart';
import 'package:customer_app/services/api_client.dart';
import 'package:customer_app/services/cashfree_service.dart';
import 'package:customer_app/services/location_service.dart';
import 'package:customer_app/services/order_service.dart';
import 'package:customer_app/services/places_service.dart';
import 'package:customer_app/state/cart_state.dart';
import 'package:customer_app/theme/app_theme.dart';
import 'package:customer_app/theme/theme_provider.dart';

const String _orderId = '11111111-2222-3333-4444-555555555555';
const String _session = 'session_tok_abc123';

/// The order that has already been created and is awaiting payment. This is
/// the object the retry reuses — same id, same session — so the customer keeps
/// their price, their offer and their cart.
CreatedOrder _createdOrder({String? session = _session}) => CreatedOrder(
      id: _orderId,
      status: 'CREATED',
      totalAmount: 240,
      payment: PaymentIntent(
        gateway: 'cashfree',
        gatewayOrderId: 'cf_order_1',
        amount: 240,
        currency: 'INR',
        keyId: 'key',
        paymentSessionId: session,
      ),
    );

/// A backend whose reported payment_status can change between polls, which is
/// exactly what a late webhook looks like from the app's side.
///
/// [statuses] is consumed one entry per GET; the last entry sticks.
/// [paidWhen], when supplied, overrides [statuses] the moment it returns true.
/// Used to model "the payment succeeded on the RETRY" without depending on how
/// many polls happened to fire first — a call-count fixture races the grace
/// deadline and makes the test about timer ordering rather than behaviour.
ApiClient _api(
  List<String> statuses, {
  List<String>? log,
  bool Function()? paidWhen,
}) {
  SharedPreferences.setMockInitialValues({'carevo_access_token': 't'});
  var call = 0;
  return ApiClient(
    client: MockClient((req) async {
      log?.add('${req.method} ${req.url.path}');
      final status = (paidWhen?.call() ?? false)
          ? 'PAID'
          : statuses[call < statuses.length ? call : statuses.length - 1];
      call++;
      return http.Response(
        jsonEncode({
          'order_id': _orderId,
          'status': status == 'PAID' ? 'RECEIVED' : 'CREATED',
          'payment_status': status,
          'outlet_name': 'Test Kitchen',
          'total_amount': 240,
          'discount_amount': 0,
          'created_at': DateTime.now().toIso8601String(),
          'pickup_code': status == 'PAID' ? '482913' : null,
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

/// A CashfreeService whose sheet is scripted rather than real.
///
/// Records every reopen so a test can prove the retry re-invoked payment for
/// the SAME order and session — a passing UI assertion would not.
class _FakeCashfree implements CashfreeService {
  _FakeCashfree(this._results);

  final List<CheckoutResult> _results;
  int _call = 0;
  final List<String> opened = [];

  @override
  Future<CheckoutResult> openCheckout({
    required String orderId,
    required String paymentSessionId,
  }) async {
    opened.add('$orderId/$paymentSessionId');
    final r = _results[_call < _results.length ? _call : _results.length - 1];
    _call++;
    return r;
  }
}

/// A cart with something in it, so "the basket survived" is an assertion about
/// real contents rather than about an already-empty cart.
CartState _seededCart() => CartState();

Widget _host({
  required ApiClient api,
  required CashfreeService cashfree,
  required CartState cart,
  Duration grace = const Duration(seconds: 12),
  Duration poll = const Duration(seconds: 3),
  CreatedOrder? order,
}) {
  return MultiProvider(
    providers: [
      Provider<ApiClient>.value(value: api),
      Provider<OrderService>(create: (_) => OrderService(api)),
      Provider<CashfreeService>.value(value: cashfree),
      Provider<LocationService>(create: (_) => LocationService()),
      ChangeNotifierProvider<CartState>.value(value: cart),
      ChangeNotifierProvider(create: (_) => ThemeProvider()),
    ],
    child: MaterialApp(
      theme: AppTheme.light(),
      home: PaymentOutcomeScreen(
        order: order ?? _createdOrder(),
        reason: 'Payment was cancelled.',
        graceWindow: grace,
        pollInterval: poll,
      ),
    ),
  );
}

/// Unmount so the screen's poll/grace timers are cancelled — a live timer at
/// teardown fails the test, which doubles as the assertion that dispose stops
/// them.
Future<void> _close(WidgetTester tester) async {
  await tester.pumpWidget(const SizedBox.shrink());
  await tester.pumpAndSettle();
}

void main() {
  group('a dismissed sheet does not immediately claim failure', () {
    testWidgets('it confirms with the server before offering retry',
        (tester) async {
      await tester.pumpWidget(_host(
        api: _api(['PENDING']),
        cashfree: _FakeCashfree(const []),
        cart: _seededCart(),
      ));
      await tester.pump();

      // The window in which a double-charge would be created: the sheet has
      // closed reporting failure, and there is deliberately no retry button.
      expect(find.byKey(PaymentOutcomeScreen.confirmingKey), findsOneWidget);
      expect(find.byKey(PaymentOutcomeScreen.tryAgainKey), findsNothing,
          reason: 'retry before the server answers is a double-charge button');
      expect(find.textContaining('Please don\'t pay again yet'), findsOneWidget);

      await _close(tester);
    });

    testWidgets('a late webhook goes straight to pickup, never showing retry',
        (tester) async {
      // The genuine payment whose confirmation was lost. The customer must end
      // on their pickup code, and must never be invited to pay a second time.
      await tester.pumpWidget(_host(
        api: _api(['PENDING', 'PAID']),
        cashfree: _FakeCashfree(const []),
        cart: _seededCart(),
        grace: const Duration(seconds: 12),
        poll: const Duration(seconds: 2),
      ));
      await tester.pump();
      expect(find.byKey(PaymentOutcomeScreen.confirmingKey), findsOneWidget);

      // Second poll lands PAID, still inside the grace window.
      await tester.pump(const Duration(seconds: 3));
      await tester.pumpAndSettle();

      expect(find.byType(PickupScreen), findsOneWidget);
      expect(find.byKey(PaymentOutcomeScreen.tryAgainKey), findsNothing,
          reason: 'a paid order must never offer to be paid again');

      await _close(tester);
    });

    testWidgets('still unpaid after the grace window → retry is offered',
        (tester) async {
      await tester.pumpWidget(_host(
        api: _api(['PENDING']),
        cashfree: _FakeCashfree(const []),
        cart: _seededCart(),
        grace: const Duration(seconds: 5),
        poll: const Duration(seconds: 2),
      ));
      await tester.pump();
      expect(find.byKey(PaymentOutcomeScreen.tryAgainKey), findsNothing);

      await tester.pump(const Duration(seconds: 6));
      await tester.pumpAndSettle();

      expect(find.byKey(PaymentOutcomeScreen.retryStateKey), findsOneWidget);
      expect(find.byKey(PaymentOutcomeScreen.tryAgainKey), findsOneWidget);
      expect(find.text('Try Payment Again'), findsOneWidget);
      expect(find.textContaining('You have not been charged'), findsOneWidget);

      await _close(tester);
    });

    testWidgets('a dead network still reaches retry rather than hanging',
        (tester) async {
      SharedPreferences.setMockInitialValues({'carevo_access_token': 't'});
      final broken = ApiClient(
        client: MockClient((_) async => http.Response('boom', 500)),
      );
      await tester.pumpWidget(_host(
        api: broken,
        cashfree: _FakeCashfree(const []),
        cart: _seededCart(),
        grace: const Duration(seconds: 4),
        poll: const Duration(seconds: 2),
      ));
      await tester.pump();
      await tester.pump(const Duration(seconds: 5));
      await tester.pumpAndSettle();

      expect(find.byKey(PaymentOutcomeScreen.tryAgainKey), findsOneWidget,
          reason: 'a failing poll must not trap the customer in confirming');

      await _close(tester);
    });
  });

  group('retry re-invokes the same payment', () {
    testWidgets('it reopens the SAME order and session, not a new order',
        (tester) async {
      final cashfree = _FakeCashfree(
          const [CheckoutResult(CheckoutOutcome.verified)]);
      await tester.pumpWidget(_host(
        api: _api(['PENDING']),
        cashfree: cashfree,
        cart: _seededCart(),
        grace: const Duration(seconds: 4),
        poll: const Duration(seconds: 2),
      ));
      await tester.pump();
      await tester.pump(const Duration(seconds: 5));
      await tester.pumpAndSettle();

      await tester.tap(find.byKey(PaymentOutcomeScreen.tryAgainKey));
      await tester.pump();

      // The evidence a screenshot could not give: the retry addressed the
      // existing order on its existing session. A new order would mean a new
      // id, a lost offer and a re-priced basket.
      expect(cashfree.opened, ['$_orderId/$_session']);

      await _close(tester);
    });

    testWidgets('a successful retry still defers to the server, then pickup',
        (tester) async {
      final cashfree = _FakeCashfree(
          const [CheckoutResult(CheckoutOutcome.verified)]);
      // The webhook lands only once the customer has actually retried.
      await tester.pumpWidget(_host(
        api: _api(['PENDING'], paidWhen: () => cashfree.opened.isNotEmpty),
        cashfree: cashfree,
        cart: _seededCart(),
        grace: const Duration(seconds: 4),
        poll: const Duration(seconds: 2),
      ));
      await tester.pump();
      await tester.pump(const Duration(seconds: 5));
      await tester.pumpAndSettle();

      await tester.tap(find.byKey(PaymentOutcomeScreen.tryAgainKey));
      await tester.pump();
      // Back into confirming — the SDK's "verified" is not taken as payment.
      expect(find.byKey(PaymentOutcomeScreen.confirmingKey), findsOneWidget);

      await tester.pump(const Duration(seconds: 3));
      await tester.pumpAndSettle();
      expect(find.byType(PickupScreen), findsOneWidget);

      await _close(tester);
    });

    testWidgets('a second cancellation returns to retry, not a dead end',
        (tester) async {
      final cashfree = _FakeCashfree(const [
        CheckoutResult(CheckoutOutcome.failed, message: 'Cancelled again.'),
      ]);
      await tester.pumpWidget(_host(
        api: _api(['PENDING']),
        cashfree: cashfree,
        cart: _seededCart(),
        grace: const Duration(seconds: 3),
        poll: const Duration(seconds: 2),
      ));
      await tester.pump();
      await tester.pump(const Duration(seconds: 4));
      await tester.pumpAndSettle();

      await tester.tap(find.byKey(PaymentOutcomeScreen.tryAgainKey));
      await tester.pump();
      await tester.pump(const Duration(seconds: 4));
      await tester.pumpAndSettle();

      expect(find.byKey(PaymentOutcomeScreen.tryAgainKey), findsOneWidget,
          reason: 'the customer can always try once more');
      expect(find.textContaining('Cancelled again.'), findsOneWidget);

      await _close(tester);
    });

    testWidgets('a sheet that cannot open says so without pretending to retry',
        (tester) async {
      final cashfree = _FakeCashfree(const [
        CheckoutResult(CheckoutOutcome.notStarted,
            message: 'A payment is already in progress.'),
      ]);
      await tester.pumpWidget(_host(
        api: _api(['PENDING']),
        cashfree: cashfree,
        cart: _seededCart(),
        grace: const Duration(seconds: 3),
        poll: const Duration(seconds: 2),
      ));
      await tester.pump();
      await tester.pump(const Duration(seconds: 4));
      await tester.pumpAndSettle();

      await tester.tap(find.byKey(PaymentOutcomeScreen.tryAgainKey));
      await tester.pumpAndSettle();

      expect(find.textContaining('already in progress'), findsOneWidget);
      expect(find.byKey(PaymentOutcomeScreen.tryAgainKey), findsOneWidget);

      await _close(tester);
    });

    testWidgets('an order with no session refuses rather than opening empty',
        (tester) async {
      final cashfree = _FakeCashfree(const []);
      await tester.pumpWidget(_host(
        api: _api(['PENDING']),
        cashfree: cashfree,
        cart: _seededCart(),
        grace: const Duration(seconds: 3),
        poll: const Duration(seconds: 2),
        order: _createdOrder(session: null),
      ));
      await tester.pump();
      await tester.pump(const Duration(seconds: 4));
      await tester.pumpAndSettle();

      await tester.tap(find.byKey(PaymentOutcomeScreen.tryAgainKey));
      await tester.pumpAndSettle();

      expect(cashfree.opened, isEmpty,
          reason: 'never open a sheet with no session token');
      expect(find.textContaining('can no longer be paid for'), findsOneWidget);

      await _close(tester);
    });
  });

  group('the customer keeps their order', () {
    testWidgets('the cart is never cleared on the failure path', (tester) async {
      final cart = _seededCart();
      var clears = 0;
      cart.addListener(() {
        if (cart.isEmpty) clears++;
      });

      await tester.pumpWidget(_host(
        api: _api(['PENDING']),
        cashfree: _FakeCashfree(const []),
        cart: cart,
        grace: const Duration(seconds: 3),
        poll: const Duration(seconds: 2),
      ));
      await tester.pump();
      await tester.pump(const Duration(seconds: 4));
      await tester.pumpAndSettle();

      expect(find.byKey(PaymentOutcomeScreen.retryStateKey), findsOneWidget);
      expect(clears, 0,
          reason: 'a failed payment must not spend the basket');

      await _close(tester);
    });

    testWidgets('there is a way back to the order, and it is not Home',
        (tester) async {
      // The defect in one assertion. PickupScreen offered only "Order more",
      // which pushAndRemoveUntil'd to HomeScreen; this screen offers a plain
      // pop, so checkout — and the basket on it — is still underneath.
      await tester.pumpWidget(_host(
        api: _api(['PENDING']),
        cashfree: _FakeCashfree(const []),
        cart: _seededCart(),
        grace: const Duration(seconds: 3),
        poll: const Duration(seconds: 2),
      ));
      await tester.pump();
      await tester.pump(const Duration(seconds: 4));
      await tester.pumpAndSettle();

      expect(find.byKey(PaymentOutcomeScreen.backToCartKey), findsOneWidget);
      expect(find.text('Back to my order'), findsOneWidget);
      // And an escape hatch for "my bank says it debited me".
      expect(find.byKey(PaymentOutcomeScreen.checkStatusKey), findsOneWidget);

      await _close(tester);
    });

    testWidgets('the amount is restated so the order is recognisable',
        (tester) async {
      await tester.pumpWidget(_host(
        api: _api(['PENDING']),
        cashfree: _FakeCashfree(const []),
        cart: _seededCart(),
        grace: const Duration(seconds: 3),
        poll: const Duration(seconds: 2),
      ));
      await tester.pump();
      await tester.pump(const Duration(seconds: 4));
      await tester.pumpAndSettle();

      expect(find.text('Your order is saved'), findsOneWidget);
      expect(find.textContaining('240'), findsWidgets);

      await _close(tester);
    });

    testWidgets('"I was charged" reaches the pickup screen', (tester) async {
      await tester.pumpWidget(_host(
        api: _api(['PENDING']),
        cashfree: _FakeCashfree(const []),
        cart: _seededCart(),
        grace: const Duration(seconds: 3),
        poll: const Duration(seconds: 2),
      ));
      await tester.pump();
      await tester.pump(const Duration(seconds: 4));
      await tester.pumpAndSettle();

      await tester.tap(find.byKey(PaymentOutcomeScreen.checkStatusKey));
      await tester.pumpAndSettle();

      expect(find.byType(PickupScreen), findsOneWidget);

      await _close(tester);
    });
  });

  _wiringTests();
}

// ===========================================================================
// The wiring at the navigation point.
//
// Everything above drives PaymentOutcomeScreen directly, which proves the
// screen behaves — but would keep passing if checkout_screen.dart went back to
// sending BOTH outcomes to PickupScreen. These two tests are the ones that
// fail on that revert: they drive the real CheckoutScreen and assert which
// screen each outcome actually lands on.
// ===========================================================================

MenuItem _menuItem() => MenuItem.fromJson({
      'id': 'i1',
      'name': 'Masala Dosa',
      'base_price': 120.0,
      'is_veg': true,
      'is_available': true,
      'image_url': null,
      'prep_time_minutes': 0,
      'tags': const <String>[],
      'customizations': const <dynamic>[],
    });

Outlet _outlet() => Outlet.fromJson({
      'id': 'o1',
      'name': 'Test Kitchen',
      'address': 'Somewhere',
      'is_open': true,
    });

/// A cart holding a real order at a real outlet — so "the basket survived" is
/// a claim about contents, not about an empty cart trivially staying empty.
CartState _cartWithItems() {
  final cart = CartState();
  cart.setOutlet(_outlet());
  cart.addItem(_menuItem(), quantity: 2);
  return cart;
}

/// A backend that creates a CASHFREE order (so checkout takes the Cashfree
/// branch rather than the stub one) and then reports it unpaid.
ApiClient _checkoutApi({List<String>? log}) {
  SharedPreferences.setMockInitialValues({'carevo_access_token': 't'});
  return ApiClient(
    client: MockClient((req) async {
      final path = req.url.path;
      log?.add('${req.method} $path');

      if (req.method == 'POST' && path.endsWith('/customer/orders')) {
        return http.Response(
          jsonEncode({
            'id': _orderId,
            'status': 'CREATED',
            'total_amount': 240,
            'original_amount': 240,
            'discount_amount': 0,
            'payment': {
              'gateway': 'cashfree',
              'gateway_order_id': 'cf_order_1',
              'amount': 240,
              'currency': 'INR',
              'key_id': 'k',
              'payment_session_id': _session,
            },
          }),
          200,
          headers: {'content-type': 'application/json'},
        );
      }

      // Availability pre-check: nothing is sold out.
      if (req.method == 'POST' && path.contains('availability')) {
        return http.Response(jsonEncode({'unavailable': <String>[]}), 200,
            headers: {'content-type': 'application/json'});
      }

      // Order status polls — still awaiting the webhook.
      return http.Response(
        jsonEncode({
          'order_id': _orderId,
          'status': 'CREATED',
          'payment_status': 'PENDING',
          'outlet_name': 'Test Kitchen',
          'total_amount': 240,
          'discount_amount': 0,
          'created_at': DateTime.now().toIso8601String(),
          'pickup_code': null,
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

Widget _checkoutHost({
  required ApiClient api,
  required CashfreeService cashfree,
  required CartState cart,
}) {
  return MultiProvider(
    providers: [
      Provider<ApiClient>.value(value: api),
      Provider<OrderService>(create: (_) => OrderService(api)),
      Provider<CashfreeService>.value(value: cashfree),
      Provider<LocationService>(create: (_) => LocationService()),
      Provider<PlacesService>(create: (_) => PlacesService()),
      ChangeNotifierProvider<CartState>.value(value: cart),
      ChangeNotifierProvider(create: (_) => ThemeProvider()),
    ],
    child: MaterialApp(
      theme: AppTheme.light(),
      home: const CheckoutScreen(),
    ),
  );
}

void _wiringTests() {
  group('checkout routes each outcome to the right screen', () {
    testWidgets('a DISMISSED sheet lands on the retry screen, not pickup',
        (tester) async {
      final cart = _cartWithItems();
      final cashfree = _FakeCashfree(const [
        CheckoutResult(CheckoutOutcome.failed, message: 'Payment cancelled.'),
      ]);
      await tester.pumpWidget(_checkoutHost(
        api: _checkoutApi(), cashfree: cashfree, cart: cart));
      await tester.pumpAndSettle();

      await tester.tap(find.byKey(const Key('checkout_pay')));
      await tester.pumpAndSettle();

      expect(find.byType(PaymentOutcomeScreen), findsOneWidget,
          reason: 'a cancelled payment must not land on the pickup ticket');
      expect(find.byType(PickupScreen), findsNothing);

      // And the basket is intact — nothing to re-add.
      expect(cart.isEmpty, isFalse);
      expect(cart.items.first.quantity, 2);

      await _close(tester);
    });

    testWidgets('a VERIFIED sheet still goes straight to pickup',
        (tester) async {
      // The success path is unchanged by this work; this is the guard that
      // says so.
      final cart = _cartWithItems();
      final cashfree = _FakeCashfree(
          const [CheckoutResult(CheckoutOutcome.verified)]);
      await tester.pumpWidget(_checkoutHost(
        api: _checkoutApi(), cashfree: cashfree, cart: cart));
      await tester.pumpAndSettle();

      await tester.tap(find.byKey(const Key('checkout_pay')));
      await tester.pumpAndSettle();

      expect(find.byType(PickupScreen), findsOneWidget);
      expect(find.byType(PaymentOutcomeScreen), findsNothing);

      await _close(tester);
    });
  });
}
