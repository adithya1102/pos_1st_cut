// Home's "N orders in progress" row goes to the ORDER, not to the list.
//
// The bug: `_ActiveOrdersLink` and the "Order history" card below it were both
// handed the same `onHistory` callback, so the two rows were duplicates. A
// customer standing at a counter who tapped "1 order in progress" to get their
// pickup code landed on the history list and had to find and tap the order a
// second time — which is exactly the three-taps-deep problem the active-order
// surfaces were added to remove.
//
// These tests assert the DESTINATION of each row, not the wiring that produces
// it, so the fix can be refactored without rewriting them.
import 'dart:convert';

import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:http/http.dart' as http;
import 'package:http/testing.dart';
import 'package:provider/provider.dart';
import 'package:shared_preferences/shared_preferences.dart';

import 'package:customer_app/screens/home_screen.dart';
import 'package:customer_app/screens/order_history_screen.dart';
import 'package:customer_app/screens/pickup_screen.dart';
import 'package:customer_app/services/api_client.dart';
import 'package:customer_app/services/catalog_service.dart';
import 'package:customer_app/services/customer_service.dart';
import 'package:customer_app/services/google_auth_service.dart';
import 'package:customer_app/services/location_service.dart';
import 'package:customer_app/services/order_service.dart';
import 'package:customer_app/services/otp_auth_service.dart';
import 'package:customer_app/services/push_service.dart';
import 'package:customer_app/state/auth_state.dart';
import 'package:customer_app/state/cart_state.dart';
import 'package:customer_app/theme/app_theme.dart';
import 'package:customer_app/theme/theme_provider.dart';

http.Response _json(Object body, {int status = 200}) =>
    http.Response(jsonEncode(body), status,
        headers: {'content-type': 'application/json'});

Map<String, dynamic> _order({
  required String id,
  String status = 'READY',
  required String code,
  String outlet = 'Test Kitchen',
  double amount = 220,
}) =>
    {
      'order_id': id,
      'id': id,
      'status': status,
      'outlet_name': outlet,
      'payment_status': 'PAID',
      'total_amount': amount,
      'discount_amount': 0,
      'created_at': DateTime.now().toIso8601String(),
      'pickup_code': code,
      'items': [
        {'name': 'Dosa', 'quantity': 1, 'line_total': amount}
      ],
    };

/// Home, with a backend that answers both the history list and the per-order
/// detail the pickup screen polls.
Widget _host(List<Map<String, dynamic>> orders) {
  SharedPreferences.setMockInitialValues({'carevo_access_token': 'valid'});
  final api = ApiClient(client: MockClient((req) async {
    final path = req.url.path;
    // Detail first: '/customer/orders/o1' also contains '/customer/orders'.
    if (path.contains('/customer/orders/')) {
      final id = path.split('/').last;
      final match = orders.firstWhere((o) => o['order_id'] == id,
          orElse: () => orders.first);
      return _json(match);
    }
    if (path.endsWith('/customer/orders')) return _json(orders);
    if (path.endsWith('/customer/me')) {
      return _json({'id': 'c1', 'name': 'Asha', 'phone_number': '+919876543210'});
    }
    return _json(const {});
  }));

  return MultiProvider(
    providers: [
      Provider<ApiClient>.value(value: api),
      Provider<CustomerService>(create: (_) => CustomerService(api)),
      Provider<CatalogService>(create: (_) => CatalogService(api)),
      Provider<OrderService>(create: (_) => OrderService(api)),
      ChangeNotifierProvider<LocationService>(create: (_) => LocationService()),
      ChangeNotifierProvider<CartState>(create: (_) => CartState()),
      ChangeNotifierProvider<ThemeProvider>(create: (_) => ThemeProvider()),
      ChangeNotifierProvider<AuthState>(
        create: (_) => AuthState(
            api, StubOtpService(api), GoogleAuthService(api), PushService(api)),
      ),
    ],
    child: MaterialApp(theme: AppTheme.light(), home: const HomeScreen()),
  );
}

