// Checkout follows the owner's payment toggles (Payment tab mission, TASK 4).
//
// THE GROUP THAT MATTERS MOST is "option removed between open and pay": the
// owner can flip a toggle off while the customer is mid-checkout, and the
// server is the only thing that actually knows at the moment Pay is tapped —
// so a 409 PAYMENT_METHOD_UNAVAILABLE must refetch and let the customer try
// again with the cart and any scheduled time intact, never with a silent
// retry of the same now-dead method.
import 'dart:async';
import 'dart:convert';

import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:http/http.dart' as http;
import 'package:http/testing.dart';
import 'package:provider/provider.dart';
import 'package:shared_preferences/shared_preferences.dart';

import 'package:customer_app/models/menu.dart';
import 'package:customer_app/models/outlet.dart';
import 'package:customer_app/screens/checkout_screen.dart';
import 'package:customer_app/services/api_client.dart';
import 'package:customer_app/services/cashfree_service.dart';
import 'package:customer_app/services/catalog_service.dart';
import 'package:customer_app/services/location_service.dart';
import 'package:customer_app/services/order_service.dart';
import 'package:customer_app/services/places_service.dart';
import 'package:customer_app/state/cart_state.dart';
import 'package:customer_app/theme/app_theme.dart';
import 'package:customer_app/theme/theme_provider.dart';

Outlet _outlet({List<String>? methods}) => Outlet.fromJson({
      'id': 'o1',
      'name': 'Test Kitchen',
      'address': 'Somewhere',
      'is_open': true,
      'order_status': 'open',
      if (methods != null) 'payment_methods': methods,
    });

MenuItem _menuItem() => MenuItem.fromJson({
      'id': 'm1',
      'name': 'Masala Dosa',
      'base_price': 120,
      'is_veg': true,
      'is_available': true,
    });

CartState _cartWithItems(List<String>? methods) {
  final cart = CartState();
  cart.setOutlet(_outlet(methods: methods));
  cart.addItem(_menuItem(), quantity: 2);
  return cart;
}

/// A backend whose `/customer/menu/:id` answers with [methods] — mutable, so
/// a test can change what the NEXT fetch returns (simulating the owner
/// flipping a toggle) without rebuilding the whole widget tree.
class _Backend {
  _Backend(this.methods);

  List<String> methods;

  /// When true, exactly ONE `/customer/orders` call gets the 409; every call
  /// after that (the retry, once the customer picks the now-valid method)
  /// succeeds normally.
  bool failNextOrderWith409 = false;
  int orderAttempts = 0;
  Map<String, dynamic>? lastOrderBody;
  int menuFetches = 0;

  late final ApiClient api = ApiClient(
    client: MockClient((req) async {
      if (req.method == 'GET' && req.url.path.contains('/customer/menu/')) {
        menuFetches++;
        return http.Response(
          jsonEncode({
            'outlet_id': 'o1',
            'categories': const [],
            'payment_methods': methods,
          }),
          200,
          headers: {'content-type': 'application/json'},
        );
      }
      if (req.method == 'POST' && req.url.path.endsWith('/customer/cart/check')) {
        return http.Response(jsonEncode({'unavailable': []}), 200,
            headers: {'content-type': 'application/json'});
      }
      if (req.method == 'POST' && req.url.path.endsWith('/customer/orders')) {
        orderAttempts++;
        lastOrderBody = jsonDecode(req.body) as Map<String, dynamic>;
        if (failNextOrderWith409) {
          failNextOrderWith409 = false;
          return http.Response(
            jsonEncode({
              'detail': {
                'error': 'PAYMENT_METHOD_UNAVAILABLE',
                'available': methods,
                'message': 'That payment method is no longer available.',
              },
            }),
            409,
            headers: {'content-type': 'application/json'},
          );
        }
        final mode = (lastOrderBody!['payment_method'] ?? 'PREPAID').toString();
        return http.Response(
          jsonEncode({
            'id': '11111111-2222-3333-4444-555555555555',
            'status': 'CREATED',
            'total_amount': 240,
            'payment_mode': mode,
            'amount_due_at_pickup': mode == 'PAY_AT_PICKUP' ? 240 : 0,
            if (mode == 'PREPAID')
              'payment': {
                'gateway': 'cashfree',
                'gateway_order_id': 'cf_1',
                'amount': 240,
                'currency': 'INR',
                'payment_session_id': 'session_abc',
              },
            if (mode == 'UPI_MANUAL')
              'upi_payment': {
                'vpa': 'kitchen@okaxis',
                'payee_name': 'Test Kitchen',
                'amount': 240,
                'note': 'A1B2C3',
              },
          }),
          200,
          headers: {'content-type': 'application/json'},
        );
      }
      return http.Response(jsonEncode(const {}), 200,
          headers: {'content-type': 'application/json'});
    }),
  );
}

