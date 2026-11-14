// TASK 2 — the Call button asks what happened before it counts the attempt.
//
// HOW IT WORKED BEFORE: tapping Call opened the dialer and then ALWAYS fired
// POST /pos/orders/{id}/call, so an accidental tap — or a tap by someone who
// then decided not to ring — moved call_state to CALLED and bumped
// call_attempts. The counter measured TAPS, not calls.
//
// NOW: the dialer opens, and when the app comes back to the foreground a
// three-way dialog asks. "Spoke to customer" and "Called, no answer" both
// send the one existing request. `call_state` has only PENDING / CALLED /
// UNREACHABLE (migration 034 line 216) and UNREACHABLE is reachable solely by
// REJECTING the order, so no existing value can record "nobody answered" on a
// live order — distinguishing the two in DATA would need a migration, and the
// distinction therefore lives in the question only. "Did not call" sends
// nothing at all.
//
// WHY THIS DRIVES THE CARD DIRECTLY instead of through OrdersState.load():
// load() starts a Timer.periodic (orders_state.dart:276) which, together with
// a Consumer rebuild, never lets pumpAndSettle go quiet — the suite wedges
// with no timeout able to interrupt it. The attempt counter is therefore
// asserted from the OBSERVED HTTP traffic (the server's own record) plus the
// rendered label on a card built from an explicit Order, which is the shape
// every other widget test in this suite uses.
import 'dart:convert';

import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:http/http.dart' as http;
import 'package:http/testing.dart';
import 'package:provider/provider.dart';
import 'package:shared_preferences/shared_preferences.dart';

import 'package:owner_app/models/order.dart';
import 'package:owner_app/services/api_client.dart';
import 'package:owner_app/services/order_service.dart';
import 'package:owner_app/state/orders_state.dart';
import 'package:owner_app/widgets/order_card.dart';

const _orderId = 'aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee';

late List<String> requestLog;
late List<Uri> launched;
late int serverCallAttempts;

http.Response _json(Object body) => http.Response(jsonEncode(body), 200,
    headers: {'content-type': 'application/json'});

Order _order({String phone = '9499956612', int callAttempts = 0}) =>
    Order.fromJson({
      'order_id': _orderId,
      'status': 'PREPARING',
      'payment_status': 'PENDING',
      'payment_mode': 'PAY_AT_PICKUP',
      'is_locked': false,
      'total_amount': 240,
      'created_at': '2026-10-28T10:00:00Z',
      'contact_name': 'Asha',
      'contact_phone': phone,
      'contact_visible': true,
      'call_state': callAttempts == 0 ? 'PENDING' : 'CALLED',
      'call_attempts': callAttempts,
      'items': const [
        {'id': 'i1', 'name': 'Masala Dosa', 'quantity': 2}
      ],
    });

/// The server. Records every request and counts the attempts it was told
/// about, which is the thing the owner's counter is meant to reflect.
ApiClient _api() => ApiClient(httpClient: MockClient((req) async {
      requestLog.add('${req.method} ${req.url.path}');
      if (req.url.path.endsWith('/call')) {
        serverCallAttempts++;
        return _json({
          'order_id': _orderId,
          'call_state': 'CALLED',
          'call_attempts': serverCallAttempts,
        });
      }
      if (req.url.path.endsWith('/pos/orders')) return _json(const []);
      return _json(const {});
    }));

int _callRequests() =>
    requestLog.where((e) => e == 'POST /api/v1/pos/orders/$_orderId/call').length;

/// Pumps the expanded card for [order]. No OrdersState.load(), so no poll
/// timer — see the file header.
Future<void> _openCard(WidgetTester tester, {required Order order}) async {
  final api = _api();
  final state = OrdersState(OrderService(api));
  addTearDown(state.dispose);

  await tester.pumpWidget(MultiProvider(
    providers: [
      Provider<ApiClient>.value(value: api),
      Provider<OrderService>(create: (_) => OrderService(api)),
      ChangeNotifierProvider<OrdersState>.value(value: state),
    ],
    child: MaterialApp(
      home: Scaffold(
        body: SingleChildScrollView(
          child: OrderCard(
            order: order,
            // The fake dialer: records the URI and reports success, so no
            // platform channel is involved.
            launcher: (uri) async {
              launched.add(uri);
              return true;
            },
          ),
        ),
      ),
    ),
  ));
  await tester.pump();
  await tester.tap(find.text('#${order.shortId}'));
  await tester.pumpAndSettle();
}

/// Leaves the app and comes back, in the order a real device reports it.
///
/// The intermediate states are REQUIRED, not decoration: Flutter asserts on
/// any jump its state machine does not allow (app_lifecycle_listener.dart
/// lines 225 and 257), so this walks the full documented path a device takes —
/// resumed -> inactive -> hidden -> paused on the way out, and back again.
Future<void> _leaveAndReturn(WidgetTester tester) async {
  for (final s in const [
    AppLifecycleState.inactive,
    AppLifecycleState.hidden,
    AppLifecycleState.paused,
    AppLifecycleState.hidden,
    AppLifecycleState.inactive,
    AppLifecycleState.resumed,
  ]) {
    tester.binding.handleAppLifecycleStateChanged(s);
    await tester.pump();
  }
  await tester.pumpAndSettle();
}

