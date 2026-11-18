// The CLOSED menu view (backend migration 024, surfaced on the menu screen).
//
// The menu is still shown in full when a restaurant is closed, and that is the
// decision under test: a customer who opened a restaurant wants to know what it
// serves whether or not it is serving right now, and a blank screen or a bounce
// back to the list cannot tell them "closed" apart from "broken". So the
// content stays and loses its colour.
//
// THE THREE THAT MATTER MOST
// --------------------------
//  * The dish screen does not open when closed, and the refusal lands BEFORE
//    the outlet-switch prompt — a closed restaurant must never be the reason a
//    customer is asked to discard a cart they built somewhere open.
//  * The "Closed" label sits OUTSIDE the greyscale filter, so the one thing
//    explaining the grey keeps its own colour.
//  * 'closing_soon' is untouched. The server still accepts a SCHEDULED pickup
//    in that window, so greying the menu would block an order the backend
//    would have taken.
import 'dart:convert';

import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:http/http.dart' as http;
import 'package:http/testing.dart';
import 'package:provider/provider.dart';
import 'package:shared_preferences/shared_preferences.dart';

import 'package:customer_app/models/outlet.dart';
import 'package:customer_app/screens/dish_detail_screen.dart';
import 'package:customer_app/screens/menu_screen.dart';
import 'package:customer_app/services/api_client.dart';
import 'package:customer_app/services/catalog_service.dart';
import 'package:customer_app/services/customer_service.dart';
import 'package:customer_app/services/location_service.dart';
import 'package:customer_app/state/cart_state.dart';
import 'package:customer_app/theme/app_theme.dart';
import 'package:customer_app/theme/theme_provider.dart';

Outlet _outlet(String status, {String? reason}) => Outlet.fromJson({
      'id': 'o1',
      'name': 'Test Kitchen',
      'address': 'Anna Nagar, Chennai',
      'is_open': status == 'open',
      'order_status': status,
      'closed_reason': reason,
    });

/// A two-dish menu, so the list has rows to grey out and tap.
Map<String, dynamic> _menuBody() => {
      'outlet_id': 'o1',
      'payment_methods': ['PREPAID'],
      'categories': [
        {
          'id': 'c1',
          'name': 'Mains',
          'items': [
            {
              'id': 'd1',
              'name': 'Masala Dosa',
              'base_price': 80,
              'is_veg': true,
              'is_available': true,
              'prep_time_minutes': 10,
            },
            {
              'id': 'd2',
              'name': 'Chicken Biryani',
              'base_price': 220,
              'is_veg': false,
              'is_available': true,
              'prep_time_minutes': 20,
            },
          ],
        },
      ],
    };

Widget _host(Outlet outlet) {
  SharedPreferences.setMockInitialValues({'carevo_access_token': 'valid'});
  final api = ApiClient(client: MockClient((req) async {
    http.Response okJson(Object b) => http.Response(jsonEncode(b), 200,
        headers: {'content-type': 'application/json'});
    if (req.url.path.contains('/customer/menu')) return okJson(_menuBody());
    return okJson(const []);
  }));
  return MultiProvider(
    providers: [
      Provider<ApiClient>.value(value: api),
      Provider<CatalogService>(create: (_) => CatalogService(api)),
      Provider<CustomerService>(create: (_) => CustomerService(api)),
      ChangeNotifierProvider<LocationService>(create: (_) => LocationService()),
      ChangeNotifierProvider<CartState>(create: (_) => CartState()),
      ChangeNotifierProvider<ThemeProvider>(create: (_) => ThemeProvider()),
    ],
    child: MaterialApp(
      theme: AppTheme.light(),
      home: MenuScreen(outlet: outlet),
    ),
  );
}

Future<void> _pump(WidgetTester tester, Outlet outlet) async {
  tester.view.physicalSize = const Size(1170, 2532);
  tester.view.devicePixelRatio = 3.0;
  addTearDown(tester.view.reset);
  await tester.pumpWidget(_host(outlet));
  await tester.pumpAndSettle();
}

Finder get _banner => find.byKey(const Key('menu_closed_banner'));
Finder get _greyscale => find.byKey(const Key('menu_greyscale'));

