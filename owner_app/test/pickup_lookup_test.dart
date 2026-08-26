// Counter-side pickup by code.
//
// These drive the real OrderService/OrdersState over a MockClient, so the JSON
// contract, the state layer and the widget are all exercised together — a fake
// state object would prove only that the widget calls a method.
//
// The line these tests exist to hold: typing a code FINDS an order, it does not
// hand it over. Only the confirm tap does, and the request log is what proves
// it — a passing UI assertion would not.
import 'dart:convert';

import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:http/http.dart' as http;
import 'package:http/testing.dart';
import 'package:provider/provider.dart';
import 'package:shared_preferences/shared_preferences.dart';

import 'package:owner_app/services/api_client.dart';
import 'package:owner_app/services/order_service.dart';
import 'package:owner_app/state/orders_state.dart';
import 'package:owner_app/widgets/pickup_lookup_card.dart';

/// Every request the app made, in order — the evidence for "no status change
/// happened", which cannot be read off the screen.
late List<String> requestLog;

const String _orderId = '11111111-2222-3333-4444-555555555555';

Map<String, dynamic> _order({String status = 'READY'}) => {
      'order_id': _orderId,
      'status': status,
      'payment_status': 'PAID',
      'is_locked': false,
      'total_amount': 240.0,
      'created_at': '2026-08-26T10:00:00Z',
      'items': [
        {'id': 'i1', 'name': 'Masala Dosa', 'quantity': 2},
        {'id': 'i2', 'name': 'Filter Coffee', 'quantity': 1},
      ],
    };

/// A backend that knows exactly one code, scoped to one outlet — the same
/// shape the real `/pos/orders/lookup-pickup` returns.
///
/// [knownCode] is what THIS outlet's staff can find. Any other code misses,
/// which is how another outlet's code behaves against this account: the server
/// filters by the caller's own outlet, so it simply is not there.
http.Client _backend({
  String knownCode = '234567',
  bool locked = false,
  bool confirmSucceeds = true,
}) {
  return MockClient((req) async {
    final path = req.url.path;
    final body = req.body.isEmpty
        ? <String, dynamic>{}
        : jsonDecode(req.body) as Map<String, dynamic>;
    requestLog.add('${req.method} $path');

    if (path.endsWith('/pos/orders/lookup-pickup')) {
      final code = (body['pickup_code'] as String? ?? '').trim().toUpperCase();
      if (code != knownCode) {
        return http.Response(jsonEncode({'found': false}), 200,
            headers: {'content-type': 'application/json'});
      }
      return http.Response(
          jsonEncode({'found': true, 'locked': locked, 'order': _order()}), 200,
          headers: {'content-type': 'application/json'});
    }

    if (path.endsWith('/pos/orders/verify-pickup')) {
      if (!confirmSucceeds) {
        return http.Response(
            jsonEncode({'verified': false, 'attempts_remaining': 2}), 200,
            headers: {'content-type': 'application/json'});
      }
      return http.Response(
          jsonEncode(
              {'verified': true, 'order_id': _orderId, 'status': 'COMPLETED'}),
          200,
          headers: {'content-type': 'application/json'});
    }

    if (path.endsWith('/pos/orders')) {
      return http.Response(jsonEncode(<dynamic>[]), 200,
          headers: {'content-type': 'application/json'});
    }

    return http.Response(jsonEncode({'detail': 'unexpected ${req.url}'}), 404,
        headers: {'content-type': 'application/json'});
  });
}

const String _orderIdB = '99999999-8888-7777-6666-555555555555';

/// A second order, on its own code, with DIFFERENT items.
///
/// Distinct items are the point: with one fixture, "showed order B" and "never
/// cleared order A" render identically and no assertion can separate them.
Map<String, dynamic> _orderB() => {
      'order_id': _orderIdB,
      'status': 'PAID',
      'payment_status': 'PAID',
      'is_locked': false,
      'total_amount': 99.0,
      'created_at': '2026-08-27T10:00:00Z',
      'items': [
        {'id': 'b1', 'name': 'Idli Sambar', 'quantity': 3},
      ],
    };

