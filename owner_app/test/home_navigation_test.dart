// Bottom-bar order and the landing tab.
//
// Two decisions worth holding, because both are invisible to every other test
// and both are one integer away from silently regressing:
//
//   1. ORDERS IS WHERE THE APP OPENS. It is the only time-critical tab — a
//      queue of paying customers — so it is what a picked-up phone shows.
//   2. MENU IS THE CENTRE DESTINATION, reachable by thumb from either side.
//
// The tab index used to be a bare integer at six sites (initial value, two
// "jump to Orders" jumps, the app-bar outlet toggle, the FAB switch, the
// destination list). Reordering meant finding all six by hand, and a missed
// one puts a control on the wrong tab rather than failing loudly — so the
// per-tab control assertions below are as much the point as the order itself.
import 'dart:convert';

import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:http/http.dart' as http;
import 'package:http/testing.dart';
import 'package:provider/provider.dart';
import 'package:shared_preferences/shared_preferences.dart';

import 'package:owner_app/screens/home_screen.dart';
import 'package:owner_app/services/api_client.dart';
import 'package:owner_app/services/auth_service.dart';
import 'package:owner_app/services/menu_service.dart';
import 'package:owner_app/services/offer_service.dart';
import 'package:owner_app/services/order_service.dart';
import 'package:owner_app/services/outlet_service.dart';
import 'package:owner_app/services/staff_push_service.dart';
import 'package:owner_app/state/auth_state.dart';
import 'package:owner_app/state/home_state.dart';
import 'package:owner_app/state/offers_state.dart';
import 'package:owner_app/state/orders_state.dart';

/// A quiet backend: every owner endpoint answers, nothing arrives.
http.Client _backend() {
  http.Response json(Object b) => http.Response(jsonEncode(b), 200,
      headers: {'content-type': 'application/json'});

  return MockClient((req) async {
    final path = req.url.path;
    if (path.endsWith('/pos/outlet')) {
      return json({
        'id': 'aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee',
        'location_name': 'Anand Bhavan',
        'is_visible': true,
        'image_url': null,
      });
    }
    if (path.endsWith('/pos/orders') ||
        path.endsWith('/pos/menu-items') ||
        path.endsWith('/pos/offers')) {
      return json(const <dynamic>[]);
    }
    return http.Response(jsonEncode({'detail': 'unexpected ${req.url}'}), 404,
        headers: {'content-type': 'application/json'});
  });
}

Widget _host() {
  SharedPreferences.setMockInitialValues({'gusto_owner_access_token': 'staff'});
  final api = ApiClient(httpClient: _backend());
  return MultiProvider(
    providers: [
      ChangeNotifierProvider(create: (_) => AuthState(AuthService(api))),
      ChangeNotifierProvider(
        create: (_) => HomeState(OutletService(api), MenuService(api)),
      ),
      ChangeNotifierProvider(create: (_) => OrdersState(OrderService(api))),
      ChangeNotifierProvider(create: (_) => OffersState(OfferService(api))),
      Provider(create: (_) => StaffPushService(OrderService(api))),
    ],
    child: const MaterialApp(home: HomeScreen()),
  );
}

/// Unmounting stops the orders poll timer — a live timer at teardown fails.
Future<void> _close(WidgetTester tester) async {
  await tester.pumpWidget(const SizedBox.shrink());
  await tester.pumpAndSettle();
}

/// The section label under the outlet name in the app bar.
Finder _appBarSection(String label) => find.descendant(
      of: find.byType(AppBar),
      matching: find.text(label),
    );

Future<void> _openTab(WidgetTester tester, String label) async {
  await tester.tap(find.widgetWithText(NavigationDestination, label));
  await tester.pumpAndSettle();
}

void main() {
  testWidgets('the app opens on Orders', (tester) async {
    await tester.pumpWidget(_host());
    await tester.pumpAndSettle();

    expect(_appBarSection('Orders'), findsOneWidget,
        reason: 'a picked-up phone must show the queue, not the menu editor');

    await _close(tester);
  });

  testWidgets('Menu is the centre destination', (tester) async {
    await tester.pumpWidget(_host());
    await tester.pumpAndSettle();

    final labels = tester
        .widgetList<NavigationDestination>(find.byType(NavigationDestination))
        .map((d) => d.label)
        .toList();

    expect(labels, ['Orders', 'Menu', 'Offers']);
    // Stated separately from the list above: this is the actual requirement,
    // and it should still read as satisfied if a fourth tab ever appears and
    // the literal list has to change.
    expect(labels[labels.length ~/ 2], 'Menu');

    await _close(tester);
  });

  testWidgets('the selected destination follows the tab', (tester) async {
    await tester.pumpWidget(_host());
    await tester.pumpAndSettle();

    NavigationBar bar() => tester.widget<NavigationBar>(find.byType(NavigationBar));
    expect(bar().selectedIndex, 0, reason: 'Orders is index 0 and is selected');

    await _openTab(tester, 'Menu');
    expect(bar().selectedIndex, 1);

    await _openTab(tester, 'Offers');
    expect(bar().selectedIndex, 2);

    await _close(tester);
  });

  testWidgets('every tab shows its own section title', (tester) async {
    await tester.pumpWidget(_host());
    await tester.pumpAndSettle();

    await _openTab(tester, 'Menu');
    expect(_appBarSection('Menu & Outlet'), findsOneWidget);

    await _openTab(tester, 'Offers');
    expect(_appBarSection('Offers'), findsOneWidget);

    await _openTab(tester, 'Orders');
    expect(_appBarSection('Orders'), findsOneWidget);

    await _close(tester);
  });

  group('the per-tab controls moved with the tabs', () {
    testWidgets('"Add dish" is on Menu, not on the landing tab',
        (tester) async {
      // The regression the named constants exist to prevent: the FAB switch
      // still keyed on 0, so "Add dish" would sit on Orders.
      await tester.pumpWidget(_host());
      await tester.pumpAndSettle();

      expect(find.text('Add dish'), findsNothing,
          reason: 'Orders is the landing tab and has no dish FAB');

      await _openTab(tester, 'Menu');
      expect(find.text('Add dish'), findsOneWidget);

      await _close(tester);
    });

    testWidgets('"Create offer" is on Offers', (tester) async {
      await tester.pumpWidget(_host());
      await tester.pumpAndSettle();
      expect(find.text('Create offer'), findsNothing);

      await _openTab(tester, 'Offers');
      expect(find.text('Create offer'), findsOneWidget);

      await _close(tester);
    });

    testWidgets('the outlet visibility switch rides with Menu', (tester) async {
      // Same class of bug as the FAB: an outlet control left behind on the
      // tab that used to be index 0.
      await tester.pumpWidget(_host());
      await tester.pumpAndSettle();

      expect(find.byType(Switch), findsNothing,
          reason: 'the visibility switch is an outlet control, not an order one');

      await _openTab(tester, 'Menu');
      expect(find.byType(Switch), findsOneWidget);

      await _close(tester);
    });
  });
}
