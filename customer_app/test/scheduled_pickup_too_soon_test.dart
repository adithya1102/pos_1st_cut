// Task 2 — the customer-facing side of SCHEDULED_PICKUP_TOO_SOON.
//
// create_order answers 409 with `{error, message, earliest_pickup_at}`
// (gusto_pos/backend/.../carevo_customer/service.py:_assert_scheduled_
// release_feasible) whenever the kitchen cannot make the slot the customer
// chose. Before this file there was NO handling for this specific shape on
// the client: _payNow's ApiException catch just showed e.message as a plain
// SnackBar and left the customer to guess a new time themselves, with no way
// to accept the server's own suggestion in one tap.
//
// Three properties, one per test:
//   1. the 409 renders the earliest time, in plain words, in a dialog;
//   2. accepting it re-submits create_order with EXACTLY that instant;
//   3. the cart is never touched by any of this — createOrder failing, the
//      dialog, or the resubmission.
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
import 'package:customer_app/services/customer_service.dart';
import 'package:customer_app/services/location_service.dart';
import 'package:customer_app/services/order_service.dart';
import 'package:customer_app/services/places_service.dart';
import 'package:customer_app/state/cart_state.dart';
import 'package:customer_app/theme/app_theme.dart';
import 'package:customer_app/theme/theme_provider.dart';
import 'package:customer_app/widgets/arrival_time_picker.dart';

String _hhmm(DateTime t) =>
    '${t.hour.toString().padLeft(2, '0')}:${t.minute.toString().padLeft(2, '0')}';

MenuItem _menuItem() => MenuItem.fromJson({
      'id': 'i1', 'name': 'Masala Dosa', 'base_price': 120.0,
      'is_veg': true, 'is_available': true, 'image_url': null,
      'prep_time_minutes': 0, 'tags': const <String>[],
      'customizations': const <dynamic>[],
    });

Outlet _outlet() {
  final close = DateTime.now().add(const Duration(hours: 4));
  return Outlet.fromJson({
    'id': 'o1', 'name': 'Test Kitchen', 'address': 'Somewhere',
    'is_open': true, 'order_status': 'open',
    'opening_time': '09:00', 'closing_time': _hhmm(close),
  });
}

// The server's suggestion, well inside the outlet's remaining hours so the
// resubmission is not itself refused by the picker's own bounds. Module-level
// so both the mock backend and the assertions read the identical instant.
final _earliest = DateTime.now().toUtc().add(const Duration(minutes: 50));

/// A backend that 409s the FIRST create_order with SCHEDULED_PICKUP_TOO_SOON
/// naming [_earliest], then 400s any further attempt — deliberately, so the
/// test can inspect exactly what the resubmission asked for without having
/// to also stand up PickupScreen/CashfreeService for a full success path
/// (same technique test/scheduled_pickup_test.dart's "four cases on the
/// wire" group uses).
class _Backend {
  int orderCalls = 0;
  Map<String, dynamic>? firstBody;
  Map<String, dynamic>? secondBody;

  late final ApiClient api = ApiClient(client: MockClient((req) async {
    if (req.url.path.endsWith('/customer/cart/check')) {
      return http.Response(jsonEncode({'unavailable': const []}), 200,
          headers: {'content-type': 'application/json'});
    }
    if (req.method == 'POST' && req.url.path.endsWith('/customer/orders')) {
      orderCalls++;
      final body = (jsonDecode(req.body) as Map).cast<String, dynamic>();
      if (orderCalls == 1) {
        firstBody = body;
        return http.Response(
          jsonEncode({
            'detail': {
              'error': 'SCHEDULED_PICKUP_TOO_SOON',
              'message': 'This restaurant needs more time to prepare your '
                  'order. Please choose a later pickup time.',
              'earliest_pickup_at': _earliest.toIso8601String(),
            },
          }),
          409,
          headers: {'content-type': 'application/json'},
        );
      }
      secondBody = body;
      // Deliberate 400: the resubmission's PAYLOAD is what these tests
      // check, not a full success navigation.
      return http.Response(jsonEncode({'detail': 'captured-resubmit'}), 400,
          headers: {'content-type': 'application/json'});
    }
    return http.Response(jsonEncode(const []), 200,
        headers: {'content-type': 'application/json'});
  }));
}