void main() {
  // Roomy surface: the pickup screen's status stepper lays out with GoogleFonts,
  // which cannot fetch a webfont under `flutter test`, so it measures wider here
  // than on a device. Same allowance the other pickup-screen tests make.
  void sizeSurface(WidgetTester tester) {
    tester.view.physicalSize = const Size(1600, 3200);
    tester.view.devicePixelRatio = 2.0;
    addTearDown(tester.view.reset);
  }

  group('Home — "in progress" opens the order, "Order history" opens the list',
      () {
    testWidgets('one active order goes straight to ITS pickup screen',
        (tester) async {
      sizeSurface(tester);
      await tester.pumpWidget(_host([_order(id: 'o1', code: '4821')]));
      await tester.pump(const Duration(milliseconds: 600));

      expect(find.text('1 order in progress'), findsOneWidget);
      await tester.tap(find.byKey(const Key('home_active_orders_link')));
      await tester.pump();
      await tester.pump(const Duration(milliseconds: 600));

      expect(find.byType(PickupScreen), findsOneWidget);
      // The regression: this used to be the history list.
      expect(find.byType(OrderHistoryScreen), findsNothing);

      // ...and the RIGHT order — its code, live, without a second tap.
      final pickup = tester.widget<PickupScreen>(find.byType(PickupScreen));
      expect(pickup.orderId, 'o1');
      expect(find.text('4821'), findsOneWidget);
      // Reached from a list, so it must be escapable.
      expect(pickup.fromHistory, isTrue);
    });

    testWidgets('the correct order when it is not the only one on record',
        (tester) async {
      // One live, one already collected. Picking `orders.first` blindly would
      // still pass with a single-order fixture; this one fails unless the
      // ACTIVE order is the one opened.
      sizeSurface(tester);
      await tester.pumpWidget(_host([
        _order(id: 'done', status: 'COMPLETED', code: '1111'),
        _order(id: 'live', status: 'PREPARING', code: '2222'),
      ]));
      await tester.pump(const Duration(milliseconds: 600));

      await tester.tap(find.byKey(const Key('home_active_orders_link')));
      await tester.pump();
      await tester.pump(const Duration(milliseconds: 600));

      expect(tester.widget<PickupScreen>(find.byType(PickupScreen)).orderId,
          'live');
    });

    testWidgets('"Order history" still opens the list — a DIFFERENT route',
        (tester) async {
      sizeSurface(tester);
      await tester.pumpWidget(_host([_order(id: 'o1', code: '4821')]));
      await tester.pump(const Duration(milliseconds: 600));

      await tester.tap(find.byKey(const Key('home_history_shortcut')));
      await tester.pump();
      await tester.pump(const Duration(milliseconds: 600));

      expect(find.byType(OrderHistoryScreen), findsOneWidget);
      expect(find.byType(PickupScreen), findsNothing);
    });

    testWidgets('several live at once keeps going to the list, and says so',
        (tester) async {
      // With more than one in flight there is no single right order to open, so
      // the row deliberately still opens history — which floats the active ones
      // to the top and opens the same pickup screen per row. Guessing one here
      // would be wrong often enough to be worse than the extra tap.
      sizeSurface(tester);
      await tester.pumpWidget(_host([
        _order(id: 'a', status: 'READY', code: '1111'),
        _order(id: 'b', status: 'PREPARING', code: '2222'),
      ]));
      await tester.pump(const Duration(milliseconds: 600));

      expect(find.text('2 orders in progress'), findsOneWidget);
      expect(find.text('View order history'), findsOneWidget);

      await tester.tap(find.byKey(const Key('home_active_orders_link')));
      await tester.pump();
      await tester.pump(const Duration(milliseconds: 600));

      expect(find.byType(OrderHistoryScreen), findsOneWidget);
      expect(find.byType(PickupScreen), findsNothing);
    });

    testWidgets('the row names the destination it actually has',
        (tester) async {
      sizeSurface(tester);
      await tester.pumpWidget(_host([_order(id: 'o1', code: '4821')]));
      await tester.pump(const Duration(milliseconds: 600));

      // One order opens the order, so it must not advertise the list.
      expect(find.text('Track order'), findsOneWidget);
      expect(find.text('View order history'), findsNothing);
    });
  });
}
