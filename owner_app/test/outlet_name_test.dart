// Which restaurant is this phone signed into?
//
// Several test devices run the owner app side by side, each logged into a
// different outlet, and every screen in the app is otherwise identical. The
// outlet name in the app bar is the only thing that tells them apart, so these
// tests hold two lines: the name is on screen after login, and it is the name
// the SERVER returned for this account rather than anything cached or guessed.
//
// The whole tree is driven over a MockClient — real HomeState, real
// OutletService, real JSON — because a fake state object would only prove the
// widget reads a getter, not that `location_name` survives the round trip.
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

/// A backend for one signed-in outlet. Only `/pos/outlet` differs between
/// accounts, which is exactly the situation on the bench: same app, same menu
/// shape, different restaurant.
http.Client _backend({
  required String outletName,
  bool outletFails = false,
}) {
  return MockClient((req) async {
    final path = req.url.path;

    if (path.endsWith('/pos/outlet')) {
      if (outletFails) {
        return http.Response(jsonEncode({'detail': 'boom'}), 500,
            headers: {'content-type': 'application/json'});
      }
      return http.Response(
          jsonEncode({
            'id': 'aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee',
            'location_name': outletName,
            'is_visible': true,
            'image_url': null,
          }),
          200,
          headers: {'content-type': 'application/json'});
    }

    // Everything else the home screen pulls on mount. Empty is fine — none of
    // it is what these tests are about.
    if (path.endsWith('/pos/menu-items') ||
        path.endsWith('/pos/orders') ||
        path.endsWith('/pos/offers')) {
      return http.Response(jsonEncode(<dynamic>[]), 200,
          headers: {'content-type': 'application/json'});
    }

    return http.Response(jsonEncode({'detail': 'unexpected ${req.url}'}), 404,
        headers: {'content-type': 'application/json'});
  });
}

Widget _host(http.Client backend) {
  SharedPreferences.setMockInitialValues({'gusto_owner_access_token': 'staff'});
  final api = ApiClient(httpClient: backend);
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

/// Unmounts the tree at the end of a test.
///
/// Not just tidiness: HomeScreen starts the orders poll on mount, and
/// flutter_test fails any test that finishes with a live timer. So this doubles
/// as the assertion that [HomeScreen.dispose] actually stops polling — remove
/// the `stopPolling()` from dispose and every test in this file fails.
Future<void> _close(WidgetTester tester) async {
  await tester.pumpWidget(const SizedBox.shrink());
  await tester.pumpAndSettle();
}

void main() {
  testWidgets('the outlet name is in the app bar after login', (tester) async {
    await tester.pumpWidget(_host(_backend(outletName: 'Anand Bhavan')));
    await tester.pumpAndSettle();

    expect(find.byKey(HomeScreen.outletNameKey), findsOneWidget);
    expect(
      tester.widget<Text>(find.byKey(HomeScreen.outletNameKey)).data,
      'Anand Bhavan',
    );
    await _close(tester);
  });

  testWidgets('it is the app bar, not something buried in a tab',
      (tester) async {
    await tester.pumpWidget(_host(_backend(outletName: 'Anand Bhavan')));
    await tester.pumpAndSettle();

    // Inside the AppBar specifically: a name that only appears once you scroll
    // a tab does not answer "which phone is which" at a glance.
    expect(
      find.descendant(
        of: find.byType(AppBar),
        matching: find.byKey(HomeScreen.outletNameKey),
      ),
      findsOneWidget,
    );
    // The section label survives alongside it — the name is added context, not
    // a replacement for knowing which tab you are on.
    expect(
      find.descendant(
        of: find.byType(AppBar),
        matching: find.text('Menu & Outlet'),
      ),
      findsOneWidget,
    );
    await _close(tester);
  });

  testWidgets('two accounts are told apart by it', (tester) async {
    // The actual scenario: the same build on two phones. Nothing about the app
    // is different except the account, so if this name were hardcoded or stale
    // the two devices would be indistinguishable.
    await tester.pumpWidget(_host(_backend(outletName: 'Anand Bhavan')));
    await tester.pumpAndSettle();
    expect(find.text('Anand Bhavan'), findsOneWidget);

    // Torn down between the two: the second phone is a separate launch of the
    // app, not a rebuild of the first. Keeping the tree alive would reuse the
    // already-created providers and quietly test nothing.
    await _close(tester);

    await tester.pumpWidget(_host(_backend(outletName: 'Cafe Mocha')));
    await tester.pumpAndSettle();
    expect(find.text('Cafe Mocha'), findsOneWidget);
    expect(find.text('Anand Bhavan'), findsNothing);
    await _close(tester);
  });

  testWidgets('the name follows the tab, so it is never off screen',
      (tester) async {
    await tester.pumpWidget(_host(_backend(outletName: 'Anand Bhavan')));
    await tester.pumpAndSettle();

    await tester.tap(find.text('Orders'));
    await tester.pumpAndSettle();

    expect(find.byKey(HomeScreen.outletNameKey), findsOneWidget);
    expect(find.text('Anand Bhavan'), findsOneWidget);
    expect(
      find.descendant(of: find.byType(AppBar), matching: find.text('Orders')),
      findsOneWidget,
    );
    await _close(tester);
  });

  testWidgets('a failed outlet load shows no name rather than a fake one',
      (tester) async {
    // Showing a placeholder here would be worse than showing nothing: a name
    // that is not the account's is precisely the mistake this feature exists
    // to prevent.
    await tester.pumpWidget(_host(_backend(outletName: 'x', outletFails: true)));
    await tester.pumpAndSettle();

    expect(find.byKey(HomeScreen.outletNameKey), findsNothing);
    expect(
      find.descendant(
        of: find.byType(AppBar),
        matching: find.text('Menu & Outlet'),
      ),
      findsOneWidget,
    );
    await _close(tester);
  });
}