void main() {
  group('a closed outlet', () {
    testWidgets('shows a Closed label with the server reason', (tester) async {
      await _pump(
        tester,
        _outlet('closed', reason: 'This outlet is temporarily closed.'),
      );

      expect(_banner, findsOneWidget);
      expect(find.text('Closed'), findsOneWidget);
      expect(find.text('This outlet is temporarily closed.'), findsOneWidget);
    });

    testWidgets('falls back to a plain line when there is no reason',
        (tester) async {
      await _pump(tester, _outlet('closed'));

      expect(find.text('Closed'), findsOneWidget);
      expect(
        find.text('This restaurant is not taking orders right now.'),
        findsOneWidget,
        reason: 'a bare label with no explanation is worse than a generic one',
      );
    });

    testWidgets('greys the menu but still shows every dish', (tester) async {
      await _pump(tester, _outlet('closed'));

      expect(_greyscale, findsOneWidget);
      // The menu is NOT hidden — that is the whole point of greying it.
      expect(find.text('Masala Dosa'), findsOneWidget);
      expect(find.text('Chicken Biryani'), findsOneWidget);
    });

    testWidgets('the Closed label is outside the greyscale filter',
        (tester) async {
      await _pump(tester, _outlet('closed'));

      expect(
        find.descendant(of: _greyscale, matching: _banner),
        findsNothing,
        reason: 'the label explaining the grey must keep its own colour',
      );
    });

    testWidgets('tapping a dish says the outlet is closed and does not open it',
        (tester) async {
      await _pump(tester, _outlet('closed'));

      await tester.tap(find.text('Masala Dosa'));
      await tester.pumpAndSettle();

      expect(find.byKey(const Key('outlet_closed_notice')), findsOneWidget);
      expect(find.text('Test Kitchen is closed'), findsOneWidget);
      expect(find.byType(DishDetailScreen), findsNothing,
          reason: 'there is no order line to build at a closed restaurant');
    });

    testWidgets('the closed refusal pre-empts the outlet-switch prompt',
        (tester) async {
      // A cart bound to ANOTHER restaurant. Tapping a dish here must not ask
      // the customer to discard it — the restaurant is closed, so the question
      // would be pointless and the cart is the thing they would lose.
      SharedPreferences.setMockInitialValues({'carevo_access_token': 'valid'});
      final api = ApiClient(client: MockClient((req) async {
        http.Response okJson(Object b) => http.Response(jsonEncode(b), 200,
            headers: {'content-type': 'application/json'});
        if (req.url.path.contains('/customer/menu')) return okJson(_menuBody());
        return okJson(const []);
      }));
      final cart = CartState();
      cart.setOutlet(_outlet('open'));

      tester.view.physicalSize = const Size(1170, 2532);
      tester.view.devicePixelRatio = 3.0;
      addTearDown(tester.view.reset);

      await tester.pumpWidget(MultiProvider(
        providers: [
          Provider<ApiClient>.value(value: api),
          Provider<CatalogService>(create: (_) => CatalogService(api)),
          Provider<CustomerService>(create: (_) => CustomerService(api)),
          ChangeNotifierProvider<LocationService>(
              create: (_) => LocationService()),
          ChangeNotifierProvider<CartState>.value(value: cart),
          ChangeNotifierProvider<ThemeProvider>(create: (_) => ThemeProvider()),
        ],
        child: MaterialApp(
          theme: AppTheme.light(),
          // A DIFFERENT outlet id, so the cart would genuinely be at risk.
          home: MenuScreen(
            outlet: Outlet.fromJson({
              'id': 'o2',
              'name': 'Other Kitchen',
              'address': 'Elsewhere',
              'is_open': false,
              'order_status': 'closed',
              'closed_reason': 'Closed for now.',
            }),
          ),
        ),
      ));
      await tester.pumpAndSettle();

      await tester.tap(find.text('Masala Dosa'));
      await tester.pumpAndSettle();

      expect(find.text('Start a new order?'), findsNothing,
          reason: 'a closed outlet must never cost someone their cart');
      expect(find.byKey(const Key('outlet_closed_notice')), findsOneWidget);
    });
  });

  group('an open outlet is unchanged', () {
    testWidgets('no banner, no greyscale', (tester) async {
      await _pump(tester, _outlet('open'));

      expect(_banner, findsNothing);
      expect(_greyscale, findsNothing);
      expect(find.text('Masala Dosa'), findsOneWidget);
    });

    testWidgets('tapping a dish opens it', (tester) async {
      await _pump(tester, _outlet('open'));

      await tester.tap(find.text('Masala Dosa'));
      await tester.pumpAndSettle();

      expect(find.byType(DishDetailScreen), findsOneWidget);
      expect(find.byKey(const Key('outlet_closed_notice')), findsNothing);
    });
  });

  group('closing_soon is deliberately untouched', () {
    testWidgets('no banner and no greyscale', (tester) async {
      await _pump(
        tester,
        _outlet('closing_soon', reason: 'This outlet is closing soon.'),
      );

      expect(_banner, findsNothing,
          reason: 'a scheduled pickup is still accepted while closing soon');
      expect(_greyscale, findsNothing);
    });

    testWidgets('a dish still opens', (tester) async {
      await _pump(tester, _outlet('closing_soon'));

      await tester.tap(find.text('Masala Dosa'));
      await tester.pumpAndSettle();

      expect(find.byType(DishDetailScreen), findsOneWidget,
          reason: 'blocking this would refuse an order the server would take');
    });
  });
}
