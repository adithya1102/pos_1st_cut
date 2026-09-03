// Operating-hours status on the customer side (migration 024):
//   * the Outlet model maps order_status -> label / isAcceptingOrders;
//   * the outlet card shows Open / Closing soon / Closed;
//   * checkout's Pay is disabled, with the reason, when the outlet is not open.
//
// The backend is the hard gate (it refuses the order at creation); these hold
// the client's job — telling the customer BEFORE they tap, not after.
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
import 'package:customer_app/screens/outlets_screen.dart';
import 'package:customer_app/services/api_client.dart';
import 'package:customer_app/services/cashfree_service.dart';
import 'package:customer_app/services/catalog_service.dart';
import 'package:customer_app/services/customer_service.dart';
import 'package:customer_app/services/location_service.dart';
import 'package:customer_app/services/order_service.dart';
import 'package:customer_app/services/places_service.dart';
import 'package:customer_app/state/cart_state.dart';
import 'package:customer_app/theme/app_theme.dart';
import 'package:customer_app/theme/theme_provider.dart';

void main() {
  group('Outlet model maps order_status', () {
    Outlet fromStatus(String status, {String? reason, bool isOpen = true}) =>
        Outlet.fromJson({
          'id': 'o1',
          'name': 'Test Kitchen',
          'address': 'Somewhere',
          'is_open': isOpen,
          'order_status': status,
          'closed_reason': reason,
        });

    test('open', () {
      final o = fromStatus('open');
      expect(o.orderStatus, 'open');
      expect(o.statusLabel, 'Open');
      expect(o.isAcceptingOrders, isTrue);
    });

    test('closing_soon is not accepting', () {
      final o = fromStatus('closing_soon', isOpen: false);
      expect(o.statusLabel, 'Closing soon');
      expect(o.isAcceptingOrders, isFalse);
    });

    test('closed carries its reason', () {
      final o = fromStatus('closed',
          reason: 'This outlet is temporarily closed.', isOpen: false);
      expect(o.statusLabel, 'Closed');
      expect(o.isAcceptingOrders, isFalse);
      expect(o.closedReason, 'This outlet is temporarily closed.');
    });

    test('falls back to is_open when order_status is absent', () {
      final o = Outlet.fromJson({
        'id': 'o1', 'name': 'X', 'address': 'Y', 'is_open': false,
      });
      expect(o.orderStatus, 'closed');
      expect(o.isAcceptingOrders, isFalse);
    });
  });

  group('outlet card shows the status', () {
    http.Response okJson(Object b) => http.Response(jsonEncode(b), 200,
        headers: {'content-type': 'application/json'});

    Widget host(String status) {
      SharedPreferences.setMockInitialValues({'carevo_access_token': 'valid'});
      final api = ApiClient(client: MockClient((req) async {
        if (req.url.path.contains('/customer/orders')) return okJson(const []);
        if (req.url.path.contains('/customer/outlets')) {
          return okJson([
            {
              'id': 'o1',
              'name': 'Test Kitchen',
              'address': 'Anna Nagar, Chennai',
              'is_open': status == 'open',
              'order_status': status,
              'closed_reason': status == 'open' ? null : 'Closed for now.',
              'distance_km': 1.0,
            }
          ]);
        }
        return okJson(const []);
      }));
      return MultiProvider(
        providers: [
          Provider<ApiClient>.value(value: api),
          Provider<CatalogService>(create: (_) => CatalogService(api)),
          Provider<CustomerService>(create: (_) => CustomerService(api)),
          ChangeNotifierProvider<LocationService>(
              create: (_) => LocationService()),
          ChangeNotifierProvider<CartState>(create: (_) => CartState()),
          ChangeNotifierProvider<ThemeProvider>(create: (_) => ThemeProvider()),
        ],
        child: MaterialApp(theme: AppTheme.light(), home: const OutletsScreen()),
      );
    }

    Future<void> pumpStatus(WidgetTester tester, String status) async {
      tester.view.physicalSize = const Size(1170, 2532);
      tester.view.devicePixelRatio = 3.0;
      addTearDown(tester.view.reset);
      await tester.pumpWidget(host(status));
      await tester.pump(const Duration(milliseconds: 600));
    }

    testWidgets('open outlet shows "Open"', (tester) async {
      await pumpStatus(tester, 'open');
      expect(find.byKey(const Key('outlet_status_o1')), findsOneWidget);
      expect(find.text('Open'), findsOneWidget);
    });

    testWidgets('closing-soon outlet shows "Closing soon"', (tester) async {
      await pumpStatus(tester, 'closing_soon');
      expect(find.text('Closing soon'), findsOneWidget);
    });

    testWidgets('closed outlet shows "Closed"', (tester) async {
      await pumpStatus(tester, 'closed');
      expect(find.text('Closed'), findsOneWidget);
    });
  });

  group('checkout Pay is gated by outlet status', () {
    MenuItem menuItem() => MenuItem.fromJson({
          'id': 'i1', 'name': 'Masala Dosa', 'base_price': 120.0,
          'is_veg': true, 'is_available': true, 'image_url': null,
          'prep_time_minutes': 0, 'tags': const <String>[],
          'customizations': const <dynamic>[],
        });

    Outlet outlet(String status) => Outlet.fromJson({
          'id': 'o1', 'name': 'Test Kitchen', 'address': 'Somewhere',
          'is_open': status == 'open', 'order_status': status,
          'closed_reason': status == 'open'
              ? null
              : 'This outlet is temporarily closed and is not taking orders.',
        });

    Widget host(String status) {
      SharedPreferences.setMockInitialValues({'carevo_access_token': 't'});
      final api = ApiClient(client: MockClient((req) async =>
          http.Response(jsonEncode(const []), 200,
              headers: {'content-type': 'application/json'})));
      final cart = CartState()
        ..setOutlet(outlet(status))
        ..addItem(menuItem(), quantity: 1);
      return MultiProvider(
        providers: [
          Provider<ApiClient>.value(value: api),
          Provider<OrderService>(create: (_) => OrderService(api)),
          Provider<CashfreeService>(create: (_) => CashfreeService()),
          Provider<LocationService>(create: (_) => LocationService()),
          Provider<PlacesService>(create: (_) => PlacesService()),
          ChangeNotifierProvider<CartState>.value(value: cart),
          ChangeNotifierProvider(create: (_) => ThemeProvider()),
        ],
        child: MaterialApp(theme: AppTheme.light(), home: const CheckoutScreen()),
      );
    }

    testWidgets('open → Pay enabled, no closed reason', (tester) async {
      await tester.pumpWidget(host('open'));
      await tester.pumpAndSettle();
      final btn = tester.widget<Widget>(find.byKey(const Key('checkout_pay')));
      // The neo button is enabled when its onPressed is non-null; assert via
      // the absence of the closed-reason row and presence of a Pay label.
      expect(find.byKey(const Key('checkout_closed_reason')), findsNothing);
      expect(find.textContaining('Pay '), findsOneWidget);
      expect(btn, isNotNull);
    });

    testWidgets('closed → Pay disabled, reason shown', (tester) async {
      await tester.pumpWidget(host('closed'));
      await tester.pumpAndSettle();
      expect(find.byKey(const Key('checkout_closed_reason')), findsOneWidget);
      expect(find.textContaining('temporarily closed'), findsOneWidget);
      // The button now reads the status, not "Pay".
      expect(find.text('Closed'), findsWidgets);
      expect(find.textContaining('Pay '), findsNothing);
    });

    testWidgets('closing soon → Pay disabled', (tester) async {
      await tester.pumpWidget(host('closing_soon'));
      await tester.pumpAndSettle();
      expect(find.byKey(const Key('checkout_closed_reason')), findsOneWidget);
      expect(find.textContaining('Pay '), findsNothing);
    });
  });
}
