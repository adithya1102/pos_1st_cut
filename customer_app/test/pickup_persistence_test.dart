// Order-status UI state must survive backgrounding, a process kill, and a
// reopen — not live only in navigation-time widget memory.
//
// Two distinct causes, fixed on their own terms (see the diagnosis):
//
//  * The pickup CODE and payment status come from the server via the poll, so
//    they were already durable — the only gap was that a RESUME did not force
//    an immediate re-fetch. Covered by the "resume" group.
//  * The travel flags ("I'm leaving" / "I've arrived") and the pickup ack
//    ("I've picked this up") are client-only — the server records the travel
//    events but does not expose them in OrderOut, and the ack has no server
//    field at all. They now persist per order and restore on entry. Covered by
//    the "durable flags" group.
import 'dart:convert';

import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:http/http.dart' as http;
import 'package:http/testing.dart';
import 'package:provider/provider.dart';
import 'package:shared_preferences/shared_preferences.dart';

import 'package:customer_app/screens/pickup_screen.dart';
import 'package:customer_app/services/api_client.dart';
import 'package:customer_app/services/cashfree_service.dart';
import 'package:customer_app/services/location_service.dart';
import 'package:customer_app/services/order_service.dart';
import 'package:customer_app/state/cart_state.dart';
import 'package:customer_app/theme/app_theme.dart';
import 'package:customer_app/theme/theme_provider.dart';

const String _orderId = '11111111-2222-3333-4444-555555555555';
String _flagKey(String id) => 'pickup_ui_$id';

/// Never invoked in these tests (retry is not exercised); present only so the
/// provider lookup PickupScreen would do on retry cannot fail.
class _NoCashfree implements CashfreeService {
  @override
  Future<CheckoutResult> openCheckout({
    required String orderId,
    required String paymentSessionId,
  }) async =>
      const CheckoutResult(CheckoutOutcome.notStarted);
}

/// A backend for one order. [statusOf] is re-read on every poll, so a test can
/// flip payment_status between polls to model a webhook landing.
ApiClient _api({
  required String Function() statusOf,
  String? pickupCode,
  List<String>? postLog,
}) {
  final api = ApiClient(
    client: MockClient((req) async {
      if (req.method == 'POST') {
        postLog?.add(req.url.path);
        return http.Response(jsonEncode({'ok': true}), 200,
            headers: {'content-type': 'application/json'});
      }
      final status = statusOf();
      final paid = status == 'PAID' ||
          const {'RECEIVED', 'PREPARING', 'READY', 'COMPLETED'}.contains(status);
      return http.Response(
        jsonEncode({
          'id': _orderId,
          'status': status,
          'payment_status': paid ? 'PAID' : 'PENDING',
          'pickup_code': paid ? pickupCode : null,
          'total_amount': 240,
          'items': [
            {'name': 'Masala Dosa', 'quantity': 2}
          ],
        }),
        200,
        headers: {'content-type': 'application/json'},
      );
    }),
  );
  return api;
}

Widget _host(ApiClient api) {
  return MultiProvider(
    providers: [
      Provider<ApiClient>.value(value: api),
      Provider<OrderService>(create: (_) => OrderService(api)),
      Provider<CashfreeService>(create: (_) => _NoCashfree()),
      Provider<LocationService>(create: (_) => LocationService()),
      ChangeNotifierProvider<CartState>(create: (_) => CartState()),
      ChangeNotifierProvider<ThemeProvider>(create: (_) => ThemeProvider()),
    ],
    child: MaterialApp(
      theme: AppTheme.light(),
      home: const PickupScreen(orderId: _orderId),
    ),
  );
}

Future<void> _close(WidgetTester tester) async {
  await tester.pumpWidget(const SizedBox.shrink());
  await tester.pumpAndSettle();
}

/// Drive a full background → foreground lifecycle transition, so only the
/// `resumed` edge (which PickupScreen listens for) fires.
Future<void> _backgroundAndResume(WidgetTester tester) async {
  final b = tester.binding;
  b.handleAppLifecycleStateChanged(AppLifecycleState.inactive);
  b.handleAppLifecycleStateChanged(AppLifecycleState.hidden);
  b.handleAppLifecycleStateChanged(AppLifecycleState.paused);
  b.handleAppLifecycleStateChanged(AppLifecycleState.hidden);
  b.handleAppLifecycleStateChanged(AppLifecycleState.inactive);
  b.handleAppLifecycleStateChanged(AppLifecycleState.resumed);
  await tester.pump();
}

