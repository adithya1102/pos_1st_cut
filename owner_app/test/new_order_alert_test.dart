// The live in-app new-order alert.
//
// Owner app polls its own order feed while it is on screen; a paid order that
// was not there last time is announced with a banner, a chime and a buzz.
//
// Two lines these tests exist to hold:
//   1. The queue already on the counter at sign-in is NOT news. Alerting on it
//      would train staff to ignore the sound that matters.
//   2. Each order is announced exactly once. A poll every 15 seconds re-reads
//      the same rows over and over, so "seen it" has to be remembered rather
//      than re-derived from what is on screen.
//
// Sound and vibration are asserted at the platform channel, not through a fake:
// what matters is that SystemSound/HapticFeedback are actually invoked, and a
// mock object would only prove the app called its own wrapper.
//
// Out of scope here, deliberately: delivery while the app is backgrounded or
// closed. That is the push path, and nothing in this feature touches it.
import 'dart:convert';

import 'package:flutter/material.dart';
import 'package:flutter/services.dart';
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

// Real UUID-shaped ids: Order.shortId keeps anything 8 characters or shorter
// whole and otherwise shows the last six, so a toy id would not exercise the
// label staff actually read off the banner.
const String _idA = '11111111-2222-3333-4444-555555881111';
const String _idB = '99999999-8888-7777-6666-555555992222';

Map<String, dynamic> _order(
  String id, {
  String status = 'RECEIVED',
  String paymentStatus = 'PAID',
  double total = 240,
  List<Map<String, dynamic>>? items,
}) =>
    {
      'order_id': id,
      'status': status,
      'payment_status': paymentStatus,
      'is_locked': false,
      'total_amount': total,
      'created_at': '2026-09-02T10:00:00Z',
      'items': items ??
          [
            {'id': '${id}i1', 'name': 'Masala Dosa', 'quantity': 2},
            {'id': '${id}i2', 'name': 'Filter Coffee', 'quantity': 1},
          ],
    };

/// A backend whose order feed changes between polls.
///
/// [feeds] is consumed one entry per `GET /pos/orders`; the last entry sticks
/// once the list runs out, which is what a real quiet period looks like.
http.Client _backend(List<List<Map<String, dynamic>>> feeds) {
  var call = 0;
  return MockClient((req) async {
    final path = req.url.path;

    if (path.endsWith('/pos/orders')) {
      final feed = feeds[call < feeds.length ? call : feeds.length - 1];
      call++;
      return http.Response(jsonEncode(feed), 200,
          headers: {'content-type': 'application/json'});
    }

    if (path.endsWith('/pos/outlet')) {
      return http.Response(
          jsonEncode({
            'id': 'aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee',
            'location_name': 'Anand Bhavan',
            'is_visible': true,
            'image_url': null,
          }),
          200,
          headers: {'content-type': 'application/json'});
    }

    if (path.endsWith('/pos/menu-items') || path.endsWith('/pos/offers')) {
      return http.Response(jsonEncode(<dynamic>[]), 200,
          headers: {'content-type': 'application/json'});
    }

    return http.Response(jsonEncode({'detail': 'unexpected ${req.url}'}), 404,
        headers: {'content-type': 'application/json'});
  });
}

/// Every SystemSound/HapticFeedback call the app made, in order.
late List<String> feedbackLog;

void _captureFeedback(WidgetTester tester) {
  feedbackLog = [];
  tester.binding.defaultBinaryMessenger.setMockMethodCallHandler(
    SystemChannels.platform,
    (call) async {
      if (call.method == 'SystemSound.play' ||
          call.method == 'HapticFeedback.vibrate') {
        feedbackLog.add('${call.method}:${call.arguments}');
      }
      return null;
    },
  );
}

const Duration _poll = Duration(seconds: 15);

Widget _host(http.Client backend) {
  SharedPreferences.setMockInitialValues({'gusto_owner_access_token': 'staff'});
  final api = ApiClient(httpClient: backend);
  return MultiProvider(
    providers: [
      ChangeNotifierProvider(create: (_) => AuthState(AuthService(api))),
      ChangeNotifierProvider(
        create: (_) => HomeState(OutletService(api), MenuService(api)),
      ),
      ChangeNotifierProvider(
        create: (_) => OrdersState(OrderService(api), pollInterval: _poll),
      ),
      ChangeNotifierProvider(create: (_) => OffersState(OfferService(api))),
      Provider(create: (_) => StaffPushService(OrderService(api))),
    ],
    child: const MaterialApp(home: HomeScreen()),
  );
}

