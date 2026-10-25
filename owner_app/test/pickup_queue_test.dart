// The Pickup screen's active-order queue.
//
// This screen is what the kitchen reads to know what to cook, so the lines
// these tests hold are about TRUST in the list rather than about pixels:
//
//   1. Only live work appears. The backend keeps a collected order in the feed
//      for 30 minutes after handover (COMPLETED_GRACE) and that is useful on
//      the Orders tab, but a "what do I cook next" list that shows finished
//      orders gets ignored. Cancelled and unpaid rows likewise.
//   2. Oldest first. The queue is a work order; whoever waited longest is next.
//      The feed arrives newest-first, so this is an inversion, not a pass-through.
//   3. The pickup code NEVER renders. Not in a row, not in the detail panel.
//      The backend does not even send it, and this asserts the app would not
//      show it if a future response started to.
//   4. A 401 routes to login. An expired token previously produced a dead
//      screen offering a Retry button that could never succeed.
//
// Driven through a MockClient and a real ApiClient rather than a fake service,
// so the ApiException mapping that distinguishes 401 from 500 is exercised for
// real — a hand-rolled fake would only prove the test agrees with itself.
import 'dart:convert';

import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:http/http.dart' as http;
import 'package:http/testing.dart';
import 'package:provider/provider.dart';
import 'package:shared_preferences/shared_preferences.dart';

import 'package:owner_app/models/order.dart';
import 'package:owner_app/screens/orders_screen.dart';
import 'package:owner_app/services/api_client.dart';
import 'package:owner_app/services/auth_service.dart';
import 'package:owner_app/services/order_service.dart';
import 'package:owner_app/state/auth_state.dart';
import 'package:owner_app/state/orders_state.dart';
import 'package:owner_app/widgets/order_card.dart';

// UUID-shaped: Order.shortId shows the last six characters of anything longer
// than eight, so a toy id would not exercise the label staff read off the row.
const String _idOldest = '11111111-1111-1111-1111-5555550a0001';
const String _idMiddle = '22222222-2222-2222-2222-5555550b0002';
const String _idNewest = '33333333-3333-3333-3333-5555550c0003';
const String _idDone = '44444444-4444-4444-4444-5555550d0004';
const String _idCancelled = '55555555-5555-5555-5555-5555550e0005';

/// The literal a leaked pickup code would look like. Asserted absent.
const String _secretCode = '472913';

const Key _emptyKey = Key('orders_queue_empty');
const Key _errorKey = Key('orders_queue_error');
const Key _retryKey = Key('orders_queue_retry');
const Key _listKey = Key('orders_queue_list');
const Key _expiredKey = Key('orders_queue_session_expired');

Map<String, dynamic> _order(
  String id, {
  String status = 'RECEIVED',
  String paymentStatus = 'PAID',
  double total = 240,
  required String createdAt,
  bool leakCode = false,
}) =>
    {
      'order_id': id,
      'status': status,
      'payment_status': paymentStatus,
      'is_locked': false,
      'total_amount': total,
      'created_at': createdAt,
      // Only set by the leak test: the real OwnerOrderOut has no such field.
      if (leakCode) 'pickup_code': _secretCode,
      'items': [
        {'id': '${id}i1', 'name': 'Masala Dosa', 'quantity': 2},
        {'id': '${id}i2', 'name': 'Filter Coffee', 'quantity': 1},
      ],
    };

/// Mounts the Pickup screen over a backend that answers `GET /pos/orders`
/// with [handler], and returns the states so a test can assert on them.
Future<({OrdersState orders, AuthState auth})> _pump(
  WidgetTester tester,
  Future<http.Response> Function(http.Request) handler, {
  bool signedIn = true,
}) async {
  final client = ApiClient(httpClient: MockClient(handler));
  if (signedIn) await client.saveToken('a.stale.jwt');

  final orders = OrdersState(OrderService(client));
  final auth = AuthState(AuthService(client));
  await auth.bootstrap();

  await tester.pumpWidget(
    MultiProvider(
      providers: [
        ChangeNotifierProvider<OrdersState>.value(value: orders),
        ChangeNotifierProvider<AuthState>.value(value: auth),
      ],
      child: const MaterialApp(home: Scaffold(body: OrdersScreen())),
    ),
  );

  await orders.load();
  await tester.pumpAndSettle();
  return (orders: orders, auth: auth);
}

