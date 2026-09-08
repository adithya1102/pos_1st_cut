// Payment failure/cancel must not strand the customer — now handled INLINE on
// the pickup screen rather than a separate PaymentOutcomeScreen.
//
// The defect these tests guard against: BOTH outcomes of the Cashfree sheet —
// verified and dismissed — used to land on a pickup ticket showing "Appears
// after payment", with no back button and one button ("Order more") that
// cleared the stack to Home. The cart survived, but the only route back to it
// was outlet → menu → cart → checkout.
//
// The line these tests hold, and it is a financial one: a dismissed sheet is
// NOT proof that nothing was paid. onError fires when the customer cancels, but
// it also fires when a genuine payment's confirmation is lost coming back from
// a UPI app. So the retry button must not appear until the server has been
// asked and still says unpaid — otherwise "Try Payment Again" is a
// double-charge button. That confirmation window now runs on the pickup screen
// itself: while it runs, the pickup-code area is replaced by a "confirming"
// state; only if it closes still-unpaid does the retry state replace it.
//
// Out of scope here: the stub gateway. It never reaches this flow — checkout
// early-returns into PaymentProcessingScreen at the `isCashfree` branch.
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
/// the object retry reuses — same id, same session — so the customer keeps
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
/// [paidWhen], when supplied, overrides [statuses] the moment it returns true —
/// used to model "the payment succeeded on the RETRY" without depending on how
/// many polls happened to fire first.
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

CartState _seededCart() => CartState();

/// Mounts PickupScreen in the awaiting-payment state — i.e. reached from a
/// sheet that did NOT report success. This is the failure path the whole
/// feature exists for; the confirmation window runs inline here.
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
      home: PickupScreen(
        orderId: _orderId,
        amount: 240,
        awaitingPayment: true,
        paymentOrder: order ?? _createdOrder(),
        paymentReason: 'Payment was cancelled.',
        graceWindow: grace,
        confirmPollInterval: poll,
      ),
    ),
  );
}

/// Unmount so the screen's poll/grace/status timers are cancelled — a live
/// timer at teardown fails the test, which doubles as the assertion that
/// dispose stops them.
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
      expect(find.byKey(PickupScreen.confirmingKey), findsOneWidget);
      expect(find.byKey(PickupScreen.tryAgainKey), findsNothing,
          reason: 'retry before the server answers is a double-charge button');
      expect(find.textContaining('Please don\'t pay again yet'), findsOneWidget);
      // The pickup code slot is REPLACED by the confirming state, not left on
      // the dead "Appears after payment" placeholder.
      expect(find.text('Appears after payment'), findsNothing);

      await _close(tester);
    });

    testWidgets('a late webhook resolves to the pickup code, never showing retry',
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
      expect(find.byKey(PickupScreen.confirmingKey), findsOneWidget);

      // Second poll lands PAID, still inside the grace window.
      await tester.pump(const Duration(seconds: 3));
      await tester.pump();

      expect(find.text('482913'), findsOneWidget,
          reason: 'a confirmed payment reveals the pickup code inline');
      expect(find.byKey(PickupScreen.tryAgainKey), findsNothing,
          reason: 'a paid order must never offer to be paid again');
      expect(find.byKey(PickupScreen.confirmingKey), findsNothing);

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
      expect(find.byKey(PickupScreen.tryAgainKey), findsNothing);

      await tester.pump(const Duration(seconds: 6));

      expect(find.byKey(PickupScreen.retryStateKey), findsOneWidget);
      expect(find.byKey(PickupScreen.tryAgainKey), findsOneWidget);
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

      expect(find.byKey(PickupScreen.tryAgainKey), findsOneWidget,
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

      await tester.tap(find.byKey(PickupScreen.tryAgainKey));
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
      // The webhook lands only AFTER the retry, and only on a later poll — the
      // first poll after reopening still reads PENDING. That gap is the whole
      // point: it proves the code is revealed by the SERVER confirming, not by
      // the SDK's "verified", which fires one tick earlier.
      var pollsAfterRetry = 0;
      await tester.pumpWidget(_host(
        api: _api(['PENDING'], paidWhen: () {
          if (cashfree.opened.isEmpty) return false;
          pollsAfterRetry++;
          return pollsAfterRetry > 1;
        }),
        cashfree: cashfree,
        cart: _seededCart(),
        grace: const Duration(seconds: 4),
        poll: const Duration(seconds: 2),
      ));
      await tester.pump();
      await tester.pump(const Duration(seconds: 5));

      await tester.tap(find.byKey(PickupScreen.tryAgainKey));
      await tester.pump();
      // Back into confirming — the SDK's "verified" is not taken as payment,
      // and the first post-retry poll still reads PENDING.
      expect(find.byKey(PickupScreen.confirmingKey), findsOneWidget);

      await tester.pump(const Duration(seconds: 3));
      await tester.pump();
      expect(find.text('482913'), findsOneWidget,
          reason: 'only the server-confirmed retry reveals the code');

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

      await tester.tap(find.byKey(PickupScreen.tryAgainKey));
      await tester.pump();
      await tester.pump(const Duration(seconds: 4));

      expect(find.byKey(PickupScreen.tryAgainKey), findsOneWidget,
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

      await tester.tap(find.byKey(PickupScreen.tryAgainKey));
      await tester.pump();

      expect(find.textContaining('already in progress'), findsOneWidget);
      expect(find.byKey(PickupScreen.tryAgainKey), findsOneWidget);

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

      await tester.tap(find.byKey(PickupScreen.tryAgainKey));
      await tester.pump();

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

      expect(find.byKey(PickupScreen.retryStateKey), findsOneWidget);
      expect(clears, 0, reason: 'a failed payment must not spend the basket');

      await _close(tester);
    });

    testWidgets('the retry state is inline on the pickup page, with an escape '
        'hatch — not a dead end', (tester) async {
      // The merge in one assertion. The old separate screen offered a "Back to
      // my order" pop; inline on the pickup page there is nowhere to pop to, so
      // the way forward is the retry itself plus the charged-anyway hatch.
      await tester.pumpWidget(_host(
        api: _api(['PENDING']),
        cashfree: _FakeCashfree(const []),
        cart: _seededCart(),
        grace: const Duration(seconds: 3),
        poll: const Duration(seconds: 2),
      ));
      await tester.pump();
      await tester.pump(const Duration(seconds: 4));

      expect(find.byType(PickupScreen), findsOneWidget);
      expect(find.byKey(PickupScreen.retryStateKey), findsOneWidget);
      expect(find.byKey(PickupScreen.tryAgainKey), findsOneWidget);
      // The escape hatch for "my bank says it debited me", inline now.
      expect(find.byKey(PickupScreen.checkStatusKey), findsOneWidget);

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

      expect(find.text('Payment not completed'), findsOneWidget);
      expect(find.textContaining('240'), findsWidgets);

      await _close(tester);
    });

    testWidgets('"I was charged" drops the retry prompt and keeps polling',
        (tester) async {
      // Inline now: instead of navigating to a pickup screen, it hands THIS
      // page back to its ordinary waiting state (which keeps polling), so a
      // real late webhook still resolves and the code appears.
      await tester.pumpWidget(_host(
        api: _api(['PENDING']),
        cashfree: _FakeCashfree(const []),
        cart: _seededCart(),
        grace: const Duration(seconds: 3),
        poll: const Duration(seconds: 2),
      ));
      await tester.pump();
      await tester.pump(const Duration(seconds: 4));
      expect(find.byKey(PickupScreen.retryStateKey), findsOneWidget);

      await tester.tap(find.byKey(PickupScreen.checkStatusKey));
      await tester.pump();

      // Retry prompt gone; the ordinary unpaid pickup-code placeholder is back.
      expect(find.byKey(PickupScreen.retryStateKey), findsNothing);
      expect(find.byKey(PickupScreen.confirmingKey), findsNothing);
      expect(find.text('Appears after payment'), findsOneWidget);

      await _close(tester);
    });
  });

  _wiringTests();
}

