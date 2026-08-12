// Covers three behaviours, each of which was a real defect:
//
//  1. A dead session (401 from ANY endpoint) must clear the stored token and
//     signal the app, instead of being kept forever while every request fails.
//  2. Several in-progress orders must each show their own pickup code on the
//     main screen, without navigating.
//  3. A COLLECTED order must say so, and must leave the active stack.
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
import 'package:customer_app/theme/theme_provider.dart';

/// An ApiClient whose transport is scripted, so a test can produce any status
/// code without a server.
ApiClient _client(
  Future<http.Response> Function(http.Request req) handler, {
  String? seededToken,
}) {
  SharedPreferences.setMockInitialValues(
    seededToken == null ? {} : {'carevo_access_token': seededToken},
  );
  return ApiClient(client: MockClient((req) async => handler(req)));
}

http.Response _json(Object body, {int status = 200}) =>
    http.Response(jsonEncode(body), status,
        headers: {'content-type': 'application/json'});

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
      'items': [
        {'name': 'Dosa', 'quantity': 1}
      ],
    };

// ===========================================================================
// 1. Dead / foreign session
// ===========================================================================
void main() {
  group('invalid or foreign token', () {
    test('401 on ANY endpoint clears the stored token and signals the app',
        () async {
      final api = _client(
        (_) async => _json({'detail': 'Could not validate credentials'},
            status: 401),
        seededToken: 'token-from-another-backend',
      );
      await api.loadToken();
      expect(api.isAuthenticated, isTrue, reason: 'starts with a stored token');

      var signalled = 0;
      api.authFailures.addListener(() => signalled++);

      await expectLater(
        api.get('/customer/outlets'),
        throwsA(isA<AuthExpiredException>()),
      );

      expect(api.isAuthenticated, isFalse, reason: 'token must be dropped');
      expect(signalled, 1, reason: 'app must be told to route to login');

      // Persisted, not just in-memory: a relaunch must not resurrect it.
      final prefs = await SharedPreferences.getInstance();
      expect(prefs.getString('carevo_access_token'), isNull);
    });

    test('applies to every verb, not just the outlet-list GET', () async {
      for (final call in <String, Future<dynamic> Function(ApiClient)>{
        'get': (a) => a.get('/customer/orders'),
        'post': (a) => a.post('/customer/orders', body: const {}),
        'patch': (a) => a.patch('/customer/me', body: const {}),
        'delete': (a) => a.delete('/customer/me'),
      }.entries) {
        final api = _client((_) async => _json({'detail': 'bad token'}, status: 401),
            seededToken: 'stale');
        await api.loadToken();
        await expectLater(call.value(api), throwsA(isA<AuthExpiredException>()),
            reason: '${call.key} should surface an auth failure');
        expect(api.isAuthenticated, isFalse,
            reason: '${call.key} should have cleared the session');
      }
    });

    test('403 does NOT clear the session — it is a permission denial', () async {
      // The API returns 403 for "Not your order" / "Simulation disabled" with a
      // perfectly valid session. Signing the customer out there would punish
      // them for an error they could not have avoided.
      final api = _client(
        (_) async => _json({'detail': 'Not your order'}, status: 403),
        seededToken: 'good-token',
      );
      await api.loadToken();

      var signalled = 0;
      api.authFailures.addListener(() => signalled++);

      await expectLater(api.get('/customer/orders/x'), throwsA(isA<ApiException>()));

      expect(api.isAuthenticated, isTrue, reason: 'session must survive a 403');
      expect(signalled, 0);
    });

    test('a 401 is distinguishable from an ordinary failure', () async {
      final bad = _client((_) async => _json({'detail': 'boom'}, status: 500),
          seededToken: 't');
      await bad.loadToken();
      await expectLater(bad.get('/x'), throwsA(isA<ApiException>()));
      expect(bad.isAuthenticated, isTrue, reason: '500 is not an auth failure');
    });
  });

  // =========================================================================
  // 2 + 3. Active-order stack on the main screen
  // =========================================================================
  group('active order stack', () {
    // The default 800x600 test surface overflows this screen's AppBar actions,
    // which throws and masks the assertions below. A tall phone-shaped surface
    // is both realistic and wide enough for the toolbar.
    setUp(() {
      final view = TestWidgetsFlutterBinding.ensureInitialized().platformDispatcher.views.first;
      view.physicalSize = const Size(1170, 2532);
      view.devicePixelRatio = 3.0;
    });

    tearDown(() {
      final view = TestWidgetsFlutterBinding.ensureInitialized().platformDispatcher.views.first;
      view.resetPhysicalSize();
      view.resetDevicePixelRatio();
    });

    Widget host(ApiClient api) {
      return MultiProvider(
        providers: [
          Provider<ApiClient>.value(value: api),
          Provider<CatalogService>(create: (_) => CatalogService(api)),
          Provider<CustomerService>(create: (_) => CustomerService(api)),
          // The shared AppBar actions include the theme toggle; without this
          // the toolbar throws ProviderNotFound and renders an error widget,
          // which then overflows and masks every real assertion.
          ChangeNotifierProvider<ThemeProvider>(create: (_) => ThemeProvider()),
        ],
        child: MaterialApp(
          theme: AppTheme.light(),
          home: const OutletsScreen(),
        ),
      );
    }

    ApiClient apiWith(List<Map<String, dynamic>> orders) => _client((req) async {
          if (req.url.path.contains('/customer/orders')) {
            return _json(orders);
          }
          if (req.url.path.contains('/customer/outlets')) {
            return _json(const []); // discovery list is irrelevant here
          }
          return _json(const []);
        }, seededToken: 'valid');

    testWidgets('two in-progress orders each show their OWN code, no tapping',
        (tester) async {
      final api = apiWith([
        _order(id: 'a', status: 'READY', code: '4821', outlet: 'Dosa Corner'),
        _order(id: 'b', status: 'PREPARING', code: '9137', outlet: 'Biryani House'),
      ]);
      await tester.pumpWidget(host(api));
      await tester.pump(const Duration(milliseconds: 600));

      // Both codes readable on the FIRST screen — the whole point.
      expect(find.text('4821'), findsOneWidget);
      expect(find.text('9137'), findsOneWidget);

      // Attributed to the right restaurant, so two codes can't be confused.
      expect(find.text('Dosa Corner'), findsOneWidget);
      expect(find.text('Biryani House'), findsOneWidget);

      // One card per order.
      expect(find.byKey(const Key('active_order_a')), findsOneWidget);
      expect(find.byKey(const Key('active_order_b')), findsOneWidget);
      expect(find.text('2 orders in progress'), findsOneWidget);
    });

    testWidgets('a single order shows its code with no count header',
        (tester) async {
      final api = apiWith([_order(id: 'solo', status: 'READY', code: '5150')]);
      await tester.pumpWidget(host(api));
      await tester.pump(const Duration(milliseconds: 600));

      expect(find.text('5150'), findsOneWidget);
      expect(find.textContaining('orders in progress'), findsNothing);
    });

    testWidgets('COMPLETED orders drop out of the active stack', (tester) async {
      final api = apiWith([
        _order(id: 'done', status: 'COMPLETED', code: '1111', outlet: 'Old Order'),
        _order(id: 'live', status: 'READY', code: '2222', outlet: 'Live Order'),
      ]);
      await tester.pumpWidget(host(api));
      await tester.pump(const Duration(milliseconds: 600));

      expect(find.text('2222'), findsOneWidget, reason: 'live order stays');
      expect(find.text('1111'), findsNothing,
          reason: 'a collected order must not keep occupying the main screen');
      expect(find.byKey(const Key('active_order_done')), findsNothing);
      // One card left, so no plural header.
      expect(find.textContaining('orders in progress'), findsNothing);
    });

    testWidgets('no active orders renders nothing at all', (tester) async {
      final api = apiWith([_order(id: 'x', status: 'COMPLETED', code: '0000')]);
      await tester.pumpWidget(host(api));
      await tester.pump(const Duration(milliseconds: 600));
      expect(find.text('0000'), findsNothing);
    });

    testWidgets('an order awaiting its code says so instead of showing a blank',
        (tester) async {
      final api = apiWith([_order(id: 'nocode', status: 'PAID', code: null)]);
      await tester.pumpWidget(host(api));
      await tester.pump(const Duration(milliseconds: 600));
      expect(find.text('Code soon'), findsOneWidget);
    });
  });

  // =========================================================================
  // 3. "Collected" is a state of its own
  // =========================================================================
  group('collected state — pickup screen copy', () {
    // Wider logical surface than the outlets group. The status stepper lays out
    // with GoogleFonts, which cannot fetch a webfont under `flutter test`, so
    // text measures differently here than on a device and the stepper's Row
    // reports an overflow that does not occur in the app. Giving it room keeps
    // the assertions about COPY from being masked by a font-metrics artifact —
    // the fix belongs in the harness, not in real layout.
    setUp(() {
      final view = TestWidgetsFlutterBinding.ensureInitialized().platformDispatcher.views.first;
      view.physicalSize = const Size(1600, 3000);
      view.devicePixelRatio = 2.0;
    });
    tearDown(() {
      final view = TestWidgetsFlutterBinding.ensureInitialized().platformDispatcher.views.first;
      view.resetPhysicalSize();
      view.resetDevicePixelRatio();
    });

    Widget pickupHost(String status) {
      final api = _client((req) async {
        if (req.url.path.contains('/customer/orders/')) {
          return _json({
            'id': 'o1',
            'status': status,
            'payment_status': 'PAID',
            'pickup_code': '7788',
            'total_amount': 200,
            'items': [
              {'name': 'Dosa', 'quantity': 1, 'line_total': 200}
            ],
          });
        }
        return _json(const {});
      }, seededToken: 'valid');

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

    testWidgets('COMPLETED shows warm collected copy, not "Ready to collect"',
        (tester) async {
      await tester.pumpWidget(pickupHost('COMPLETED'));
      await tester.pump(const Duration(milliseconds: 600));

      expect(find.text('Enjoy your\nfood!'), findsOneWidget);
      // The bug this replaces: a collected order told the customer to go and
      // collect the food they were already holding.
      expect(find.text('Ready to\ncollect!'), findsNothing);
      // TWO now, not one: the ticket header label plus the v2 rotated ghost
      // stamp across the ticket. Both are intended.
      expect(find.text('COLLECTED'), findsNWidgets(2));
      expect(find.text('PICKUP CODE'), findsNothing);
    });

    testWidgets('READY still shows the collect prompt', (tester) async {
      await tester.pumpWidget(pickupHost('READY'));
      await tester.pump(const Duration(milliseconds: 600));

      expect(find.text('Ready to\ncollect!'), findsOneWidget);
      expect(find.text('Enjoy your\nfood!'), findsNothing);
      expect(find.text('PICKUP CODE'), findsOneWidget);
    });
  });

  group('collected state', () {
    test('COMPLETED and PICKED_UP are not active', () {
      for (final s in ['COMPLETED', 'PICKED_UP', 'CANCELLED']) {
        expect(OrderHistoryEntry(orderId: 'x', status: s).isActive, isFalse,
            reason: '$s must not sit in the in-progress stack');
      }
    });

    test('the statuses that ARE active are exactly the in-flight ones', () {
      for (final s in ['PAID', 'RECEIVED', 'PREPARING', 'READY']) {
        expect(OrderHistoryEntry(orderId: 'x', status: s).isActive, isTrue);
      }
    });
  });
}
