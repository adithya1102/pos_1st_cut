// The arrival-signal chip on each active order card: "Left X min ago",
// "At the restaurant", or nothing at all when the server has no signal yet.
//
// Computed purely from departed_at/arrived_at on the order the queue already
// polls — no new request, no new timer. Three states, each its own test:
//   1. neither field present -> no chip at all;
//   2. departed_at only -> "Left X min ago";
//   3. arrived_at present -> "At the restaurant" (wins over departure).
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

const String _orderId = '11111111-1111-1111-1111-5555550a0001';
const Key _chipKey = Key('order_arrival_chip');

Map<String, dynamic> _order({
  String? departedAt,
  String? arrivedAt,
}) {
  final json = <String, dynamic>{
    'order_id': _orderId,
    'status': 'RECEIVED',
    'payment_status': 'PAID',
    'is_locked': false,
    'total_amount': 240,
    'created_at': '2026-09-02T10:00:00Z',
    'items': [
      {'id': '${_orderId}i1', 'name': 'Masala Dosa', 'quantity': 2},
    ],
  };
  json['departed_at'] = departedAt;
  json['arrived_at'] = arrivedAt;
  return json;
}

Future<void> _pump(
  WidgetTester tester,
  Map<String, dynamic> order,
) async {
  final client = ApiClient(
    httpClient: MockClient((_) async => http.Response(
          jsonEncode([order]),
          200,
          headers: {'content-type': 'application/json'},
        )),
  );
  await client.saveToken('a.stale.jwt');

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
}

void main() {
  setUp(() => SharedPreferences.setMockInitialValues({}));

  group('arrival chip on the order card', () {
    testWidgets('no signal at all renders no chip', (t) async {
      await _pump(t, _order());

      expect(find.byType(OrderCard), findsOneWidget);
      expect(find.byKey(_chipKey), findsNothing);
    });

    testWidgets('departed only shows "Left X min ago"', (t) async {
      final tenMinutesAgo =
          DateTime.now().toUtc().subtract(const Duration(minutes: 10));
      await _pump(t, _order(departedAt: tenMinutesAgo.toIso8601String()));

      expect(find.byKey(_chipKey), findsOneWidget);
      expect(find.textContaining('Left'), findsOneWidget);
      expect(find.textContaining('m ago'), findsOneWidget);
      expect(find.text('At the restaurant'), findsNothing);
    });

    testWidgets('departed just now shows "Left just now", not "0m ago"',
        (t) async {
      final now = DateTime.now().toUtc();
      await _pump(t, _order(departedAt: now.toIso8601String()));

      expect(find.text('Left just now'), findsOneWidget);
    });

    testWidgets('arrived shows "At the restaurant"', (t) async {
      final fiveMinutesAgo =
          DateTime.now().toUtc().subtract(const Duration(minutes: 5));
      await _pump(t, _order(arrivedAt: fiveMinutesAgo.toIso8601String()));

      expect(find.byKey(_chipKey), findsOneWidget);
      expect(find.text('At the restaurant'), findsOneWidget);
      expect(find.textContaining('Left'), findsNothing);
    });

    testWidgets(
        'arrived wins over departed when both signals are present',
        (t) async {
      final twenty = DateTime.now().toUtc().subtract(const Duration(minutes: 20));
      final five = DateTime.now().toUtc().subtract(const Duration(minutes: 5));
      await _pump(
        t,
        _order(
          departedAt: twenty.toIso8601String(),
          arrivedAt: five.toIso8601String(),
        ),
      );

      expect(find.text('At the restaurant'), findsOneWidget);
      expect(find.textContaining('Left'), findsNothing);
    });
  });

  group('Order model: arrivalChipLabel', () {
    test('null when neither timestamp is present', () {
      final o = Order.fromJson(_order());
      expect(o.departedAt, isNull);
      expect(o.arrivedAt, isNull);
      expect(o.arrivalChipLabel, isNull);
      expect(o.hasArrived, isFalse);
    });

    test('"Left Xm ago" floored at zero on clock skew', () {
      final future = DateTime.now().add(const Duration(hours: 1)).toUtc();
      final o = Order.fromJson(_order(departedAt: future.toIso8601String()));
      expect(o.minutesSinceDeparted, 0);
      expect(o.arrivalChipLabel, 'Left just now');
    });

    test('hasArrived is true once arrived_at is set', () {
      final o = Order.fromJson(
        _order(arrivedAt: DateTime.now().toUtc().toIso8601String()),
      );
      expect(o.hasArrived, isTrue);
      expect(o.arrivalChipLabel, 'At the restaurant');
    });
  });
}
