// CASHFREE_ONLY (backend config.py) — when the platform switch is on,
// payment_methods_for (backend) returns at most ['PREPAID'] for every
// outlet. This file proves the customer app, which is already server-driven
// (see payment_methods_test.dart), renders exactly that shape correctly:
// "Pay online" and nothing else — no pickup or UPI option ever appears,
// because the server never lists them. No change to checkout_screen.dart's
// rendering logic was needed for this — _buildPaymentSection already draws
// exactly the server's list; this file pins that it stays true for the
// single-method shape CASHFREE_ONLY produces.
import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:provider/provider.dart';
import 'package:shared_preferences/shared_preferences.dart';

import 'package:customer_app/models/menu.dart';
import 'package:customer_app/models/outlet.dart';
import 'package:customer_app/screens/checkout_screen.dart';
import 'package:customer_app/services/api_client.dart';
import 'package:customer_app/services/cashfree_service.dart';
import 'package:customer_app/services/location_service.dart';
import 'package:customer_app/services/order_service.dart';
import 'package:customer_app/state/cart_state.dart';
import 'package:customer_app/theme/app_theme.dart';
import 'package:customer_app/theme/theme_provider.dart';

Outlet _outlet({required List<String> methods}) => Outlet.fromJson({
      'id': 'out-1',
      'name': 'Test Kitchen',
      'address': 'Koramangala, Bengaluru',
      'is_open': true,
      'order_status': 'open',
      'latitude': 12.9716,
      'longitude': 77.5946,
      'payment_methods': methods,
    });

MenuItem _menuItem() => MenuItem.fromJson({
      'id': 'item-1',
      'name': 'Masala Dosa',
      'base_price': 120,
      'is_veg': true,
      'is_available': true,
    });

CartState _cartFor(List<String> methods) {
  final cart = CartState();
  cart.setOutlet(_outlet(methods: methods));
  cart.addItem(_menuItem(), quantity: 2);
  return cart;
}

class _NoopCashfree implements CashfreeService {
  @override
  Future<CheckoutResult> openCheckout({
    required String orderId,
    required String paymentSessionId,
  }) async =>
      const CheckoutResult(CheckoutOutcome.verified);
}

Widget _checkoutHost(CartState cart) {
  SharedPreferences.setMockInitialValues({'carevo_access_token': 't'});
  final api = ApiClient(client: null); // never called — no tap in these tests
  return MultiProvider(
    providers: [
      Provider<ApiClient>.value(value: api),
      Provider<OrderService>(create: (_) => OrderService(api)),
      Provider<CashfreeService>.value(value: _NoopCashfree()),
      Provider<LocationService>(create: (_) => LocationService()),
      ChangeNotifierProvider<CartState>.value(value: cart),
      ChangeNotifierProvider(create: (_) => ThemeProvider()),
    ],
    child: MaterialApp(theme: AppTheme.light(), home: const CheckoutScreen()),
  );
}

/// The payment section sits far down checkout's scrollable body, so a lazily
/// built list never constructs it without being scrolled there first.
Future<void> _scrollToPayment(WidgetTester tester, Key target) async {
  await tester.scrollUntilVisible(find.byKey(target), 300,
      scrollable: find.byType(Scrollable).first);
  await tester.pumpAndSettle();
}

void main() {
  testWidgets('CASHFREE_ONLY shape (["PREPAID"]) shows only Pay online',
      (tester) async {
    await tester.pumpWidget(_checkoutHost(_cartFor(const ['PREPAID'])));
    await tester.pumpAndSettle();
    await _scrollToPayment(tester, const Key('payment_method_PREPAID'));

    expect(find.byKey(const Key('payment_method_PREPAID')), findsOneWidget);
    expect(find.text('Pay online'), findsOneWidget);
    expect(find.byKey(const Key('payment_method_PAY_AT_PICKUP')),
        findsNothing);
    expect(find.byKey(const Key('payment_method_UPI_MANUAL')), findsNothing);
    expect(find.text('Pay at pickup'), findsNothing);
    expect(find.text('Pay by UPI'), findsNothing);
  });

  testWidgets('switch off (list carries pickup+upi too) still shows them — '
      'unchanged', (tester) async {
    await tester.pumpWidget(_checkoutHost(
        _cartFor(const ['PREPAID', 'PAY_AT_PICKUP', 'UPI_MANUAL'])));
    await tester.pumpAndSettle();
    await _scrollToPayment(tester, const Key('payment_method_PREPAID'));

    expect(find.byKey(const Key('payment_method_PREPAID')), findsOneWidget);
    expect(
        find.byKey(const Key('payment_method_PAY_AT_PICKUP')), findsOneWidget);
    expect(find.byKey(const Key('payment_method_UPI_MANUAL')), findsOneWidget);
  });
}
