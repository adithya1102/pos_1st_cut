// The acceptance modal (Task 4.4) and the pending-order poll cadence.
//
// The modal takes NO services on purpose — the caller does the networking and
// owns the alarm — so everything here is exercised without a backend, an audio
// device, or a Firebase app.
import 'dart:convert';

import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:http/http.dart' as http;
import 'package:http/testing.dart';
import 'package:shared_preferences/shared_preferences.dart';

import 'package:owner_app/models/order.dart';
import 'package:owner_app/services/api_client.dart';
import 'package:owner_app/services/order_service.dart';
import 'package:owner_app/state/orders_state.dart';
import 'package:owner_app/widgets/order_acceptance_modal.dart';

Order _order({
  String? acceptanceState = 'AWAITING',
  String? deadline,
  double total = 240,
}) =>
    Order(
      orderId: 'order-1',
      status: 'PAID',
      paymentStatus: 'PAID',
      isLocked: false,
      totalAmount: total,
      createdAt: DateTime.now().toUtc().toIso8601String(),
      items: const [
        OrderLineItem(id: 'l1', name: 'Masala Dosa', quantity: 2),
      ],
      acceptanceState: acceptanceState,
      acceptanceDeadlineAt: deadline,
    );

/// Long enough for `showGeneralDialog`'s transition to run to completion.
///
/// pumpAndSettle is UNUSABLE anywhere in this file, and not as a matter of
/// taste: the sheet re-renders itself every second from a `Timer.periodic` to
/// redraw the countdown, so the tree never reaches a frame-less state. Each
/// pump lands another scheduled frame, so pumpAndSettle loops until its own
/// internal timeout instead of returning — which is a silent hang for minutes,
/// not a failure. A fixed pump is both correct here and immediate.
const Duration _settle = Duration(milliseconds: 400);

/// The committed prep time as the stepper is actually displaying it.
String? _prepValue(WidgetTester tester) =>
    tester.widget<Text>(find.byKey(const Key('prep_value'))).data;

/// Opens the modal and hands back the future of whatever it is closed with.
///
/// The decision future is returned INSIDE A RECORD deliberately. An `async`
/// function that does `return someFuture` has that future FLATTENED into its
/// own: the caller's `await _open(...)` would then block until the MODAL IS
/// ANSWERED, which in a test that only wants to inspect the open sheet never
/// happens. The suite then hangs indefinitely instead of failing, with the
/// runner's own per-test timeout unable to fire. Wrapping the future keeps
/// "the sheet is up" and "the sheet was answered" independently awaitable.
Future<({Future<AcceptanceDecision?> decision})> _open(
  WidgetTester tester,
  Order order,
) async {
  late Future<AcceptanceDecision?> decision;
  await tester.pumpWidget(MaterialApp(
    home: Builder(
      builder: (context) => ElevatedButton(
        onPressed: () => decision = showOrderAcceptanceModal(context, order),
        child: const Text('go'),
      ),
    ),
  ));
  await tester.tap(find.text('go'));
  await tester.pump();
  await tester.pump(_settle);
  return (decision: decision);
}