/// Resolves instantly as verified — the tests here care about which method
/// reached create_order, not about the gateway sheet itself.
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

final _navKey = GlobalKey<NavigatorState>();

Widget _host(CartState cart, _Backend backend) {
  SharedPreferences.setMockInitialValues({'carevo_access_token': 't'});
  return MultiProvider(
    providers: [
      Provider<ApiClient>.value(value: backend.api),
      Provider<OrderService>(create: (_) => OrderService(backend.api)),
      Provider<CatalogService>(create: (_) => CatalogService(backend.api)),
      Provider<CashfreeService>.value(value: _SpyCashfree()),
      Provider<LocationService>(create: (_) => LocationService()),
      Provider<PlacesService>(create: (_) => PlacesService()),
      ChangeNotifierProvider<CartState>.value(value: cart),
      ChangeNotifierProvider(create: (_) => ThemeProvider()),
    ],
    child: MaterialApp(
      theme: AppTheme.light(),
      navigatorKey: _navKey,
      home: const Scaffold(body: Center(child: Text('base route'))),
    ),
  );
}

/// Tears the tree down so PickupScreen's polling Timer does not outlive a
/// test that paid all the way through.
Future<void> _close(WidgetTester tester) async {
  await tester.pumpWidget(const SizedBox.shrink());
  await tester.pumpAndSettle();
}

Future<void> _openCheckout(
    WidgetTester tester, CartState cart, _Backend backend) async {
  tester.view.physicalSize = const Size(1400, 7000);
  tester.view.devicePixelRatio = 2.0;
  addTearDown(tester.view.reset);
  await tester.pumpWidget(_host(cart, backend));
  await tester.pump();
  unawaited(_navKey.currentState!
      .push(MaterialPageRoute(builder: (_) => const CheckoutScreen())));
  await tester.pumpAndSettle();
}