void main() {
  Widget host(CartState cart, ApiClient api) {
    SharedPreferences.setMockInitialValues({'carevo_access_token': 't'});
    return MultiProvider(
      providers: [
        Provider<ApiClient>.value(value: api),
        Provider<OrderService>(create: (_) => OrderService(api)),
        Provider<CustomerService>(create: (_) => CustomerService(api)),
        Provider<CashfreeService>(create: (_) => CashfreeService()),
        Provider<LocationService>(create: (_) => LocationService()),
        Provider<PlacesService>(create: (_) => PlacesService()),
        ChangeNotifierProvider<CartState>.value(value: cart),
        ChangeNotifierProvider(create: (_) => ThemeProvider()),
      ],
      child: MaterialApp(theme: AppTheme.light(), home: const CheckoutScreen()),
    );
  }

  CartState cartWithItem() => CartState()
    ..setOutlet(_outlet())
    ..addItem(_menuItem(), quantity: 1);

  Future<void> settle(WidgetTester tester) async {
    await tester.pump();
    await tester.pump(const Duration(milliseconds: 400));
  }

  Future<void> pump(WidgetTester tester, Widget w) async {
    tester.view.physicalSize = const Size(1170, 3400);
    tester.view.devicePixelRatio = 3.0;
    addTearDown(tester.view.reset);
    await tester.pumpWidget(w);
    await settle(tester);
  }

  Future<void> reveal(WidgetTester tester, Key key, {double delta = 240}) async {
    await tester.scrollUntilVisible(find.byKey(key), delta,
        scrollable: find.byType(Scrollable).first);
    await settle(tester);
  }

  /// Turn scheduling on and accept whatever slot the picker opens on — the
  /// EXACT slot does not matter to these tests, since the mock backend 409s
  /// the first create_order regardless of what time was requested.
  Future<void> chooseAnySlot(WidgetTester tester) async {
    await reveal(tester, const Key('schedule_later'));
    await tester.tap(find.byKey(const Key('schedule_later')));
    await settle(tester);
    await reveal(tester, const Key('time_field'));
    await tester.tap(find.byKey(const Key('time_field')));
    await settle(tester);
    await tester.tap(find.byKey(const Key('arrival_confirm')));
    await settle(tester);
  }

  Future<void> tapPay(WidgetTester tester) async {
    await reveal(tester, const Key('checkout_pay'));
    await tester.tap(find.byKey(const Key('checkout_pay')));
    for (var i = 0; i < 4; i++) {
      await settle(tester);
    }
  }

  group('SCHEDULED_PICKUP_TOO_SOON', () {
    testWidgets('the 409 renders the earliest pickup time in plain words',
        (tester) async {
      final backend = _Backend();
      await pump(tester, host(cartWithItem(), backend.api));
      await chooseAnySlot(tester);
      await tapPay(tester);

      expect(backend.orderCalls, 1,
          reason: 'the first attempt must have reached create_order');

      final ctx = tester.element(find.byType(CheckoutScreen));
      final expectedTime =
          formatDateTimeWithDayPart(ctx, _earliest.toLocal());

      expect(find.text('Kitchen needs more time'), findsOneWidget);
      expect(find.textContaining(expectedTime), findsOneWidget,
          reason: 'the dialog must say the SAME earliest time the server sent');
      expect(find.text('Use this time'), findsOneWidget);
      expect(find.text('Choose another time'), findsOneWidget);
    });

    testWidgets('accepting the suggestion re-submits with exactly that time',
        (tester) async {
      final backend = _Backend();
      await pump(tester, host(cartWithItem(), backend.api));
      await chooseAnySlot(tester);
      await tapPay(tester);
      expect(backend.orderCalls, 1);

      await tester.tap(find.text('Use this time'));
      for (var i = 0; i < 4; i++) {
        await settle(tester);
      }

      expect(backend.orderCalls, 2,
          reason: 'accepting must trigger a second create_order attempt');
      expect(backend.secondBody?['requested_pickup_at'],
          _earliest.toIso8601String(),
          reason: 'the resubmission must request EXACTLY the time the '
              'server named, not whatever the customer originally picked');
      // Proves the original (too-soon) slot was actually replaced, not just
      // coincidentally equal to it.
      expect(backend.secondBody?['requested_pickup_at'],
          isNot(backend.firstBody?['requested_pickup_at']));
    });

    testWidgets('the cart is never lost across the 409, the dialog or the retry',
        (tester) async {
      final cart = cartWithItem();
      final backend = _Backend();
      await pump(tester, host(cart, backend.api));
      expect(cart.items, isNotEmpty);

      await chooseAnySlot(tester);
      await tapPay(tester);
      expect(cart.items, isNotEmpty,
          reason: 'the cart must survive the 409 itself');
      expect(find.text('Kitchen needs more time'), findsOneWidget);

      await tester.tap(find.text('Use this time'));
      for (var i = 0; i < 4; i++) {
        await settle(tester);
      }
      expect(cart.items, isNotEmpty,
          reason: 'the cart must survive the retry, even though it failed too');
    });

    testWidgets('"choose another time" reopens the picker and keeps the cart',
        (tester) async {
      final cart = cartWithItem();
      final backend = _Backend();
      await pump(tester, host(cart, backend.api));
      await chooseAnySlot(tester);
      await tapPay(tester);

      await tester.tap(find.text('Choose another time'));
      await settle(tester);

      expect(find.byKey(const Key('arrival_confirm')), findsOneWidget,
          reason: 'declining must reopen the ordinary time picker');
      expect(cart.items, isNotEmpty);
      // No second create_order attempt until the customer confirms a time
      // and taps Pay again.
      expect(backend.orderCalls, 1);
    });
  });
}