void main() {
  group('durable travel + ack flags survive a rebuild', () {
    testWidgets('a persisted "departed" restores the en-route state',
        (tester) async {
      // The bug: after "I\'m leaving now", a background/kill reset the screen to
      // "I\'m leaving now" again. With the flag persisted, reopening restores
      // the en-route state instead.
      SharedPreferences.setMockInitialValues({
        'carevo_access_token': 't',
        _flagKey(_orderId): 'departed',
      });
      await tester.pumpWidget(_host(_api(statusOf: () => 'RECEIVED')));
      await tester.pump();
      await tester.pump();

      expect(find.text('On your way — we\'re timing your food.'), findsOneWidget);
      expect(find.text('I\'ve arrived'), findsOneWidget);
      expect(find.text('I\'m leaving now'), findsNothing,
          reason: 'a departed order must not offer to depart again');

      await _close(tester);
    });

    testWidgets('a persisted "picked_up" restores the acknowledged state',
        (tester) async {
      SharedPreferences.setMockInitialValues({
        'carevo_access_token': 't',
        _flagKey(_orderId): 'picked_up',
      });
      await tester.pumpWidget(_host(_api(statusOf: () => 'RECEIVED')));
      await tester.pump();
      await tester.pump();

      expect(find.byKey(const Key('ack_picked_up_note')), findsOneWidget);
      expect(find.byKey(const Key('ack_picked_up')), findsNothing,
          reason: 'the ack was already given — do not ask again');

      await _close(tester);
    });

    testWidgets('nothing persisted → the flags start false', (tester) async {
      SharedPreferences.setMockInitialValues({'carevo_access_token': 't'});
      await tester.pumpWidget(_host(_api(statusOf: () => 'RECEIVED')));
      await tester.pump();
      await tester.pump();

      expect(find.text('I\'m leaving now'), findsOneWidget);
      expect(find.byKey(const Key('ack_picked_up')), findsOneWidget);

      await _close(tester);
    });

    testWidgets('tapping "I\'ve arrived" persists, and it survives a reopen',
        (tester) async {
      // The full round trip: an action taken now must still be true after the
      // screen is destroyed and rebuilt (a process kill + reopen).
      SharedPreferences.setMockInitialValues({
        'carevo_access_token': 't',
        _flagKey(_orderId): 'departed',
      });
      final postLog = <String>[];
      final api = _api(statusOf: () => 'RECEIVED', postLog: postLog);

      await tester.pumpWidget(_host(api));
      await tester.pump();
      await tester.pump();
      expect(find.text('I\'ve arrived'), findsOneWidget);

      await tester.tap(find.text('I\'ve arrived'));
      await tester.pump();
      await tester.pump();
      expect(postLog.any((p) => p.endsWith('/arrived')), isTrue,
          reason: 'the tap still tells the server');

      // Destroy and rebuild the screen with the SAME order — the kill+reopen.
      await _close(tester);
      await tester.pumpWidget(_host(api));
      await tester.pump();
      await tester.pump();

      expect(find.text('You\'re here — head to the counter.'), findsOneWidget,
          reason: 'the arrival must survive the reopen');

      await _close(tester);
    });

    testWidgets('a completed order clears its persisted flags', (tester) async {
      SharedPreferences.setMockInitialValues({
        'carevo_access_token': 't',
        _flagKey(_orderId): 'departed,arrived',
      });
      await tester.pumpWidget(_host(
          _api(statusOf: () => 'COMPLETED', pickupCode: '482913')));
      await tester.pump();
      await tester.pump();

      final prefs = await SharedPreferences.getInstance();
      expect(prefs.getString(_flagKey(_orderId)), isNull,
          reason: 'a finished order should not leak a stored flag row');

      await _close(tester);
    });
  });

  group('the pickup code is re-fetched on resume, not just at navigation', () {
    testWidgets('a webhook that landed while backgrounded shows on resume',
        (tester) async {
      // The order is unpaid when the screen opens; payment confirms while the
      // app is in the background. On resume the screen must re-poll immediately
      // and reveal the code — not wait out a poll interval, and certainly not
      // stay blank.
      SharedPreferences.setMockInitialValues({'carevo_access_token': 't'});
      var paid = false;
      final api = _api(
        statusOf: () => paid ? 'PAID' : 'CREATED',
        pickupCode: '482913',
      );

      await tester.pumpWidget(_host(api));
      await tester.pump();
      // Opens unpaid: no code, just the placeholder.
      expect(find.text('482913'), findsNothing);
      expect(find.text('Appears after payment'), findsOneWidget);

      // The webhook lands while the app is away.
      paid = true;
      await _backgroundAndResume(tester);
      // No time advanced past the 4s poll interval — the ONLY thing that could
      // have re-fetched is the resume hook.
      await tester.pump();

      expect(find.text('482913'), findsOneWidget,
          reason: 'resume must force an immediate re-fetch of order status');

      await _close(tester);
    });
  });

  group('a full pickup walk survives a resume mid-flow', () {
    testWidgets('leaving → resume → arrived → picked up → kill + reopen',
        (tester) async {
      // The end-to-end walk Task 5 asks for. "Leaving" is represented by a
      // seeded flag (the depart button needs live GPS, which a widget test
      // cannot grant); every other step is driven for real, with a background
      // → foreground resume in the middle to prove nothing is lost across it.
      SharedPreferences.setMockInitialValues({
        'carevo_access_token': 't',
        _flagKey(_orderId): 'departed',
      });
      final api = _api(statusOf: () => 'RECEIVED', pickupCode: '482913');

      await tester.pumpWidget(_host(api));
      await tester.pump();
      await tester.pump();

      // Post-payment: code shown, en route.
      expect(find.text('482913'), findsOneWidget);
      expect(find.text('I\'ve arrived'), findsOneWidget);

      // Resume mid-flow — code and travel state both intact.
      await _backgroundAndResume(tester);
      await tester.pump();
      expect(find.text('482913'), findsOneWidget);
      expect(find.text('I\'ve arrived'), findsOneWidget);

      // Arrive.
      await tester.tap(find.text('I\'ve arrived'));
      await tester.pump();
      await tester.pump();
      expect(find.text('You\'re here — head to the counter.'), findsOneWidget);

      // Acknowledge pickup.
      await tester.tap(find.byKey(const Key('ack_picked_up')));
      await tester.pump();
      await tester.pump();
      expect(find.byKey(const Key('ack_picked_up_note')), findsOneWidget);

      // Kill + reopen: arrival AND ack restored, code re-fetched.
      await _close(tester);
      await tester.pumpWidget(_host(api));
      await tester.pump();
      await tester.pump();
      expect(find.text('You\'re here — head to the counter.'), findsOneWidget);
      expect(find.byKey(const Key('ack_picked_up_note')), findsOneWidget);
      expect(find.text('482913'), findsOneWidget);

      await _close(tester);
    });
  });
}