/// Two live orders at one outlet: A on 234567, B on 876543.
///
/// [lookupDelay] holds the response open so a test can inspect what is on
/// screen while a request is genuinely in flight.
http.Client _twoOrderBackend({Duration lookupDelay = Duration.zero}) {
  return MockClient((req) async {
    final path = req.url.path;
    final body = req.body.isEmpty
        ? <String, dynamic>{}
        : jsonDecode(req.body) as Map<String, dynamic>;
    requestLog.add('${req.method} $path');

    if (path.endsWith('/pos/orders/lookup-pickup')) {
      if (lookupDelay > Duration.zero) await Future<void>.delayed(lookupDelay);
      final code = (body['pickup_code'] as String? ?? '').trim();
      final order = code == '234567'
          ? _order()
          : code == '876543'
              ? _orderB()
              : null;
      if (order == null) {
        return http.Response(jsonEncode({'found': false}), 200,
            headers: {'content-type': 'application/json'});
      }
      return http.Response(
          jsonEncode({'found': true, 'locked': false, 'order': order}), 200,
          headers: {'content-type': 'application/json'});
    }

    if (path.endsWith('/pos/orders/verify-pickup')) {
      return http.Response(
          jsonEncode({
            'verified': true,
            'order_id': body['order_id'],
            'status': 'COMPLETED',
          }),
          200,
          headers: {'content-type': 'application/json'});
    }

    if (path.endsWith('/pos/orders')) {
      return http.Response(jsonEncode(<dynamic>[]), 200,
          headers: {'content-type': 'application/json'});
    }

    return http.Response(jsonEncode({'detail': 'unexpected ${req.url}'}), 404,
        headers: {'content-type': 'application/json'});
  });
}

Widget _host(http.Client backend) {
  SharedPreferences.setMockInitialValues({'gusto_owner_access_token': 'staff'});
  final state = OrdersState(OrderService(ApiClient(httpClient: backend)));
  return ChangeNotifierProvider<OrdersState>.value(
    value: state,
    child: const MaterialApp(
      home: Scaffold(body: SingleChildScrollView(child: PickupLookupCard())),
    ),
  );
}

Future<void> _enter(WidgetTester tester, String code) async {
  await tester.enterText(find.byKey(PickupLookupCard.fieldKey), code);
  await tester.tap(find.byKey(PickupLookupCard.findButtonKey));
  await tester.pumpAndSettle();
}

int _countOf(String entry) => requestLog.where((e) => e == entry).length;

const String _lookup = 'POST /api/v1/pos/orders/lookup-pickup';
const String _verify = 'POST /api/v1/pos/orders/verify-pickup';