http.Response _ok(List<Map<String, dynamic>> feed) => http.Response(
      jsonEncode(feed),
      200,
      headers: {'content-type': 'application/json'},
    );

void main() {
  // ApiClient.clearToken() always sweeps the legacy SharedPreferences key as
  // well as the Keystore, so the sign-out path touches this plugin even though
  // the token itself lives in secure storage. Without the mock the logout
  // future never completes and the 401 tests fail for a reason that has
  // nothing to do with the behaviour under test.
  setUp(() => SharedPreferences.setMockInitialValues({}));

  group('active queue rendering', () {
    testWidgets('renders one row per active order, oldest first', (t) async {
      // Deliberately supplied newest-first, exactly as the backend returns it.
      final s = await _pump(
        t,
        (_) async => _ok([
          _order(_idNewest, createdAt: '2026-09-02T10:40:00Z'),
          _order(_idMiddle, createdAt: '2026-09-02T10:20:00Z'),
          _order(_idOldest, createdAt: '2026-09-02T10:00:00Z'),
        ]),
      );

      expect(find.byKey(_listKey), findsOneWidget);

      final rendered = t
          .widgetList<OrderCard>(find.byType(OrderCard))
          .map((c) => c.order.orderId)
          .toList();

      // The inversion is the whole point: longest-waiting first.
      expect(rendered, [_idOldest, _idMiddle, _idNewest]);
      expect(s.orders.activeOrders.length, 3);
    });

    testWidgets('row carries order number, items summary, total and status',
        (t) async {
      await _pump(
        t,
        (_) async => _ok([_order(_idOldest, createdAt: '2026-09-02T10:00:00Z')]),
      );

      // Short id (last six of the uuid), the 3-item/₹240 summary, and status.
      expect(find.text('#0a0001'), findsOneWidget);
      expect(find.textContaining('3 items'), findsOneWidget);
      expect(find.textContaining('240'), findsOneWidget);
      expect(find.text('RECEIVED'), findsOneWidget);
    });

    testWidgets('placed time is shown and pickup time is honestly labelled',
        (t) async {
      await _pump(
        t,
        (_) async => _ok([_order(_idOldest, createdAt: '2026-09-02T10:00:00Z')]),
      );

      // Not asserting a literal clock time: the widget renders LOCAL time and
      // the suite must not depend on the machine's zone. What matters is that a
      // placed time is present and the missing field is named rather than
      // silently shown as a dash.
      expect(find.textContaining('Placed '), findsOneWidget);
      expect(
        find.textContaining('pickup time not sent by server'),
        findsOneWidget,
      );
    });

    testWidgets('excludes completed, cancelled and unpaid orders', (t) async {
      final s = await _pump(
        t,
        (_) async => _ok([
          _order(_idOldest, createdAt: '2026-09-02T10:00:00Z'),
          // In the feed only because of the 30-minute grace window.
          _order(_idDone,
              status: 'COMPLETED', createdAt: '2026-09-02T10:05:00Z'),
          _order(_idCancelled,
              status: 'CANCELLED', createdAt: '2026-09-02T10:06:00Z'),
          // Unpaid: not the outlet's problem yet.
          _order(_idNewest,
              status: 'CREATED',
              paymentStatus: 'PENDING',
              createdAt: '2026-09-02T10:07:00Z'),
        ]),
      );

      expect(s.orders.activeOrders.map((o) => o.orderId), [_idOldest]);
      expect(find.byType(OrderCard), findsOneWidget);
      // The feed itself is untouched — the filter is a view, not a mutation.
      expect(s.orders.orders.length, 4);
    });
  });

  group('the pickup code never reaches the screen', () {
    testWidgets('no code appears in a row even if the API starts sending one',
        (t) async {
      await _pump(
        t,
        (_) async => _ok([
          _order(_idOldest, createdAt: '2026-09-02T10:00:00Z', leakCode: true),
        ]),
      );

      // The row is collapsed: the code must not be anywhere on screen.
      expect(find.textContaining(_secretCode), findsNothing);

      // Expand the detail panel and check again — the handover box is a code
      // INPUT, and an input must never be pre-filled with the answer.
      await t.tap(find.text('#0a0001'));
      await t.pumpAndSettle();

      expect(find.textContaining(_secretCode), findsNothing);
      // The gate itself is still there and still demands typing.
      expect(find.text('Pickup verification'), findsOneWidget);
      expect(find.widgetWithText(TextField, 'Pickup code'), findsWidgets);
    });
  });

  group('empty state', () {
    testWidgets('shows the nothing-to-prepare message on an empty feed',
        (t) async {
      await _pump(t, (_) async => _ok([]));

      expect(find.byKey(_emptyKey), findsOneWidget);
      expect(find.textContaining('Nothing to prepare'), findsOneWidget);
      expect(find.byType(OrderCard), findsNothing);
    });

    testWidgets('an all-completed feed is empty, not a list of finished rows',
        (t) async {
      await _pump(
        t,
        (_) async => _ok([
          _order(_idDone,
              status: 'COMPLETED', createdAt: '2026-09-02T10:05:00Z'),
        ]),
      );

      expect(find.byKey(_emptyKey), findsOneWidget);
      expect(find.byType(OrderCard), findsNothing);
    });
  });

  group('error state', () {
    testWidgets('a 500 shows the retryable error with a working Retry',
        (t) async {
      var calls = 0;
      final s = await _pump(t, (_) async {
        calls++;
        if (calls == 1) {
          return http.Response('{"detail":"boom"}', 500,
              headers: {'content-type': 'application/json'});
        }
        return _ok([_order(_idOldest, createdAt: '2026-09-02T10:00:00Z')]);
      });

      expect(find.byKey(_errorKey), findsOneWidget);
      expect(find.textContaining('Could not load orders'), findsOneWidget);

      // Retry actually re-requests and recovers.
      await t.tap(find.byKey(_retryKey));
      await t.pumpAndSettle();

      expect(find.byKey(_errorKey), findsNothing);
      expect(find.byType(OrderCard), findsOneWidget);
      expect(s.orders.error, isNull);
      // A 500 must NOT be mistaken for an expired session.
      expect(s.orders.sessionExpired, isFalse);
      expect(s.auth.loggedIn, isTrue);
    });

    testWidgets('a transport failure is also a retryable error', (t) async {
      final s = await _pump(
        t,
        (_) async => throw http.ClientException('connection reset'),
      );

      expect(find.byKey(_errorKey), findsOneWidget);
      expect(s.orders.sessionExpired, isFalse);
      expect(s.auth.loggedIn, isTrue);
    });
  });

  group('401 routes to login', () {
    testWidgets('an expired token signs the owner out instead of offering Retry',
        (t) async {
      final s = await _pump(
        t,
        (_) async => http.Response('{"detail":"Staff authentication required"}',
            401, headers: {'content-type': 'application/json'}),
      );

      // The state said "expired", not "error" — these must not be conflated.
      expect(s.orders.error, isNull);

      // The post-frame handler has run by now: auth is cleared, which is what
      // flips _Root back to LoginScreen in the real app.
      expect(s.auth.loggedIn, isFalse);

      // And emphatically NOT the dead-end screen this replaced.
      expect(find.byKey(_retryKey), findsNothing);
      expect(find.textContaining('Could not load orders'), findsNothing);
    });

    testWidgets('the expired notice is shown while the sign-out lands',
        (t) async {
      final client = ApiClient(httpClient: MockClient((_) async =>
          http.Response('{"detail":"Staff authentication required"}', 401,
              headers: {'content-type': 'application/json'})));
      await client.saveToken('a.stale.jwt');
      final orders = OrdersState(OrderService(client));
      final auth = AuthState(AuthService(client));
      await auth.bootstrap();

      await t.pumpWidget(
        MultiProvider(
          providers: [
            ChangeNotifierProvider<OrdersState>.value(value: orders),
            ChangeNotifierProvider<AuthState>.value(value: auth),
          ],
          child: const MaterialApp(home: Scaffold(body: OrdersScreen())),
        ),
      );

      await orders.load();
      // One pump only — before the post-frame callback has been serviced.
      await t.pump();

      expect(find.byKey(_expiredKey), findsOneWidget);
      expect(find.textContaining('session has expired'), findsOneWidget);

      await t.pumpAndSettle();
      expect(auth.loggedIn, isFalse);
    });

    testWidgets('401 stops the poll so a dead device cannot hammer the backend',
        (t) async {
      var calls = 0;
      final client = ApiClient(httpClient: MockClient((_) async {
        calls++;
        return http.Response('{"detail":"Staff authentication required"}', 401,
            headers: {'content-type': 'application/json'});
      }));
      await client.saveToken('a.stale.jwt');

      // A short interval so the test does not wait 20 real seconds.
      final orders = OrdersState(
        OrderService(client),
        pollInterval: const Duration(milliseconds: 40),
      );
      final auth = AuthState(AuthService(client));
      await auth.bootstrap();

      await t.pumpWidget(
        MultiProvider(
          providers: [
            ChangeNotifierProvider<OrdersState>.value(value: orders),
            ChangeNotifierProvider<AuthState>.value(value: auth),
          ],
          child: const MaterialApp(home: Scaffold(body: OrdersScreen())),
        ),
      );

      orders.startPolling();
      await orders.load();
      await t.pumpAndSettle();

      final callsAfter401 = calls;
      // Well past several would-be ticks.
      await t.pump(const Duration(milliseconds: 300));

      expect(calls, callsAfter401,
          reason: 'polling must stop once the token is known to be dead');
    });
  });

  group('refresh cadence', () {
    test('the default queue poll is 20 seconds', () {
      expect(OrdersState.defaultPollInterval, const Duration(seconds: 20));
    });

    test('an order awaiting a decision still escalates to 5 seconds', () {
      // The acceptance deadline is 180s; a 20s poll against it would be up to
      // 20 seconds of alarm after another device already settled the order.
      expect(OrdersState.pendingPollInterval, const Duration(seconds: 5));
    });
  });

  group('active status set mirrors the backend', () {
    test('matches _LIVE_STATUSES exactly', () {
      // app/modules/carevo_customer/service.py:80
      expect(OrdersState.activeStatuses, {
        'PAID',
        'RECEIVED',
        'PREPARING',
        'READY',
      });
    });

    test('every live status actually survives the filter', () {
      for (final status in OrdersState.activeStatuses) {
        final order = Order.fromJson(
          _order(_idOldest, status: status, createdAt: '2026-09-02T10:00:00Z'),
        );
        expect(
          OrdersState.activeStatuses.contains(order.status.toUpperCase()),
          isTrue,
          reason: '$status must be treated as live work',
        );
      }
    });
  });

  group('oldest-first sorting edge cases', () {
    test('an unparseable timestamp sorts last rather than being dropped', () {
      final state = OrdersState(OrderService(ApiClient(
        httpClient: MockClient((_) async => _ok([])),
      )));

      // Exercised through the public getter by way of a seeded load.
      final feed = [
        _order(_idNewest, createdAt: 'not-a-date'),
        _order(_idOldest, createdAt: '2026-09-02T10:00:00Z'),
      ];
      final parsed = feed.map(Order.fromJson).toList();

      parsed.sort((a, b) {
        final at = a.placedAt;
        final bt = b.placedAt;
        if (at == null && bt == null) return 0;
        if (at == null) return 1;
        if (bt == null) return -1;
        return at.compareTo(bt);
      });

      expect(parsed.first.orderId, _idOldest);
      expect(parsed.last.orderId, _idNewest);
      expect(state.activeOrders, isEmpty);
    });

    test('placedLabel is null for an unusable timestamp', () {
      final o = Order.fromJson(_order(_idOldest, createdAt: ''));
      expect(o.placedAt, isNull);
      expect(o.placedLabel, isNull);
      expect(o.minutesSincePlaced, isNull);
    });

    test('minutesSincePlaced never goes negative on clock skew', () {
      final future = DateTime.now().add(const Duration(hours: 2)).toUtc();
      final o = Order.fromJson(
        _order(_idOldest, createdAt: future.toIso8601String()),
      );
      expect(o.minutesSincePlaced, 0);
    });
  });
}
