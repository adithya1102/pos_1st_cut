// v2 redesign behaviours that must hold regardless of how the visuals change.
//
//  §3.3 the "I've picked this up" button is an ACKNOWLEDGMENT — it must not
//       call any endpoint, and must not move the order's status.
//  §3.6 the direct-call button appears only when the outlet has a phone number.
//       Most outlets in prod have none, so the hidden case is the common one.
//  §5   the active-orders view renders 2+ concurrent orders.
import 'dart:convert';

import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:http/http.dart' as http;
import 'package:http/testing.dart';
import 'package:provider/provider.dart';
import 'package:shared_preferences/shared_preferences.dart';

import 'package:customer_app/screens/outlets_screen.dart';
import 'package:customer_app/screens/pickup_screen.dart';
import 'package:customer_app/services/api_client.dart';
import 'package:customer_app/services/catalog_service.dart';
import 'package:customer_app/services/customer_service.dart';
import 'package:customer_app/services/location_service.dart';
import 'package:customer_app/services/order_service.dart';
import 'package:customer_app/state/cart_state.dart';
import 'package:customer_app/theme/app_theme.dart';
import 'package:customer_app/theme/widgets/neo_card.dart';
import 'package:customer_app/theme/theme_provider.dart';

/// Records every request the app makes, so a test can assert on what was NOT
/// called — which is the whole point of the acknowledgment test.
class _Recorder {
  final List<String> calls = [];
  ApiClient client(Future<http.Response> Function(http.Request) handler) {
    SharedPreferences.setMockInitialValues({'carevo_access_token': 'valid'});
    return ApiClient(
      client: MockClient((req) async {
        calls.add('${req.method} ${req.url.path}');
        return handler(req);
      }),
    );
  }
}

http.Response _json(Object body, {int status = 200}) =>
    http.Response(jsonEncode(body), status,
        headers: {'content-type': 'application/json'});

Map<String, dynamic> _outlet({
  required String id,
  required String name,
  String? phone,
}) =>
    {
      'id': id,
      'name': name,
      'address': 'Koramangala, Bengaluru',
      'is_open': true,
      'distance_km': 1.2,
      'locality': 'Koramangala',
      'phone_number': phone,
      'latitude': 12.9352,
      'longitude': 77.6245,
      'offer_count': 0,
    };

Map<String, dynamic> _order({
  required String id,
  required String status,
  String? code,
  String outlet = 'Test Kitchen',
}) =>
    {
      'order_id': id,
      'status': status,
      'outlet_name': outlet,
      'payment_status': 'PAID',
      'total_amount': 120,
      'discount_amount': 0,
      'created_at': DateTime.now().toIso8601String(),
      'pickup_code': code,
      'items': const [],
    };

void _sizeSurface(WidgetTester tester) {
  final view = tester.view;
  view.physicalSize = const Size(1600, 3000);
  view.devicePixelRatio = 2.0;
  addTearDown(() {
    view.resetPhysicalSize();
    view.resetDevicePixelRatio();
  });
}