/// Taps Call, then brings the app back to the foreground.
Future<void> _callAndResume(WidgetTester tester) async {
  await tester.tap(find.byKey(const Key('order_call_button')));
  await tester.pumpAndSettle();
  await _leaveAndReturn(tester);
}

void main() {
  setUp(() {
    requestLog = [];
    launched = [];
    serverCallAttempts = 0;
    // The staff token every /pos call needs (outlet_settings_test.dart:77).
    // Without it ApiClient throws before issuing the request and
    // OrdersState.logCall swallows the error — the attempt would silently
    // never be recorded, which is exactly what these tests must detect.
    SharedPreferences.setMockInitialValues(
        {'gusto_owner_access_token': 'staff'});
  });

  testWidgets('the dialer gets the normalized +91 number and NOTHING is '
      'recorded before the outcome is chosen', (tester) async {
    await _openCard(tester, order: _order());
    await _callAndResume(tester);

    expect(launched.single, Uri.parse('tel:+919499956612'),
        reason: 'a legacy bare-ten-digit contact dials as +91');
    expect(find.byKey(const Key('call_outcome_dialog')), findsOneWidget);
    expect(_callRequests(), 0,
        reason: 'the attempt is recorded by the ANSWER, not by the tap');
  });

  testWidgets('"Did not call" sends nothing and leaves the counter alone',
      (tester) async {
    await _openCard(tester, order: _order());
    await _callAndResume(tester);

    await tester.tap(find.byKey(const Key('call_outcome_did_not_call')));
    await tester.pumpAndSettle();

    expect(_callRequests(), 0);
    expect(serverCallAttempts, 0, reason: 'the server was never told');
    expect(find.text('Call'), findsOneWidget,
        reason: 'the button never becomes "Call again (1)"');
  });

  testWidgets('dismissing the dialog also records nothing', (tester) async {
    await _openCard(tester, order: _order());
    await _callAndResume(tester);

    // Tap the barrier: an unanswered question must not assert a call.
    await tester.tapAt(const Offset(10, 10));
    await tester.pumpAndSettle();

    expect(find.byKey(const Key('call_outcome_dialog')), findsNothing);
    expect(_callRequests(), 0);
  });

  testWidgets('"Called, no answer" records exactly one attempt',
      (tester) async {
    await _openCard(tester, order: _order());
    await _callAndResume(tester);

    await tester.tap(find.byKey(const Key('call_outcome_no_answer')));
    await tester.pumpAndSettle();

    expect(_callRequests(), 1, reason: 'requests seen: $requestLog');
    expect(serverCallAttempts, 1, reason: 'the counter went up by exactly one');
  });

  testWidgets('"Spoke to customer" records exactly one attempt',
      (tester) async {
    await _openCard(tester, order: _order());
    await _callAndResume(tester);

    await tester.tap(find.byKey(const Key('call_outcome_spoke')));
    await tester.pumpAndSettle();

    expect(_callRequests(), 1, reason: 'requests seen: $requestLog');
    expect(serverCallAttempts, 1);
  });

  testWidgets('an order already called shows the attempt count', (tester) async {
    await _openCard(tester, order: _order(callAttempts: 1));
    expect(find.text('Call again (1)'), findsOneWidget);
  });

  testWidgets('a phone that does not normalize disables Call and shows no '
      'counter', (tester) async {
    // Five digits cannot be an Indian mobile, so there is nothing to dial.
    // The button must be dead rather than opening a dialer on a number that
    // cannot connect — and it must not advertise attempts either.
    await _openCard(tester, order: _order(phone: '12345', callAttempts: 2));

    expect(find.byKey(const Key('order_call_button')), findsOneWidget);
    final button = tester.widget<FilledButton>(
        find.byKey(const Key('order_call_button')));
    expect(button.onPressed, isNull, reason: 'the button is disabled');
    expect(find.textContaining('Call again'), findsNothing,
        reason: 'no counter on a number that cannot be dialed');
    expect(launched, isEmpty);
  });

  testWidgets('the dialog is asked once per tap, not on every resume',
      (tester) async {
    await _openCard(tester, order: _order());
    await _callAndResume(tester);
    await tester.tap(find.byKey(const Key('call_outcome_did_not_call')));
    await tester.pumpAndSettle();

    // A later resume that follows no Call tap must not re-ask.
    await _leaveAndReturn(tester);

    expect(find.byKey(const Key('call_outcome_dialog')), findsNothing);
    expect(_callRequests(), 0);
  });

  testWidgets('rotating the screen does not re-show the dialog',
      (tester) async {
    await _openCard(tester, order: _order());
    await _callAndResume(tester);
    await tester.tap(find.byKey(const Key('call_outcome_spoke')));
    await tester.pumpAndSettle();
    expect(_callRequests(), 1, reason: 'requests seen: $requestLog');

    // A rotation rebuilds the widget; the latch must stay spent.
    tester.view.physicalSize = const Size(2532, 1170);
    addTearDown(tester.view.reset);
    await tester.pumpAndSettle();
    await _leaveAndReturn(tester);

    expect(find.byKey(const Key('call_outcome_dialog')), findsNothing);
    expect(_callRequests(), 1, reason: 'still exactly one attempt');
  });
}
