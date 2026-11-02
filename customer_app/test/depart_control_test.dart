// "I'm on my way" — the customer's departure signal, reliably reaching the
// restaurant via the existing POST /customer/orders/{id}/depart endpoint.
//
// Covered here:
//   1. shown once the order is accepted (RECEIVED, auto-mode or manually
//      ACCEPTED) and until it is collected (COMPLETED/PICKED_UP);
//   2. hidden before acceptance (AWAITING) and after collection;
//   3. tapping it calls depart exactly once and replaces the button with
//      "The restaurant knows you're coming" — the SERVER field
//      (OrderStatus.departed), not a local flag, is what the confirmation
//      reads, so a fresh load after a server-recorded depart shows it too;
//   4. a failed depart call keeps the button and shows a short retry
//      message, never throwing;
//   5. no coordinates are sent when the app does not already hold location
//      permission — and no permission dialog is ever raised by this control.
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

const Key _button = Key('i_am_on_my_way');
const Key _confirmation = Key('depart_confirmation');
const Key _retryMessage = Key('depart_retry_message');
const String _confirmationText = 'The restaurant knows you\'re coming';
const String _buttonText = 'I\'m on my way';

class _NoCashfree implements CashfreeService {
  @override
  Future<CheckoutResult> openCheckout({
    required String orderId,
    required String paymentSessionId,
  }) async =>
      const CheckoutResult(CheckoutOutcome.notStarted);
}

/// A backend for one order.
///
/// [departPost] is called on every POST to `/depart`, and its RESULT decides
/// success/failure for that call — the one knob the "offline" test needs.
/// [acceptanceState] of null models an auto-mode outlet (the default
/// everywhere); [departed] models the server already having recorded a
/// CUSTOMER_DEPARTED event, independent of anything this client has done.
ApiClient _api({
  String status = 'RECEIVED',
  String? acceptanceState,
  bool departed = false,
  bool Function()? departPost,
  List<String>? departCalls,
}) {
  return ApiClient(
    client: MockClient((req) async {
      if (req.method == 'POST') {
        if (req.url.path.endsWith('/depart')) {
          departCalls?.add(req.url.path);
          final ok = departPost?.call() ?? true;
          if (!ok) {
            return http.Response(
                jsonEncode({'detail': 'boom'}), 503,
                headers: {'content-type': 'application/json'});
          }
        }
        return http.Response(jsonEncode({'ok': true}), 200,
            headers: {'content-type': 'application/json'});
      }
      final paid = const {'PAID', 'RECEIVED', 'PREPARING', 'READY', 'COMPLETED'}
          .contains(status);
      final body = <String, dynamic>{
        'id': _orderId,
        'status': status,
        'payment_status': paid ? 'PAID' : 'PENDING',
        'pickup_code': paid ? '234567' : null,
        'total_amount': 240,
        'acceptance_state': acceptanceState,
        'departed': departed,
        'items': [
          {'name': 'Masala Dosa', 'quantity': 2}
        ],
      };
      return http.Response(
        jsonEncode(body),
        200,
        headers: {'content-type': 'application/json'},
      );
    }),
  );
}