void main() {
  setUp(() => requestLog = []);

  group('finding an order', () {
    testWidgets('a correct code shows the order and its items', (tester) async {
      await tester.pumpWidget(_host(_backend()));
      await _enter(tester, '234567');

      expect(find.byKey(PickupLookupCard.resultKey), findsOneWidget);
      expect(find.text('Masala Dosa'), findsOneWidget);
      expect(find.text('2x'), findsOneWidget);
      expect(find.text('Filter Coffee'), findsOneWidget);
      expect(find.text('1x'), findsOneWidget);
      expect(find.byKey(PickupLookupCard.notFoundKey), findsNothing);
    });

    testWidgets('a wrong code says so plainly', (tester) async {
      await tester.pumpWidget(_host(_backend()));
      await _enter(tester, '999999');

      expect(find.byKey(PickupLookupCard.notFoundKey), findsOneWidget);
      expect(find.textContaining('No open order with that code'), findsOneWidget);
      // Not a silent failure, and not a half-rendered result.
      expect(find.byKey(PickupLookupCard.resultKey), findsNothing);
      expect(find.byKey(PickupLookupCard.confirmButtonKey), findsNothing);
    });

    testWidgets("another outlet's code simply does not resolve",
        (tester) async {
      // The server scopes the search to the caller's own outlet, so a code
      // that is perfectly valid elsewhere comes back as a miss here. From the
      // app's side that is indistinguishable from a wrong code — which is the
      // point: there is nothing to learn about the other outlet's orders.
      await tester.pumpWidget(_host(_backend(knownCode: '234567')));
      await _enter(tester, '876543'); // real code, different restaurant

      expect(find.byKey(PickupLookupCard.notFoundKey), findsOneWidget);
      expect(find.byKey(PickupLookupCard.confirmButtonKey), findsNothing);
      expect(_countOf(_verify), 0,
          reason: 'a cross-outlet miss must never reach verify-pickup');
    });

    testWidgets('an empty code is refused before any request', (tester) async {
      await tester.pumpWidget(_host(_backend()));
      await tester.tap(find.byKey(PickupLookupCard.findButtonKey));
      await tester.pumpAndSettle();

      expect(find.text('Enter the pickup code.'), findsOneWidget);
      expect(requestLog, isEmpty);
    });
  });

  group('confirm is required', () {
    testWidgets('entering a correct code does NOT complete the order',
        (tester) async {
      await tester.pumpWidget(_host(_backend()));
      await _enter(tester, '234567');

      // The order was found...
      expect(find.byKey(PickupLookupCard.resultKey), findsOneWidget);
      // ...and the confirm button is waiting, not already pressed.
      expect(find.byKey(PickupLookupCard.confirmButtonKey), findsOneWidget);
      expect(find.text('Confirm pickup'), findsOneWidget);

      // The proof: exactly one lookup, and nothing that changes state.
      expect(_countOf(_lookup), 1);
      expect(_countOf(_verify), 0,
          reason: 'a matched code alone must not close the order');
    });

    testWidgets('repeated lookups still change nothing', (tester) async {
      await tester.pumpWidget(_host(_backend()));
      await _enter(tester, '234567');
      await _enter(tester, '234567');
      await _enter(tester, '234567');

      expect(_countOf(_lookup), 3);
      expect(_countOf(_verify), 0);
    });

    testWidgets('the confirm tap is what completes it', (tester) async {
      await tester.pumpWidget(_host(_backend()));
      await _enter(tester, '234567');
      expect(_countOf(_verify), 0);

      await tester.tap(find.byKey(PickupLookupCard.confirmButtonKey));
      await tester.pumpAndSettle();

      expect(_countOf(_verify), 1, reason: 'confirm should verify exactly once');
      expect(find.text('Pickup confirmed.'), findsOneWidget);
      // The matched order is cleared once handed over, so a second tap cannot
      // land on a stale result.
      expect(find.byKey(PickupLookupCard.confirmButtonKey), findsNothing);
    });

    testWidgets('a refused confirm leaves a readable message, not a success',
        (tester) async {
      await tester.pumpWidget(_host(_backend(confirmSucceeds: false)));
      await _enter(tester, '234567');
      await tester.tap(find.byKey(PickupLookupCard.confirmButtonKey));
      await tester.pumpAndSettle();

      expect(find.text('Pickup confirmed.'), findsNothing);
      expect(find.textContaining('no longer open'), findsOneWidget);
    });

    testWidgets('a locked order offers no confirm button at all',
        (tester) async {
      await tester.pumpWidget(_host(_backend(locked: true)));
      await _enter(tester, '234567');

      expect(find.byKey(PickupLookupCard.resultKey), findsOneWidget);
      expect(find.textContaining('locked after 3 failed attempts'),
          findsOneWidget);
      expect(find.byKey(PickupLookupCard.confirmButtonKey), findsNothing,
          reason: 'lookup must not become a way round the lockout');
    });
  });

  group('the result always matches the box', () {
    testWidgets('editing the code after a match clears the stale order',
        (tester) async {
      await tester.pumpWidget(_host(_backend()));
      await _enter(tester, '234567');
      expect(find.byKey(PickupLookupCard.resultKey), findsOneWidget);

      await tester.enterText(find.byKey(PickupLookupCard.fieldKey), '2345');
      await tester.pumpAndSettle();

      expect(find.byKey(PickupLookupCard.resultKey), findsNothing,
          reason: 'items on screen must belong to the code in the field');
      expect(_countOf(_verify), 0);
    });

    testWidgets('a server error is reported, not swallowed', (tester) async {
      final broken = MockClient((req) async {
        requestLog.add('${req.method} ${req.url.path}');
        return http.Response(jsonEncode({'detail': 'boom'}), 500,
            headers: {'content-type': 'application/json'});
      });
      await tester.pumpWidget(_host(broken));
      await _enter(tester, '234567');

      expect(find.textContaining('Could not search right now'), findsOneWidget);
      // Distinct from "not found" — staff must not go looking for a bag that
      // the server never actually denied having.
      expect(find.byKey(PickupLookupCard.notFoundKey), findsNothing);
    });
  });

  // ------------------------------------------------------------------------
  // A COMPLETED order must never come back on screen.
  //
  // Reported from the counter: entering a code for a new order showed the
  // PREVIOUS, already-collected order's panel and status. The backend was
  // never at fault — /lookup-pickup is scoped by code AND by
  // `status = ANY(live)`, so a COMPLETED order is unreachable by any code.
  //
  // The staleness was local. `_confirm()` left `_match` populated and relied
  // solely on `_phase == done` to hide it, and `_find()`'s empty-code early
  // return moved the phase off `done` without clearing `_match` — which
  // re-opened the build guard on the finished order. Two orders are used
  // throughout because a single-order fixture cannot tell "showed the right
  // one" from "never changed".
  // ------------------------------------------------------------------------
  group('a completed order does not come back', () {
    Future<void> completeA(WidgetTester tester) async {
      await _enter(tester, '234567');
      expect(find.text('Masala Dosa'), findsOneWidget,
          reason: 'order A should be found before we confirm it');
      await tester.tap(find.byKey(PickupLookupCard.confirmButtonKey));
      await tester.pumpAndSettle();
      expect(find.textContaining('Pickup confirmed'), findsOneWidget);
    }

    testWidgets('an empty Find after a confirmation shows no stale panel',
        (tester) async {
      // The reproduction. Confirming clears the box, so it looks ready for the
      // next code — pressing Find before typing is a natural counter mistake.
      await tester.pumpWidget(_host(_twoOrderBackend()));
      await completeA(tester);

      await tester.tap(find.byKey(PickupLookupCard.findButtonKey));
      await tester.pumpAndSettle();

      expect(find.byKey(PickupLookupCard.resultKey), findsNothing,
          reason: 'the collected order must not reappear on an empty Find');
      expect(find.text('Masala Dosa'), findsNothing);
      expect(find.textContaining('Enter the pickup code'), findsOneWidget);
    });

    testWidgets('it holds across repeated empty Find presses', (tester) async {
      // Once could pass off a single stale value while leaving the underlying
      // field populated; pressing again proves the order is actually gone
      // rather than merely hidden by whatever phase the first press produced.
      await tester.pumpWidget(_host(_twoOrderBackend()));
      await completeA(tester);

      for (var i = 1; i <= 3; i++) {
        await tester.tap(find.byKey(PickupLookupCard.findButtonKey));
        await tester.pumpAndSettle();
        expect(find.byKey(PickupLookupCard.resultKey), findsNothing,
            reason: 'stale panel returned on empty Find #$i');
        expect(find.text('Masala Dosa'), findsNothing,
            reason: 'order A returned on empty Find #$i');
      }
    });

    testWidgets('the next code shows ITS order, not the previous one',
        (tester) async {
      await tester.pumpWidget(_host(_twoOrderBackend()));
      await completeA(tester);
      await _enter(tester, '876543');

      expect(find.text('Idli Sambar'), findsOneWidget);
      expect(find.text('Masala Dosa'), findsNothing,
          reason: 'order B\'s panel must not carry order A\'s items');
    });

    testWidgets('the previous order is gone while the next lookup is in flight',
        (tester) async {
      // The window a customer actually sees: staff have typed the new code and
      // the request has not landed yet. The old order must already be gone.
      await tester.pumpWidget(_host(
          _twoOrderBackend(lookupDelay: const Duration(seconds: 2))));
      await completeA(tester);

      await tester.enterText(
          find.byKey(PickupLookupCard.fieldKey), '876543');
      await tester.pump();
      await tester.tap(find.byKey(PickupLookupCard.findButtonKey));
      await tester.pump(const Duration(milliseconds: 200));

      expect(find.text('Masala Dosa'), findsNothing);
      expect(find.byKey(PickupLookupCard.resultKey), findsNothing);

      await tester.pumpAndSettle();
      expect(find.text('Idli Sambar'), findsOneWidget);
    });

    testWidgets('a second submission cannot start while one is in flight',
        (tester) async {
      await tester.pumpWidget(_host(
          _twoOrderBackend(lookupDelay: const Duration(seconds: 1))));
      await tester.enterText(
          find.byKey(PickupLookupCard.fieldKey), '234567');
      await tester.tap(find.byKey(PickupLookupCard.findButtonKey));
      await tester.pump(const Duration(milliseconds: 100));

      final button = tester.widget<FilledButton>(
          find.byKey(PickupLookupCard.findButtonKey));
      final field =
          tester.widget<TextField>(find.byKey(PickupLookupCard.fieldKey));
      expect(button.onPressed, isNull, reason: 'Find must be disabled in flight');
      expect(field.enabled, isFalse, reason: 'the field must be locked in flight');

      await tester.pumpAndSettle();
      expect(_countOf(_lookup), 1, reason: 'exactly one lookup should be sent');
    });
  });
}