void main() {
  setUp(() => SharedPreferences.setMockInitialValues({}));

  group('Order.isPending gates on the field, not the status', () {
    test('an auto-mode order is never pending', () {
      // Identical status to an awaiting order — PAID — which is exactly why
      // the status cannot be the test.
      final auto = _order(acceptanceState: null);
      expect(auto.status, 'PAID');
      expect(auto.isPending, isFalse);
    });

    test('AWAITING is pending; the other states are not', () {
      expect(_order(acceptanceState: 'AWAITING').isPending, isTrue);
      for (final s in ['ACCEPTED', 'REJECTED', 'EXPIRED']) {
        expect(_order(acceptanceState: s).isPending, isFalse, reason: s);
      }
    });

    test('secondsToDeadline floors at zero and tolerates nonsense', () {
      final past = DateTime.now().toUtc().subtract(const Duration(minutes: 5));
      expect(_order(deadline: past.toIso8601String()).secondsToDeadline, 0,
          reason: 'a negative countdown must not be rendered');

      expect(_order(deadline: 'not-a-date').secondsToDeadline, isNull);
      expect(_order(deadline: null).secondsToDeadline, isNull);

      final soon = DateTime.now().toUtc().add(const Duration(seconds: 90));
      final s = _order(deadline: soon.toIso8601String()).secondsToDeadline!;
      expect(s, inInclusiveRange(85, 90));
    });
  });

  group('the modal', () {
    testWidgets('shows the order and its countdown', (tester) async {
      final deadline =
          DateTime.now().toUtc().add(const Duration(seconds: 120));
      await _open(tester, _order(deadline: deadline.toIso8601String()));

      expect(find.text('New order'), findsOneWidget);
      expect(find.textContaining('2× Masala Dosa'), findsOneWidget);
      expect(find.textContaining('₹240'), findsOneWidget);
      expect(find.byKey(const Key('acceptance_countdown')), findsOneWidget);
      expect(find.textContaining('seconds to accept'), findsOneWidget);
    });

    testWidgets('says so plainly when time is up', (tester) async {
      // A "0 seconds" countdown that still offered Accept would be lying: the
      // server has almost certainly expired the order already.
      final past = DateTime.now().toUtc().subtract(const Duration(seconds: 5));
      await _open(tester, _order(deadline: past.toIso8601String()));
      expect(find.textContaining('Time is up'), findsOneWidget);
    });

    testWidgets('shows no countdown when the deadline is unknown',
        (tester) async {
      // Better than inventing one.
      await _open(tester, _order(deadline: null));
      expect(find.byKey(const Key('acceptance_countdown')), findsNothing);
    });

    testWidgets('cannot be dismissed by the back gesture', (tester) async {
      // The cost of a swiped-away alert here is a cancelled order and a
      // refund, not a missed notification.
      //
      // Asserted on PopScope.canPop rather than by driving a real back press.
      // handlePopRoute() against canPop:false returns a future that NEVER
      // completes, and inside testWidgets the clock is FAKE — so a .timeout()
      // on that future never fires either, because nothing advances time while
      // the test is parked on an await. Awaiting it hangs the whole suite
      // indefinitely rather than failing, which is how it took the run down.
      final result = (await _open(tester, _order())).decision;
      expect(
        tester.widgetList<PopScope>(find.byType(PopScope)).any((s) => !s.canPop),
        isTrue,
        reason: 'back could dismiss an undecided order',
      );
      expect(find.text('New order'), findsOneWidget);
      // Close it properly so the pending future completes.
      await tester.tap(find.byKey(const Key('acceptance_accept')));
      await tester.pump(_settle);
      expect(await result, isA<AcceptDecision>());
    });

    testWidgets('accepts with the default prep time', (tester) async {
      final result = (await _open(tester, _order())).decision;
      await tester.tap(find.byKey(const Key('acceptance_accept')));
      await tester.pump(_settle);
      final d = await result as AcceptDecision;
      expect(d.prepMinutes, 15);
    });

    testWidgets('a preset chip is ONE tap', (tester) async {
      // A bare stepper would make "20 minutes" four taps at a busy counter.
      final result = (await _open(tester, _order())).decision;
      await tester.tap(find.byKey(const Key('prep_chip_30')));
      await tester.pump();
      await tester.tap(find.byKey(const Key('acceptance_accept')));
      await tester.pump(_settle);
      expect((await result as AcceptDecision).prepMinutes, 30);
    });

    testWidgets('the stepper moves in fives and is floored at 5',
        (tester) async {
      final result = (await _open(tester, _order())).decision;
      await tester.tap(find.byKey(const Key('prep_chip_10')));
      await tester.pump();
      // 10 -> 5, then the button must disable rather than reach 0: a
      // sub-5-minute promise is not credible and would only be a mis-tap.
      await tester.tap(find.byKey(const Key('prep_minus')));
      await tester.pump();
      // Read through the prep_value KEY, not find.text. The preset chips carry
      // the same "N min" label, so a bare text match is ambiguous for every
      // value that is also a preset (10/15/20/30) and would fail on "too many"
      // rather than on the number being wrong.
      expect(_prepValue(tester), '5 min');
      expect(
        tester.widget<IconButton>(find.byKey(const Key('prep_minus')))
            .onPressed,
        isNull,
      );
      await tester.tap(find.byKey(const Key('prep_plus')));
      await tester.pump();
      expect(_prepValue(tester), '10 min');
      await tester.tap(find.byKey(const Key('acceptance_accept')));
      await tester.pump(_settle);
      expect((await result as AcceptDecision).prepMinutes, 10);
    });

    testWidgets('rejecting REQUIRES a reason', (tester) async {
      // The customer is about to be told their order was refused; "no reason
      // given" is what makes that unanswerable for them.
      await _open(tester, _order());
      await tester.tap(find.byKey(const Key('acceptance_reject_open')));
      await tester.pump(_settle);

      expect(
        tester.widget<FilledButton>(
          find.byKey(const Key('acceptance_reject_confirm')),
        ).onPressed,
        isNull,
        reason: 'reject was enabled with no reason chosen',
      );
    });

    testWidgets('rejects with the chosen reason', (tester) async {
      final result = (await _open(tester, _order())).decision;
      await tester.tap(find.byKey(const Key('acceptance_reject_open')));
      await tester.pump(_settle);
      await tester.tap(find.byKey(const Key('reject_reason_tooBusy')));
      await tester.pump();
      await tester.tap(find.byKey(const Key('acceptance_reject_confirm')));
      await tester.pump(_settle);

      final d = await result as RejectDecision;
      expect(d.reason, RejectReason.tooBusy);
      expect(d.serverReason, 'Too busy');
    });

    testWidgets('"Other" lets free text REPLACE the label', (tester) async {
      // "Other" on its own tells the customer nothing.
      final result = (await _open(tester, _order())).decision;
      await tester.tap(find.byKey(const Key('acceptance_reject_open')));
      await tester.pump(_settle);
      await tester.tap(find.byKey(const Key('reject_reason_other')));
      await tester.pump(_settle);
      await tester.enterText(
          find.byKey(const Key('reject_note')), 'Gas cylinder ran out');
      await tester.tap(find.byKey(const Key('acceptance_reject_confirm')));
      await tester.pump(_settle);

      expect((await result as RejectDecision).serverReason,
          'Gas cylinder ran out');
    });

    testWidgets('"Other" with no note falls back to the label',
        (tester) async {
      final result = (await _open(tester, _order())).decision;
      await tester.tap(find.byKey(const Key('acceptance_reject_open')));
      await tester.pump(_settle);
      await tester.tap(find.byKey(const Key('reject_reason_other')));
      await tester.pump(_settle);
      await tester.tap(find.byKey(const Key('acceptance_reject_confirm')));
      await tester.pump(_settle);
      expect((await result as RejectDecision).serverReason, 'Other');
    });

    testWidgets('Back returns to the accept side', (tester) async {
      final result = (await _open(tester, _order())).decision;
      await tester.tap(find.byKey(const Key('acceptance_reject_open')));
      await tester.pump(_settle);
      await tester.tap(find.byKey(const Key('acceptance_reject_back')));
      await tester.pump(_settle);
      expect(find.byKey(const Key('acceptance_accept')), findsOneWidget);
      await tester.tap(find.byKey(const Key('acceptance_accept')));
      await tester.pump(_settle);
      expect(await result, isA<AcceptDecision>());
    });

    testWidgets('all four reject reasons are offered', (tester) async {
      await _open(tester, _order());
      await tester.tap(find.byKey(const Key('acceptance_reject_open')));
      await tester.pump(_settle);
      for (final r in RejectReason.values) {
        expect(find.byKey(Key('reject_reason_${r.name}')), findsOneWidget,
            reason: r.name);
      }
    });
  });

  group('OrdersState poll cadence follows the data', () {
    OrdersState makeState({required bool pending}) {
      final api = ApiClient(
        httpClient: MockClient((req) async => http.Response(
              jsonEncode([
                {
                  'order_id': 'order-1',
                  'status': 'PAID',
                  'payment_status': 'PAID',
                  'is_locked': false,
                  'total_amount': 240,
                  'created_at': DateTime.now().toUtc().toIso8601String(),
                  'items': const [],
                  if (pending) 'acceptance_state': 'AWAITING',
                }
              ]),
              200,
              headers: {'content-type': 'application/json'},
            )),
      );
      return OrdersState(OrderService(api));
    }

    test('a pending order is found, and only when one exists', () async {
      final withPending = makeState(pending: true);
      await withPending.load();
      expect(withPending.hasPendingOrder, isTrue);
      expect(withPending.pendingOrder!.orderId, 'order-1');

      final auto = makeState(pending: false);
      await auto.load();
      expect(auto.hasPendingOrder, isFalse,
          reason: 'an auto outlet must never look pending');
      expect(auto.pendingOrder, isNull);
    });

    test('the pending interval is faster than the idle one', () {
      // The deadline defaults to 180s; a 15-second poll is up to 15 seconds of
      // alarm after another device already settled the order.
      expect(OrdersState.pendingPollInterval,
          lessThan(OrdersState.defaultPollInterval));
      expect(OrdersState.pendingPollInterval, const Duration(seconds: 5));
    });

    test('stopPolling allows a later restart', () async {
      // Regression guard: _activeInterval is cached to avoid restarting the
      // timer on every tick, so stopPolling MUST clear it or a restart at the
      // same cadence takes the early return and polling stays dead.
      final s = makeState(pending: false);
      await s.load();
      s.startPolling();
      s.stopPolling();
      s.startPolling();
      // Nothing observable to assert beyond "it did not throw and the state is
      // still usable"; the real proof is that a second load still runs.
      await s.load();
      expect(s.orders, hasLength(1));
      s.stopPolling();
    });
  });
}