/// Advance past one poll interval, let the response land, and let the banner
/// finish animating in — tapping a snackbar mid-entrance misses it.
Future<void> _tick(WidgetTester tester) async {
  await tester.pump(_poll + const Duration(seconds: 1));
  await tester.pump();
  await tester.pumpAndSettle();
}

/// See [outlet_name_test] — unmounting stops the poll timer, and a live timer
/// at teardown fails the test.
Future<void> _close(WidgetTester tester) async {
  await tester.pumpWidget(const SizedBox.shrink());
  await tester.pumpAndSettle();
}

void main() {
  setUp(() => feedbackLog = []);

  group('the state layer decides what counts as new', () {
    // Driven directly, without a widget, so these assertions are about the
    // arrival rule itself rather than about anything on screen.
    OrdersState stateOn(List<List<Map<String, dynamic>>> feeds) {
      SharedPreferences.setMockInitialValues(
          {'gusto_owner_access_token': 'staff'});
      return OrdersState(
          OrderService(ApiClient(httpClient: _backend(feeds))));
    }

    test('the queue present at sign-in raises no alert', () async {
      final state = stateOn([
        [_order('a'), _order('b')],
      ]);
      await state.load();

      expect(state.orders, hasLength(2));
      expect(state.newOrderAlert.value, isNull,
          reason: 'orders already on the counter are not arrivals');
    });

    test('an order that appears after the baseline does', () async {
      final state = stateOn([
        [_order('a')],
        [_order('b'), _order('a')],
      ]);
      await state.load();
      await state.load();

      final alert = state.newOrderAlert.value;
      expect(alert, isNotNull);
      expect(alert!.order.orderId, 'b');
      expect(alert.alsoArrived, 0);
    });

    test('the same order is never announced twice', () async {
      final state = stateOn([
        [_order('a')],
        [_order('b'), _order('a')],
        [_order('b'), _order('a')],
        [_order('b'), _order('a')],
      ]);
      await state.load();
      await state.load();
      state.consumeAlert();

      // Two more polls over an unchanged feed — the rows are still there, and
      // still must not re-fire.
      await state.load();
      await state.load();
      expect(state.newOrderAlert.value, isNull);
    });

    test('several at once are counted, not collapsed', () async {
      final state = stateOn([
        [_order('a')],
        [_order('c'), _order('b'), _order('a')],
      ]);
      await state.load();
      await state.load();

      final alert = state.newOrderAlert.value;
      expect(alert, isNotNull);
      // Feed is newest-first, so the head is the one to name.
      expect(alert!.order.orderId, 'c');
      expect(alert.alsoArrived, 1, reason: 'the second arrival is not silent');
    });

    test('an unpaid order does not alert until it is paid', () async {
      final state = stateOn([
        [],
        [_order('a', paymentStatus: 'PENDING', status: 'CREATED')],
        [_order('a')],
      ]);
      await state.load();
      await state.load();
      expect(state.newOrderAlert.value, isNull,
          reason: 'an unpaid order is not yet the outlet\'s problem');

      await state.load();
      expect(state.newOrderAlert.value?.order.orderId, 'a');
    });

    test('logout clears the baseline so the next outlet is not inherited',
        () async {
      final state = stateOn([
        [_order('a')],
        [_order('a')],
      ]);
      await state.load();
      expect(state.orders, hasLength(1));

      state.reset();
      expect(state.orders, isEmpty,
          reason: 'the previous outlet\'s rows must not survive logout');

      // The next sign-in takes its own baseline: the same order id comes back
      // and is still not announced, because it was already on the counter when
      // this account opened the app.
      await state.load();
      expect(state.newOrderAlert.value, isNull);
    });

    test('a failed poll leaves the baseline alone', () async {
      // A dropped request must not look like "the queue emptied", and the
      // recovery must not then announce every surviving order as new.
      SharedPreferences.setMockInitialValues(
          {'gusto_owner_access_token': 'staff'});
      var call = 0;
      final flaky = MockClient((req) async {
        call++;
        if (call == 2) {
          return http.Response(jsonEncode({'detail': 'boom'}), 500,
              headers: {'content-type': 'application/json'});
        }
        return http.Response(jsonEncode([_order('a')]), 200,
            headers: {'content-type': 'application/json'});
      });
      final state =
          OrdersState(OrderService(ApiClient(httpClient: flaky)));

      await state.load();
      await state.load(); // fails
      expect(state.error, isNotNull);
      await state.load(); // recovers, same single order

      expect(state.newOrderAlert.value, isNull,
          reason: 'a recovered poll must not re-announce a known order');
    });
  });

  group('the alert on screen', () {
    testWidgets('a new order raises a banner naming it', (tester) async {
      _captureFeedback(tester);
      await tester.pumpWidget(_host(_backend([
        [],
        [_order(_idA, total: 240)],
      ])));
      await tester.pumpAndSettle();

      // Nothing yet — the app has just opened onto an empty queue.
      expect(find.byKey(HomeScreen.newOrderBannerKey), findsNothing);

      await _tick(tester);

      expect(find.byKey(HomeScreen.newOrderBannerKey), findsOneWidget);
      // Names the order: the short id, what is in it, and what it is worth.
      expect(find.textContaining('#881111'), findsOneWidget);
      expect(find.textContaining('3 items'), findsOneWidget);
      expect(find.textContaining('240'), findsOneWidget);

      await _close(tester);
    });

    testWidgets('it chimes and vibrates', (tester) async {
      _captureFeedback(tester);
      await tester.pumpWidget(_host(_backend([
        [],
        [_order(_idA)],
      ])));
      await tester.pumpAndSettle();
      expect(feedbackLog, isEmpty);

      await _tick(tester);

      expect(feedbackLog.where((e) => e.startsWith('SystemSound.play')),
          hasLength(1),
          reason: 'a busy counter needs to HEAR this, not just see it');
      expect(feedbackLog.where((e) => e.startsWith('HapticFeedback.vibrate')),
          hasLength(1),
          reason: 'a phone on silent in an apron pocket still has to buzz');

      await _close(tester);
    });

    testWidgets('the queue at sign-in is silent', (tester) async {
      // The regression that would make this feature useless: opening the app to
      // four orders already on the counter and getting four alerts.
      _captureFeedback(tester);
      await tester.pumpWidget(_host(_backend([
        [_order('a'), _order('b'), _order('c'), _order('d')],
      ])));
      await tester.pumpAndSettle();

      expect(find.byKey(HomeScreen.newOrderBannerKey), findsNothing);
      expect(feedbackLog, isEmpty);

      // And it stays silent across the polls that follow.
      await _tick(tester);
      expect(find.byKey(HomeScreen.newOrderBannerKey), findsNothing);
      expect(feedbackLog, isEmpty);

      await _close(tester);
    });

    testWidgets('an unchanged queue does not re-alert on every poll',
        (tester) async {
      _captureFeedback(tester);
      await tester.pumpWidget(_host(_backend([
        [],
        [_order(_idA)],
      ])));
      await tester.pumpAndSettle();

      await _tick(tester);
      expect(feedbackLog, hasLength(2)); // one chime + one buzz

      // Three more polls returning the same row.
      await _tick(tester);
      await _tick(tester);
      await _tick(tester);

      expect(feedbackLog, hasLength(2),
          reason: 'polling the same order again is not a new order');

      await _close(tester);
    });

    testWidgets('the banner jumps to the Orders tab', (tester) async {
      _captureFeedback(tester);
      await tester.pumpWidget(_host(_backend([
        [],
        [_order(_idA)],
      ])));
      await tester.pumpAndSettle();
      await _tick(tester);

      // Starts on the Menu tab; the alert is actionable from there.
      expect(
        find.descendant(
          of: find.byType(AppBar),
          matching: find.text('Menu & Outlet'),
        ),
        findsOneWidget,
      );

      await tester.tap(find.text('View'));
      await tester.pumpAndSettle();

      expect(
        find.descendant(of: find.byType(AppBar), matching: find.text('Orders')),
        findsOneWidget,
      );

      await _close(tester);
    });

    testWidgets('two arrivals in one poll say so', (tester) async {
      _captureFeedback(tester);
      await tester.pumpWidget(_host(_backend([
        [],
        [_order(_idA), _order(_idB)],
      ])));
      await tester.pumpAndSettle();
      await _tick(tester);

      expect(find.textContaining('#881111'), findsOneWidget);
      expect(find.textContaining('+1 more'), findsOneWidget,
          reason: 'the second order must not vanish behind the first');

      await _close(tester);
    });
  });
}