void main() {
  // =========================================================================
  // §3.3 — acknowledgment only
  // =========================================================================
  group('pickup acknowledgment (§3.3)', () {
    late _Recorder rec;

    Widget host(String status) {
      rec = _Recorder();
      final api = rec.client((req) async {
        if (req.url.path.contains('/customer/orders/')) {
          return _json({
            'id': 'o1',
            'status': status,
            'payment_status': 'PAID',
            'pickup_code': '7788',
            'total_amount': 200,
            'items': const [],
          });
        }
        return _json(const {});
      });
      return MultiProvider(
        providers: [
          Provider<ApiClient>.value(value: api),
          Provider<OrderService>(create: (_) => OrderService(api)),
          Provider<LocationService>(create: (_) => LocationService()),
          ChangeNotifierProvider<CartState>(create: (_) => CartState()),
          ChangeNotifierProvider<ThemeProvider>(create: (_) => ThemeProvider()),
        ],
        child: MaterialApp(
          theme: AppTheme.light(),
          home: const PickupScreen(orderId: 'o1', fromHistory: true),
        ),
      );
    }

    testWidgets('tapping it calls NO status-changing endpoint', (tester) async {
      _sizeSurface(tester);
      await tester.pumpWidget(host('READY'));
      await tester.pump(const Duration(milliseconds: 600));

      final btn = find.byKey(const Key('ack_picked_up'));
      expect(btn, findsOneWidget, reason: 'the acknowledgment should be offered');

      rec.calls.clear();
      await tester.tap(btn);
      await tester.pump(const Duration(milliseconds: 400));

      // The heart of §3.3: staff verification in owner_app stays the ONLY way
      // an order completes. Anything that mutates state would break that.
      const forbidden = [
        'verify', 'complete', 'collect', 'pickup', 'status', 'arrived', 'depart',
      ];
      for (final call in rec.calls) {
        final isWrite = call.startsWith('POST') ||
            call.startsWith('PATCH') ||
            call.startsWith('DELETE');
        expect(isWrite, isFalse,
            reason: 'acknowledgment must not write anything, saw: $call');
        for (final f in forbidden) {
          expect(call.toLowerCase().contains(f) && isWrite, isFalse,
              reason: 'must not hit a status-changing endpoint: $call');
        }
      }
    });

    testWidgets('it only acknowledges locally — the order stays in progress',
        (tester) async {
      _sizeSurface(tester);
      await tester.pumpWidget(host('READY'));
      await tester.pump(const Duration(milliseconds: 600));

      await tester.tap(find.byKey(const Key('ack_picked_up')));
      await tester.pump(const Duration(milliseconds: 400));

      // The button is replaced by a note that says plainly the restaurant
      // still confirms — so nobody reads the tap as "done".
      expect(find.byKey(const Key('ack_picked_up_note')), findsOneWidget);
      expect(find.byKey(const Key('ack_picked_up')), findsNothing);
      // Still NOT the collected state: that only comes from the server.
      expect(find.text('Enjoy your\nfood!'), findsNothing);
    });

    testWidgets('not offered once the order is genuinely COMPLETED',
        (tester) async {
      _sizeSurface(tester);
      await tester.pumpWidget(host('COMPLETED'));
      await tester.pump(const Duration(milliseconds: 600));

      expect(find.byKey(const Key('ack_picked_up')), findsNothing,
          reason: 'nothing to acknowledge once the server says collected');
      expect(find.text('Enjoy your\nfood!'), findsOneWidget);
    });
  });

  // =========================================================================
  // §3.6 — direct call, hidden when there is no number
  // =========================================================================
  group('direct call button (§3.6)', () {
    Widget host(List<Map<String, dynamic>> outlets) {
      SharedPreferences.setMockInitialValues({'carevo_access_token': 'valid'});
      final api = ApiClient(
        client: MockClient((req) async {
          if (req.url.path.contains('/customer/orders')) return _json(const []);
          if (req.url.path.contains('/customer/outlets')) return _json(outlets);
          return _json(const []);
        }),
      );
      return MultiProvider(
        providers: [
          Provider<ApiClient>.value(value: api),
          Provider<CatalogService>(create: (_) => CatalogService(api)),
          Provider<CustomerService>(create: (_) => CustomerService(api)),
          ChangeNotifierProvider<ThemeProvider>(create: (_) => ThemeProvider()),
        ],
        child: MaterialApp(theme: AppTheme.light(), home: const OutletsScreen()),
      );
    }

    testWidgets('shown when the outlet HAS a phone number', (tester) async {
      _sizeSurface(tester);
      await tester.pumpWidget(
          host([_outlet(id: 'a', name: 'Has Phone', phone: '9876500000')]));
      await tester.pump(const Duration(milliseconds: 600));

      expect(find.byKey(const Key('call_outlet_a')), findsOneWidget);
    });

    testWidgets('HIDDEN when phone_number is null — the common case',
        (tester) async {
      // 5 of the 6 customer-visible outlets in prod have no phone, so this is
      // the normal path, not an edge case. A dead button would be the default
      // experience.
      _sizeSurface(tester);
      await tester.pumpWidget(
          host([_outlet(id: 'b', name: 'No Phone', phone: null)]));
      await tester.pump(const Duration(milliseconds: 600));

      expect(find.byKey(const Key('call_outlet_b')), findsNothing);
      expect(find.byIcon(Icons.call), findsNothing);
    });

    testWidgets('an empty-string phone is treated as absent', (tester) async {
      _sizeSurface(tester);
      await tester.pumpWidget(
          host([_outlet(id: 'c', name: 'Blank Phone', phone: '   ')]));
      await tester.pump(const Duration(milliseconds: 600));

      expect(find.byKey(const Key('call_outlet_c')), findsNothing);
    });

    testWidgets('mixed list shows the button only on outlets that have one',
        (tester) async {
      _sizeSurface(tester);
      await tester.pumpWidget(host([
        _outlet(id: 'p', name: 'With Phone', phone: '9876500000'),
        _outlet(id: 'q', name: 'Without Phone', phone: null),
      ]));
      await tester.pump(const Duration(milliseconds: 600));

      expect(find.byKey(const Key('call_outlet_p')), findsOneWidget);
      expect(find.byKey(const Key('call_outlet_q')), findsNothing);
    });
  });

  // =========================================================================
  // Multi-order ticket stack
  // =========================================================================
  group('multi-order active view', () {
    Widget host(List<Map<String, dynamic>> orders) {
      SharedPreferences.setMockInitialValues({'carevo_access_token': 'valid'});
      final api = ApiClient(
        client: MockClient((req) async {
          if (req.url.path.contains('/customer/orders')) return _json(orders);
          if (req.url.path.contains('/customer/outlets')) return _json(const []);
          return _json(const []);
        }),
      );
      return MultiProvider(
        providers: [
          Provider<ApiClient>.value(value: api),
          Provider<CatalogService>(create: (_) => CatalogService(api)),
          Provider<CustomerService>(create: (_) => CustomerService(api)),
          ChangeNotifierProvider<ThemeProvider>(create: (_) => ThemeProvider()),
        ],
        child: MaterialApp(theme: AppTheme.light(), home: const OutletsScreen()),
      );
    }

    testWidgets('renders 2+ concurrent orders, each with its own code',
        (tester) async {
      _sizeSurface(tester);
      await tester.pumpWidget(host([
        _order(id: 'a', status: 'READY', code: '4821', outlet: 'Dosa Corner'),
        _order(id: 'b', status: 'PREPARING', code: '9137', outlet: 'Biryani House'),
        _order(id: 'c', status: 'PAID', code: '5150', outlet: 'Chai Point'),
      ]));
      await tester.pump(const Duration(milliseconds: 600));

      for (final id in ['a', 'b', 'c']) {
        expect(find.byKey(Key('active_order_$id')), findsOneWidget);
        expect(find.byKey(Key('active_order_code_$id')), findsOneWidget);
      }
      for (final code in ['4821', '9137', '5150']) {
        expect(find.text(code), findsOneWidget);
      }
      expect(find.text('3 orders in progress'), findsOneWidget);
    });

    testWidgets('concurrency needs no backend change — COMPLETED just drops out',
        (tester) async {
      _sizeSurface(tester);
      await tester.pumpWidget(host([
        _order(id: 'live1', status: 'READY', code: '1111'),
        _order(id: 'live2', status: 'PREPARING', code: '2222'),
        _order(id: 'done', status: 'COMPLETED', code: '3333'),
      ]));
      await tester.pump(const Duration(milliseconds: 600));

      expect(find.byKey(const Key('active_order_live1')), findsOneWidget);
      expect(find.byKey(const Key('active_order_live2')), findsOneWidget);
      expect(find.byKey(const Key('active_order_done')), findsNothing);
      expect(find.text('2 orders in progress'), findsOneWidget);
    });
  });

  // =========================================================================
  // Outlet list search + filter chips (Task 4)
  // =========================================================================
  group('outlet search and filters', () {
    Widget host(List<Map<String, dynamic>> outlets) {
      SharedPreferences.setMockInitialValues({'carevo_access_token': 'valid'});
      final api = ApiClient(
        client: MockClient((req) async {
          if (req.url.path.contains('/customer/orders')) return _json(const []);
          if (req.url.path.contains('/customer/outlets')) return _json(outlets);
          return _json(const []);
        }),
      );
      return MultiProvider(
        providers: [
          Provider<ApiClient>.value(value: api),
          Provider<CatalogService>(create: (_) => CatalogService(api)),
          Provider<CustomerService>(create: (_) => CustomerService(api)),
          ChangeNotifierProvider<ThemeProvider>(create: (_) => ThemeProvider()),
        ],
        child: MaterialApp(theme: AppTheme.light(), home: const OutletsScreen()),
      );
    }

    testWidgets('search narrows the list by name', (tester) async {
      _sizeSurface(tester);
      await tester.pumpWidget(host([
        _outlet(id: 'a', name: 'Dosa Corner'),
        _outlet(id: 'b', name: 'Biryani House'),
      ]));
      await tester.pump(const Duration(milliseconds: 600));
      expect(find.byKey(const Key('outlet_card_a')), findsOneWidget);
      expect(find.byKey(const Key('outlet_card_b')), findsOneWidget);

      await tester.enterText(find.byKey(const Key('outlet_search')), 'biry');
      await tester.pump(const Duration(milliseconds: 300));

      expect(find.byKey(const Key('outlet_card_a')), findsNothing);
      expect(find.byKey(const Key('outlet_card_b')), findsOneWidget);
    });

    testWidgets('filtering to nothing explains itself instead of looking empty',
        (tester) async {
      _sizeSurface(tester);
      await tester.pumpWidget(host([_outlet(id: 'a', name: 'Dosa Corner')]));
      await tester.pump(const Duration(milliseconds: 600));

      await tester.enterText(
          find.byKey(const Key('outlet_search')), 'zzzznomatch');
      await tester.pump(const Duration(milliseconds: 300));

      // Distinct from "no restaurants here yet" — the fix is to clear a filter,
      // so the message has to say that.
      expect(find.text('No restaurants match those filters.'), findsOneWidget);
    });

    testWidgets('nearest-first sorts, and unknown distances go last',
        (tester) async {
      _sizeSurface(tester);
      final far = _outlet(id: 'far', name: 'Far Place')..['distance_km'] = 9.0;
      final near = _outlet(id: 'near', name: 'Near Place')..['distance_km'] = 0.5;
      final unknown = _outlet(id: 'unk', name: 'Unknown Place')
        ..['distance_km'] = null;

      await tester.pumpWidget(host([far, unknown, near]));
      await tester.pump(const Duration(milliseconds: 600));

      // `chip_nearest` became `sort_nearest` when the boolean "Nearest first"
      // toggle was replaced by the sort bar (2026-08-24), and that bar was then
      // collapsed behind a filter button (2026-08-25) — so reaching it is now
      // open-sheet-then-select. Same behaviour, different control; the
      // assertions below are unchanged.
      await tester.tap(find.byKey(const Key('filter_button')));
      await tester.pumpAndSettle();
      await tester.tap(find.byKey(const Key('sort_nearest')));
      await tester.pumpAndSettle();

      final cards = tester
          .widgetList(find.byType(NeoCard))
          .toList(); // order follows the list
      expect(cards.isNotEmpty, isTrue);
      // An outlet with no distance must not be presented as the closest.
      final nearY = tester.getTopLeft(find.byKey(const Key('outlet_card_near'))).dy;
      final farY = tester.getTopLeft(find.byKey(const Key('outlet_card_far'))).dy;
      final unkY = tester.getTopLeft(find.byKey(const Key('outlet_card_unk'))).dy;
      expect(nearY < farY, isTrue, reason: 'nearer outlet should sort first');
      expect(unkY > farY, isTrue, reason: 'unknown distance sorts last');
    });
  });
}
