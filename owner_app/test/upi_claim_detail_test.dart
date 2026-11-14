// TASK 3 sub-point 5 (owner side) — the card shows what the restaurant needs
// to find the money in its own UPI app.
//
// Two things, and both come from fields the backend ALREADY returns:
//   * the ORDER REFERENCE, in the same spelling the customer was shown. The
//     customer's screen gets it from the server as
//     short_order_number(order.id) = the last six hex characters UPPER-CASED
//     (service.py:2309), and it travels in the UPI note, so the owner reading
//     a bank statement is matching against that exact string. The card used
//     to render its own lower-case `shortId`, which is the same characters in
//     a different case — close enough to look right and wrong enough to make
//     someone doubt a match.
//   * WHEN the customer said they paid (payment_claimed_at), so "they claimed
//     this an hour ago and nothing has arrived" is answerable.
//
// The UPI REFERENCE NUMBER the customer typed IS now here too, as of backend
// migration 042 (customer_orders.upi_reference_number). It was previously
// BLOCKED_NEEDS_MIGRATION — there was no column to carry it, and it was left
// out rather than faked. It is the bank's own identifier for the transfer, so
// it is the one string the owner can SEARCH for; the two tests at the bottom
// pin both the present and the absent case, because every order placed before
// 042 and every claim from an older customer_app build has none.
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

const _orderId = 'aaaaaaaa-bbbb-cccc-dddd-ee12ab34cd56';

Order _order(Map<String, dynamic> extra) => Order.fromJson({
      'order_id': _orderId,
      'status': 'PREPARING',
      'payment_status': 'PENDING',
      'payment_mode': 'UPI_MANUAL',
      'is_locked': false,
      'total_amount': 240,
      'created_at': '2026-10-28T10:00:00Z',
      'items': const [
        {'id': 'i1', 'name': 'Masala Dosa', 'quantity': 2}
      ],
      ...extra,
    });

Future<void> _openCard(WidgetTester tester, Order order) async {
  SharedPreferences.setMockInitialValues(
      {'gusto_owner_access_token': 'staff'});
  final api = ApiClient(
      httpClient: MockClient((_) async => http.Response(
          jsonEncode(const {}), 200,
          headers: {'content-type': 'application/json'})));
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
          body: SingleChildScrollView(child: OrderCard(order: order))),
    ),
  ));
  await tester.pump();
  await tester.tap(find.text('#${order.shortId}'));
  await tester.pumpAndSettle();
}

void main() {
  test('the order reference is the customer-visible upper-case form', () {
    // Last six hex characters, upper-cased — what short_order_number()
    // produces server-side and what the customer pasted into their UPI app.
    expect(_order(const {}).orderReference, '34CD56');
  });

  testWidgets('a claimed direct-UPI order shows the reference and when it '
      'was claimed', (tester) async {
    await _openCard(
        tester,
        _order({
          'payment_claimed_at': '2026-10-28T10:05:00Z',
          'acceptance_state': 'AWAITING',
        }));

    expect(find.byKey(const Key('upi_claim_reference')), findsOneWidget);
    expect(find.textContaining('34CD56'), findsWidgets,
        reason: 'the owner matches the bank statement against this');
    expect(find.byKey(const Key('upi_claim_time')), findsOneWidget);
  });

  testWidgets('an unclaimed UPI order shows no claim block', (tester) async {
    await _openCard(tester, _order(const {'acceptance_state': 'AWAITING'}));
    expect(find.byKey(const Key('upi_claim_time')), findsNothing);
  });

  // ============== the 12-digit UPI reference (migration 042) ==============

  test('the reference is parsed off the wire', () {
    expect(
        _order(const {'upi_reference_number': '123456789012'})
            .upiReferenceNumber,
        '123456789012');
  });

  test('an order without one carries null, not an empty string', () {
    // Both shapes a real payload produces: the key absent (a backend older
    // than 042) and the key present-but-null (a claim that carried none).
    expect(_order(const {}).upiReferenceNumber, isNull);
    expect(_order(const {'upi_reference_number': null}).upiReferenceNumber,
        isNull);
  });

  testWidgets('a claim with a reference shows it, labelled "UPI ref"',
      (tester) async {
    await _openCard(
        tester,
        _order({
          'payment_claimed_at': '2026-10-28T10:05:00Z',
          'upi_reference_number': '123456789012',
          'acceptance_state': 'AWAITING',
        }));

    expect(find.byKey(const Key('upi_reference_number')), findsOneWidget);
    expect(find.text('UPI ref 123456789012'), findsOneWidget);
    // Alongside the order reference and the claim age, not instead of them —
    // the owner uses all three for different questions.
    expect(find.byKey(const Key('upi_claim_reference')), findsOneWidget);
    expect(find.byKey(const Key('upi_claim_time')), findsOneWidget);
  });

  testWidgets('an OLD claim with no reference shows nothing at all',
      (tester) async {
    // The compatibility case, and the reason the widget is behind a null
    // check rather than rendering "UPI ref " with nothing after it: every
    // order placed before 042, and every claim from a customer_app build
    // older than 1.0.2+9, looks exactly like this.
    await _openCard(
        tester,
        _order({
          'payment_claimed_at': '2026-10-28T10:05:00Z',
          'acceptance_state': 'AWAITING',
        }));

    expect(find.byKey(const Key('upi_reference_number')), findsNothing);
    expect(find.textContaining('UPI ref'), findsNothing);
    // And the rest of the claim block is untouched.
    expect(find.byKey(const Key('upi_claim_reference')), findsOneWidget);
    expect(find.byKey(const Key('upi_claim_time')), findsOneWidget);
  });

  testWidgets('an empty-string reference is treated as absent',
      (tester) async {
    await _openCard(
        tester,
        _order({
          'payment_claimed_at': '2026-10-28T10:05:00Z',
          'upi_reference_number': '',
          'acceptance_state': 'AWAITING',
        }));
    expect(find.byKey(const Key('upi_reference_number')), findsNothing);
  });
}
