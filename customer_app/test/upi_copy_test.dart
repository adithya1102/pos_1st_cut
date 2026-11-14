// TASK 3 — nothing on the UPI screen has to be typed or selected by hand.
//
// The customer is mid-payment with their bank app open; every value the
// restaurant matches the payment against (the UPI ID, the exact amount, and
// the order reference) gets its own one-tap copy button and says "Copied".
//
// The order reference also travels in the intent's `tn=` field, which is what
// the restaurant reads in its own UPI app — asserted here so the on-screen
// reference and the one in the deep link can never drift apart.
import 'dart:convert';

import 'package:flutter/material.dart';
import 'package:flutter/services.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:http/http.dart' as http;
import 'package:http/testing.dart';
import 'package:provider/provider.dart';
import 'package:shared_preferences/shared_preferences.dart';

import 'package:customer_app/models/order.dart';
import 'package:customer_app/screens/upi_pay_screen.dart';
import 'package:customer_app/services/api_client.dart';
import 'package:customer_app/services/order_service.dart';
import 'package:customer_app/state/cart_state.dart';
import 'package:customer_app/theme/app_theme.dart';

/// Captures what the app puts on the clipboard, with no platform behind it.
late List<String> copied;

void _interceptClipboard(WidgetTester tester) {
  tester.binding.defaultBinaryMessenger.setMockMethodCallHandler(
    SystemChannels.platform,
    (call) async {
      if (call.method == 'Clipboard.setData') {
        copied.add((call.arguments as Map)['text'] as String);
      }
      return null;
    },
  );
  addTearDown(() => tester.binding.defaultBinaryMessenger
      .setMockMethodCallHandler(SystemChannels.platform, null));
}

CreatedOrder _order() => CreatedOrder.fromJson({
      'id': 'aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee',
      'status': 'CREATED',
      'payment_status': 'PENDING',
      'payment_mode': 'UPI_MANUAL',
      'total_amount': 240,
      'final_amount': 240,
      'upi_payment': {
        'vpa': 'kitchen@okaxis',
        'payee_name': 'Test Kitchen',
        'amount': 240.0,
        'note': 'EEEEEE',
      },
    });

Widget _host(CreatedOrder order) {
  SharedPreferences.setMockInitialValues({});
  final api = ApiClient(
      client: MockClient((_) async => http.Response(jsonEncode(const {}), 200,
          headers: {'content-type': 'application/json'})));
  return MultiProvider(
    providers: [
      Provider<ApiClient>.value(value: api),
      Provider<OrderService>(create: (_) => OrderService(api)),
      ChangeNotifierProvider<CartState>(create: (_) => CartState()),
    ],
    child: MaterialApp(
      theme: AppTheme.light(),
      home: UpiPayScreen(order: order, outletName: 'Test Kitchen'),
    ),
  );
}

void main() {
  setUp(() => copied = []);

  testWidgets('the UPI ID copies with one tap and says so', (tester) async {
    _interceptClipboard(tester);
    await tester.pumpWidget(_host(_order()));
    await tester.pumpAndSettle();

    await tester.tap(find.byKey(const Key('upi_copy_vpa')));
    await tester.pumpAndSettle();

    expect(copied, ['kitchen@okaxis']);
    expect(find.text('UPI ID copied'), findsOneWidget);
  });

  testWidgets('the amount copies as the exact payable figure',
      (tester) async {
    _interceptClipboard(tester);
    await tester.pumpWidget(_host(_order()));
    await tester.pumpAndSettle();

    expect(find.byKey(const Key('upi_copy_amount')), findsOneWidget);
    await tester.tap(find.byKey(const Key('upi_copy_amount')));
    await tester.pumpAndSettle();

    // Two decimals and no symbol: what a bank app accepts pasted in, and the
    // same string the intent carries in `am=`.
    expect(copied, ['240.00']);
    expect(find.text('Amount copied'), findsOneWidget);
  });

  testWidgets('the order reference copies with its own button',
      (tester) async {
    _interceptClipboard(tester);
    await tester.pumpWidget(_host(_order()));
    await tester.pumpAndSettle();

    expect(find.byKey(const Key('upi_copy_note')), findsOneWidget);
    await tester.tap(find.byKey(const Key('upi_copy_note')));
    await tester.pumpAndSettle();

    expect(copied, ['EEEEEE']);
    expect(find.text('Reference copied'), findsOneWidget);
  });

  testWidgets('the reference shown is the one in the UPI deep link',
      (tester) async {
    await tester.pumpWidget(_host(_order()));
    await tester.pumpAndSettle();

    final info = _order().upiPayment!;
    expect(info.intentUri.queryParameters['tn'], 'EEEEEE',
        reason: 'the restaurant matches the payment on this');
    expect(info.intentUri.queryParameters['am'], '240.00');
    expect(find.text('EEEEEE'), findsWidgets,
        reason: 'and the customer can see the same string');
  });
}