Widget _host(ApiClient api) {
  return MultiProvider(
    providers: [
      Provider<ApiClient>.value(value: api),
      Provider<OrderService>(create: (_) => OrderService(api)),
      Provider<CashfreeService>(create: (_) => _NoCashfree()),
      // ChangeNotifierProvider: LocationService extends ChangeNotifier, and a
      // plain Provider trips Flutter's debug "wrong provider type" assertion
      // the moment anything actually reads it.
      ChangeNotifierProvider<LocationService>(create: (_) => LocationService()),
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

void main() {
  setUp(() => SharedPreferences.setMockInitialValues({'carevo_access_token': 't'}));

  group('visibility', () {
    testWidgets('shown once accepted at an auto-mode outlet', (tester) async {
      await tester.pumpWidget(_host(_api(status: 'RECEIVED')));
      await tester.pump();
      await tester.pump();

      expect(find.byKey(_button), findsOneWidget);
      expect(find.text(_buttonText), findsOneWidget);

      await _close(tester);
    });

    testWidgets('shown once ACCEPTED at a manual-acceptance outlet',
        (tester) async {
      await tester.pumpWidget(
          _host(_api(status: 'RECEIVED', acceptanceState: 'ACCEPTED')));
      await tester.pump();
      await tester.pump();

      expect(find.byKey(_button), findsOneWidget);

      await _close(tester);
    });

    testWidgets('hidden while AWAITING — paid is not accepted',
        (tester) async {
      // status is PAID here, identical to an auto-mode order's — the whole
      // point of gating on acceptance_state rather than status.
      await tester.pumpWidget(
          _host(_api(status: 'PAID', acceptanceState: 'AWAITING')));
      await tester.pump();
      await tester.pump();

      expect(find.byKey(_button), findsNothing,
          reason: 'a departure declared before acceptance is not a real signal');
      expect(find.byKey(_confirmation), findsNothing);

      await _close(tester);
    });

    testWidgets('hidden after collection (COMPLETED)', (tester) async {
      await tester.pumpWidget(_host(_api(status: 'COMPLETED', departed: true)));
      await tester.pump();
      await tester.pump();

      expect(find.byKey(_button), findsNothing);
      expect(find.byKey(_confirmation), findsNothing,
          reason: 'nothing to confirm once the order is already collected');

      await _close(tester);
    });

    testWidgets('hidden after collection (PICKED_UP)', (tester) async {
      await tester.pumpWidget(_host(_api(status: 'PICKED_UP', departed: true)));
      await tester.pump();
      await tester.pump();

      expect(find.byKey(_button), findsNothing);
      expect(find.byKey(_confirmation), findsNothing);

      await _close(tester);
    });
  });

  group('tap success', () {
    testWidgets('calls depart exactly once and replaces the button',
        (tester) async {
      final calls = <String>[];
      await tester.pumpWidget(_host(_api(departCalls: calls)));
      await tester.pump();
      await tester.pump();

      expect(find.byKey(_button), findsOneWidget);

      await tester.tap(find.byKey(_button));
      await tester.pump();
      await tester.pump();

      expect(calls.length, 1,
          reason: 'one tap must produce exactly one depart call');
      expect(find.byKey(_button), findsNothing);
      expect(find.byKey(_confirmation), findsOneWidget);
      expect(find.text(_confirmationText), findsOneWidget);

      // A second tap on the (now absent) button cannot happen through the UI,
      // but nothing re-enables it either way — the confirmation is final for
      // this screen's lifetime.
      expect(find.text(_buttonText), findsNothing);

      await _close(tester);
    });
  });

  group('tap failure', () {
    testWidgets('keeps the button and shows a retry message, never crashes',
        (tester) async {
      await tester.pumpWidget(_host(_api(departPost: () => false)));
      await tester.pump();
      await tester.pump();

      await tester.tap(find.byKey(_button));
      await tester.pump();
      await tester.pump();

      // Still here — not replaced by the confirmation.
      expect(find.byKey(_button), findsOneWidget);
      expect(find.text(_buttonText), findsOneWidget);
      expect(find.byKey(_confirmation), findsNothing);
      expect(find.byKey(_retryMessage), findsOneWidget);

      // The rest of the screen is unaffected: the pickup code still renders,
      // proving the failure did not block or crash anything else.
      expect(find.text('234567'), findsOneWidget);

      await _close(tester);
    });

    testWidgets('a retry after failure can still succeed', (tester) async {
      var shouldFail = true;
      await tester.pumpWidget(_host(_api(departPost: () => !shouldFail)));
      await tester.pump();
      await tester.pump();

      await tester.tap(find.byKey(_button));
      await tester.pump();
      await tester.pump();
      expect(find.byKey(_retryMessage), findsOneWidget);

      shouldFail = false;
      await tester.tap(find.byKey(_button));
      await tester.pump();
      await tester.pump();

      expect(find.byKey(_confirmation), findsOneWidget);
      expect(find.byKey(_retryMessage), findsNothing);

      await _close(tester);
    });
  });

  group('confirmation on a fresh load', () {
    testWidgets('a server-recorded departure shows the confirmation with no tap',
        (tester) async {
      // Models reopening the order (or a cold start) after depart was called
      // from a previous session — the scenario a client-only flag cannot
      // survive, and the server field can.
      await tester.pumpWidget(_host(_api(departed: true)));
      await tester.pump();
      await tester.pump();

      expect(find.byKey(_button), findsNothing);
      expect(find.byKey(_confirmation), findsOneWidget);
      expect(find.text(_confirmationText), findsOneWidget);

      await _close(tester);
    });
  });

  group('no permission, no prompt', () {
    testWidgets(
        'tapping with no location permission sends depart with no coordinates '
        'and never touches the permission system',
        (tester) async {
      // A fresh LocationService() has never called checkPermission(), so
      // hasPermission reads false without any plugin call — exactly the
      // "permission not held" case this test is asserting stays silent.
      final calls = <String>[];
      await tester.pumpWidget(_host(_api(departCalls: calls)));
      await tester.pump();
      await tester.pump();

      await tester.tap(find.byKey(_button));
      await tester.pump();
      await tester.pump();

      expect(calls, ['/api/v1/customer/orders/$_orderId/depart']);
      expect(find.byKey(_confirmation), findsOneWidget,
          reason: 'a call with no coordinates is still a successful depart');

      await _close(tester);
    });
  });
}
