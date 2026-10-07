// "Limited quantity today" — the owner-side control for stock tracking
// (backend migration 033).
//
// THE DISTINCTION UNDER TEST is null vs 0. NULL means UNTRACKED (unlimited,
// how every dish behaves today); 0 means "counted, and sold out". Collapsing
// them would make turning tracking OFF indistinguishable from selling out, and
// the model has a dedicated `clearStock` flag purely because Dart's optional
// parameters cannot otherwise express "set this to null".
import 'dart:convert';

import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:http/http.dart' as http;
import 'package:http/testing.dart';
import 'package:shared_preferences/shared_preferences.dart';

import 'package:owner_app/models/menu_item.dart';
import 'package:owner_app/services/api_client.dart';
import 'package:owner_app/services/menu_service.dart';
import 'package:owner_app/widgets/dish_row.dart';

MenuItem _item({int? stock}) => MenuItem(
      id: 'item-1',
      name: 'Masala Dosa',
      isAvailable: true,
      isActive: true,
      basePrice: 80,
      stockRemaining: stock,
    );

/// Records every request so the test can assert the wire payload, which is
/// where the null-vs-0 distinction actually has to survive.
({MenuService service, List<Map<String, dynamic>> sent}) _service({
  int? respondStock,
  bool respondAvailable = true,
}) {
  final sent = <Map<String, dynamic>>[];
  final api = ApiClient(
    httpClient: MockClient((req) async {
      if (req.body.isNotEmpty) {
        sent.add(jsonDecode(req.body) as Map<String, dynamic>);
      }
      return http.Response(
        jsonEncode({
          'id': 'item-1',
          'name': 'Masala Dosa',
          'stock_remaining': respondStock,
          'is_available': respondAvailable,
        }),
        200,
        headers: {'content-type': 'application/json'},
      );
    }),
  );
  return (service: MenuService(api), sent: sent);
}

void main() {
  // flutter_test_config.dart mocks flutter_secure_storage globally, but
  // ApiClient.readToken ALSO touches SharedPreferences — it still reads the
  // legacy plaintext store in order to migrate a token out of it. Without this
  // the first request throws MissingPluginException rather than reaching the
  // MockClient.
  setUp(() => SharedPreferences.setMockInitialValues({}));

  group('MenuItem models untracked as null, not zero', () {
    test('an absent stock_remaining is UNTRACKED', () {
      // An older backend, and every dish nobody has opted in.
      final item = MenuItem.fromJson({
        'id': 'i', 'name': 'n', 'is_available': true, 'is_active': true,
        'base_price': 10,
      });
      expect(item.stockRemaining, isNull);
      expect(item.isStockTracked, isFalse);
    });

    test('zero is TRACKED and sold out', () {
      final item = MenuItem.fromJson({
        'id': 'i', 'name': 'n', 'is_available': false, 'is_active': true,
        'base_price': 10, 'stock_remaining': 0,
      });
      expect(item.stockRemaining, 0);
      expect(item.isStockTracked, isTrue,
          reason: 'sold out is not the same as untracked');
    });

    test('copyWith can REACH untracked via clearStock', () {
      // Without the flag this state is unreachable: a null argument is
      // indistinguishable from an omitted one.
      final tracked = _item(stock: 4);
      expect(tracked.copyWith(clearStock: true).stockRemaining, isNull);
      expect(tracked.copyWith(stockRemaining: 2).stockRemaining, 2);
      // And an omitted argument must preserve, not clear.
      expect(tracked.copyWith(isAvailable: false).stockRemaining, 4);
    });

    test('copyWith can set zero without it meaning "clear"', () {
      expect(_item(stock: 4).copyWith(stockRemaining: 0).stockRemaining, 0);
    });
  });

  group('MenuService.setStock', () {
    test('sends a number and returns the server\'s view', () async {
      final s = _service(respondStock: 7);
      final r = await s.service.setStock('item-1', 7);
      expect(s.sent.single, {'quantity': 7});
      expect(r.stockRemaining, 7);
      expect(r.isAvailable, isTrue);
    });

    test('sends an explicit null to turn tracking OFF', () async {
      // The payload must carry `quantity: null`, not omit the key — omitting
      // it would read as "no change" server-side.
      final s = _service(respondStock: null);
      final r = await s.service.setStock('item-1', null);
      expect(s.sent.single.containsKey('quantity'), isTrue);
      expect(s.sent.single['quantity'], isNull);
      expect(r.stockRemaining, isNull);
    });

    test('zero comes back as sold out, not as untracked', () async {
      final s = _service(respondStock: 0, respondAvailable: false);
      final r = await s.service.setStock('item-1', 0);
      expect(s.sent.single, {'quantity': 0});
      expect(r.stockRemaining, 0);
      expect(r.isAvailable, isFalse,
          reason: 'the server hides a dish at zero');
    });

    test('restocking from zero reports the dish available again', () async {
      // One tap, not two — otherwise a dish stays hidden with stock behind it.
      final s = _service(respondStock: 5, respondAvailable: true);
      final r = await s.service.setStock('item-1', 5);
      expect(r.stockRemaining, 5);
      expect(r.isAvailable, isTrue);
    });
  });

  group('the dish row surfaces a live count', () {
    testWidgets('a tracked dish shows "N left"', (tester) async {
      await tester.pumpWidget(MaterialApp(
        home: Scaffold(
          body: _Row(item: _item(stock: 2)),
        ),
      ));
      expect(find.textContaining('2 left'), findsOneWidget);
    });

    testWidgets('an untracked dish says nothing extra', (tester) async {
      // The row must be unchanged for every dish until one is opted in.
      await tester.pumpWidget(MaterialApp(
        home: Scaffold(body: _Row(item: _item())),
      ));
      expect(find.textContaining('left'), findsNothing);
      expect(find.textContaining('Available'), findsOneWidget);
    });

    testWidgets('a sold-out tracked dish reads "Unavailable · 0 left"',
        (tester) async {
      // The whole reason the count is on the row: this distinguishes a dish
      // someone switched off from one that genuinely ran out.
      await tester.pumpWidget(MaterialApp(
        home: Scaffold(
          body: _Row(
            item: MenuItem(
              id: 'i', name: 'Masala Dosa', isAvailable: false,
              isActive: true, basePrice: 80, stockRemaining: 0,
            ),
          ),
        ),
      ));
      expect(find.textContaining('Unavailable'), findsOneWidget);
      expect(find.textContaining('0 left'), findsOneWidget);
    });
  });
}

/// Minimal host for DishRow. `onChanged` is required by the widget but is
/// never invoked here — these tests only read what it renders.
class _Row extends StatelessWidget {
  const _Row({required this.item});
  final MenuItem item;

  @override
  Widget build(BuildContext context) =>
      DishRow(item: item, onChanged: (_) {});
}