void main() {
  group('three options offered', () {
    testWidgets('all three render, in gateway / UPI / pickup order',
        (tester) async {
      final backend =
          _Backend(const ['PAY_AT_PICKUP', 'UPI_MANUAL', 'PREPAID']);
      final cart =
          _cartWithItems(const ['PAY_AT_PICKUP', 'UPI_MANUAL', 'PREPAID']);
      await _openCheckout(tester, cart, backend);

      final gateway = tester.getTopLeft(find.byKey(const Key('payment_method_PREPAID')));
      final upi = tester.getTopLeft(find.byKey(const Key('payment_method_UPI_MANUAL')));
      final pickup =
          tester.getTopLeft(find.byKey(const Key('payment_method_PAY_AT_PICKUP')));
      expect(gateway.dy, lessThan(upi.dy));
      expect(upi.dy, lessThan(pickup.dy));
    });

    testWidgets('the gateway option is preselected', (tester) async {
      final backend = _Backend(const ['PAY_AT_PICKUP', 'UPI_MANUAL', 'PREPAID']);
      final cart = _cartWithItems(const ['PAY_AT_PICKUP', 'UPI_MANUAL', 'PREPAID']);
      await _openCheckout(tester, cart, backend);

      await tester.tap(find.byKey(const Key('checkout_pay')));
      await tester.pump(const Duration(milliseconds: 50));
      await tester.pump(const Duration(milliseconds: 50));
      await tester.pump(const Duration(milliseconds: 50));

      expect(backend.lastOrderBody?['payment_method'], 'PREPAID');
      await _close(tester);
    });
  });

  group('a single option', () {
    testWidgets('renders as a statement, not a choice, and is used to pay',
        (tester) async {
      final backend = _Backend(const ['PAY_AT_PICKUP']);
      final cart = _cartWithItems(const ['PAY_AT_PICKUP']);
      await _openCheckout(tester, cart, backend);

      // Single-method rendering has no radio row to tap — see
      // checkout_screen._buildPaymentSection's `single` branch.
      expect(find.byKey(const Key('payment_method_PAY_AT_PICKUP')),
          findsOneWidget);
      expect(find.byIcon(Icons.radio_button_checked), findsNothing);
      expect(find.byIcon(Icons.radio_button_unchecked), findsNothing);
    });
  });

  group('the fixed customer-facing order', () {
    testWidgets('is gateway, UPI, pickup regardless of server order',
        (tester) async {
      // Server lists them pickup-first; the app must still show gateway
      // first — see CheckoutScreen._methodDisplayOrder.
      final backend = _Backend(const ['PAY_AT_PICKUP', 'PREPAID', 'UPI_MANUAL']);
      final cart = _cartWithItems(const ['PAY_AT_PICKUP', 'PREPAID', 'UPI_MANUAL']);
      await _openCheckout(tester, cart, backend);

      final gateway =
          tester.getTopLeft(find.byKey(const Key('payment_method_PREPAID')));
      final upi =
          tester.getTopLeft(find.byKey(const Key('payment_method_UPI_MANUAL')));
      final pickup = tester
          .getTopLeft(find.byKey(const Key('payment_method_PAY_AT_PICKUP')));
      expect(gateway.dy, lessThan(upi.dy));
      expect(upi.dy, lessThan(pickup.dy));
    });
  });

  group('checkout refreshes its options on open', () {
    testWidgets('a stale cached outlet is corrected by a fresh fetch',
        (tester) async {
      // The cart carries an OLD snapshot (gateway + pickup); the server now
      // says pickup only — the owner turned the gateway off since the
      // customer last opened the menu. Checkout must show what the server
      // says NOW, not what the cart happened to cache.
      final backend = _Backend(const ['PAY_AT_PICKUP']);
      final cart = _cartWithItems(const ['PREPAID', 'PAY_AT_PICKUP']);
      await _openCheckout(tester, cart, backend);

      expect(backend.menuFetches, greaterThanOrEqualTo(1),
          reason: 'checkout must fetch on open, not reuse the cached outlet');
      expect(find.byKey(const Key('payment_method_PREPAID')), findsNothing);
      expect(find.byKey(const Key('payment_method_PAY_AT_PICKUP')),
          findsOneWidget);
    });
  });

  group('an option removed between open and pay', () {
    testWidgets(
        '409 PAYMENT_METHOD_UNAVAILABLE refetches, warns, and keeps the cart',
        (tester) async {
      final backend = _Backend(const ['PAY_AT_PICKUP', 'PREPAID'])
        ..failNextOrderWith409 = true;
      final cart = _cartWithItems(const ['PAY_AT_PICKUP', 'PREPAID']);
      await _openCheckout(tester, cart, backend);

      // Simulate the removal happening on the server right as Pay is tapped:
      // the NEXT menu fetch (triggered by the 409 handler) sees pickup only.
      backend.methods = const ['PAY_AT_PICKUP'];

      final fetchesBeforePay = backend.menuFetches;
      await tester.tap(find.byKey(const Key('checkout_pay')));
      await tester.pump(const Duration(milliseconds: 50));
      await tester.pumpAndSettle();

      expect(backend.menuFetches, greaterThan(fetchesBeforePay),
          reason: 'the 409 must trigger a refetch');
      expect(
          find.text('This payment option is no longer available. '
              'Please choose another.'),
          findsOneWidget);
      // The gateway option is gone from the list now that it refetched.
      expect(find.byKey(const Key('payment_method_PREPAID')), findsNothing);
      // The cart is untouched — no order exists, nothing to roll back.
      expect(cart.isEmpty, isFalse);
      expect(cart.totalQuantity, 2);
      await _close(tester);
    });
  });

  group('scheduled pickup with a pickup-only outlet', () {
    testWidgets('the existing refusal to schedule is still shown',
        (tester) async {
      // Pay-at-pickup settles outside the gateway, so the server refuses a
      // requested_pickup_at for it (migration 034) — _canSchedule already
      // hides the toggle for exactly this outlet shape. This pins that the
      // Payment-tab changes did not disturb it.
      final backend = _Backend(const ['PAY_AT_PICKUP']);
      final cart = _cartWithItems(const ['PAY_AT_PICKUP']);
      await _openCheckout(tester, cart, backend);

      expect(find.byKey(const Key('schedule_toggle')), findsNothing);
      expect(find.text('When do you want it?'), findsNothing);
    });
  });
}