// ===========================================================================
// The wiring at the navigation point.
//
// Everything above drives PickupScreen's inline states directly, which proves
// the states behave — but would keep passing if checkout_screen.dart routed
// both outcomes identically. These two tests drive the real CheckoutScreen and
// assert that a dismissed sheet opens PickupScreen in its CONFIRMING state
// (awaitingPayment) while a verified sheet opens it in the ordinary state.
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

/// Flush checkout's async chain (availability → create order → open sheet →
/// pushReplacement) plus PickupScreen's first poll, WITHOUT pumpAndSettle —
/// the destination's confirming spinner and periodic timers never settle.
Future<void> _settleCheckout(WidgetTester tester) async {
  for (var i = 0; i < 12; i++) {
    await tester.pump(const Duration(milliseconds: 50));
  }
}

void _wiringTests() {
  group('checkout routes each outcome to the right pickup state', () {
    testWidgets('a DISMISSED sheet opens the pickup screen CONFIRMING, not the '
        'dead code placeholder', (tester) async {
      final cart = _cartWithItems();
      final cashfree = _FakeCashfree(const [
        CheckoutResult(CheckoutOutcome.failed, message: 'Payment cancelled.'),
      ]);
      await tester.pumpWidget(_checkoutHost(
          api: _checkoutApi(), cashfree: cashfree, cart: cart));
      await tester.pumpAndSettle();

      await tester.tap(find.byKey(const Key('checkout_pay')));
      await _settleCheckout(tester);

      // Landed on the pickup screen — the single destination — but in its
      // awaiting-payment confirming state, not stranded on a code placeholder.
      expect(find.byType(PickupScreen), findsOneWidget);
      expect(find.byKey(PickupScreen.confirmingKey), findsOneWidget,
          reason: 'a dismissed sheet must open the confirmation window');
      expect(find.byType(CheckoutScreen), findsNothing,
          reason: 'pushReplacement removes checkout from the stack');

      // And the basket is intact — nothing to re-add.
      expect(cart.isEmpty, isFalse);
      expect(cart.items.first.quantity, 2);

      await _close(tester);
    });

    testWidgets('a VERIFIED sheet opens the pickup screen WITHOUT confirming',
        (tester) async {
      // The success path is unchanged: a verified sheet goes straight to the
      // ordinary pickup flow, never showing the confirmation window. This is
      // the guard that fails if checkout stops distinguishing the outcomes.
      final cart = _cartWithItems();
      final cashfree = _FakeCashfree(
          const [CheckoutResult(CheckoutOutcome.verified)]);
      await tester.pumpWidget(_checkoutHost(
          api: _checkoutApi(), cashfree: cashfree, cart: cart));
      await tester.pumpAndSettle();

      await tester.tap(find.byKey(const Key('checkout_pay')));
      await _settleCheckout(tester);

      expect(find.byType(PickupScreen), findsOneWidget);
      expect(find.byKey(PickupScreen.confirmingKey), findsNothing,
          reason: 'a verified sheet must not enter the confirmation window');

      await _close(tester);
    });
  });
}
