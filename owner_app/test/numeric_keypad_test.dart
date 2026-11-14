// Digit-only fields get a numeric keypad and refuse non-digits (TASK 1).
//
// Pickup codes are generated server-side from the alphabet "23456789", six
// characters long (backend carevo_customer/service.py _generate_pickup_code),
// so every field that takes one is digits-only with a known length of 6.
//
// The formatter assertions are FUNCTIONAL — they run the field's formatter
// chain over hostile input — rather than identity checks against
// FilteringTextInputFormatter.digitsOnly, so a behaviourally identical
// formatter still passes and a missing one still fails.
import 'dart:convert';

import 'package:flutter/material.dart';
import 'package:flutter/services.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:http/http.dart' as http;
import 'package:http/testing.dart';
import 'package:provider/provider.dart';
import 'package:shared_preferences/shared_preferences.dart';

import 'package:owner_app/models/menu_item.dart';
import 'package:owner_app/models/order.dart';
import 'package:owner_app/screens/dish_edit_screen.dart';
import 'package:owner_app/services/api_client.dart';
import 'package:owner_app/services/menu_service.dart';
import 'package:owner_app/services/order_service.dart';
import 'package:owner_app/services/outlet_service.dart';
import 'package:owner_app/state/home_state.dart';
import 'package:owner_app/state/orders_state.dart';
import 'package:owner_app/widgets/order_card.dart';
import 'package:owner_app/widgets/verify_box.dart';

/// Runs [field]'s formatter chain over [input] as if it were typed in one go.
String _formatted(TextField field, String input) {
  var value = TextEditingValue(text: input);
  for (final f in field.inputFormatters ?? const <TextInputFormatter>[]) {
    value = f.formatEditUpdate(TextEditingValue.empty, value);
  }
  return value.text;
}

/// The [TextField] at [finder] — or, when the key sits on a [TextFormField],
/// the TextField it builds internally.
TextField _field(WidgetTester tester, Finder finder) {
  final w = tester.widget(finder);
  if (w is TextField) return w;
  return tester.widget<TextField>(
      find.descendant(of: finder, matching: find.byType(TextField)));
}

http.Client _emptyBackend() => MockClient((req) async => http.Response(
    jsonEncode(req.url.path.contains('categories') ? [] : {}), 200,
    headers: {'content-type': 'application/json'}));

void main() {
  testWidgets('VerifyBox pickup-code field is numeric, digits-only, max 6',
      (tester) async {
    await tester.pumpWidget(const MaterialApp(
        home: Scaffold(body: VerifyBox(orderId: 'o1'))));

    final finder = find.descendant(
        of: find.byType(VerifyBox), matching: find.byType(TextField));
    expect(finder, findsOneWidget);
    final field = _field(tester, finder);

    expect(field.keyboardType, TextInputType.number,
        reason: 'pickup codes are digits 2-9, so the keypad must be numeric');
    expect(_formatted(field, 'a2B3!4'), '234',
        reason: 'non-digits must be filtered out');
    expect(_formatted(field, '23456789'), '234567',
        reason: 'pickup codes are exactly 6 digits');
  });

  testWidgets('collect dialog pickup-code field is digits-only, max 6',
      (tester) async {
    SharedPreferences.setMockInitialValues(
        {'gusto_owner_access_token': 'staff'});
    final api = ApiClient(httpClient: _emptyBackend());
    final order = Order.fromJson({
      'order_id': 'aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee',
      'status': 'READY',
      'payment_status': 'PENDING',
      'payment_mode': 'PAY_AT_PICKUP',
      'is_locked': false,
      'total_amount': 240,
      'created_at': '2026-10-28T10:00:00Z',
      'items': const [
        {'id': 'i1', 'name': 'Masala Dosa', 'quantity': 2}
      ],
    });

    await tester.pumpWidget(MultiProvider(
      providers: [
        Provider<ApiClient>.value(value: api),
        Provider<OrderService>(create: (_) => OrderService(api)),
        ChangeNotifierProvider<OrdersState>(
            create: (_) => OrdersState(OrderService(api))),
      ],
      child: MaterialApp(
          home: Scaffold(
              body: SingleChildScrollView(child: OrderCard(order: order)))),
    ));
    await tester.pump();
    await tester.tap(find.text('#${order.shortId}'));
    await tester.pumpAndSettle();

    await tester.tap(find.byKey(const Key('order_paid_and_handed_over')));
    await tester.pumpAndSettle();

    final field = _field(tester, find.byKey(const Key('collect_code')));
    expect(field.keyboardType, TextInputType.number);
    expect(_formatted(field, 'x2y3z4!'), '234');
    expect(_formatted(field, '2345678'), '234567');
  });

  testWidgets('dish editor price, prep and stock fields filter their input',
      (tester) async {
    SharedPreferences.setMockInitialValues(
        {'gusto_owner_access_token': 'staff'});
    final api = ApiClient(httpClient: _emptyBackend());
    final home = HomeState(OutletService(api), MenuService(api));
    final item = MenuItem.fromJson({
      'id': 'm1',
      'name': 'Masala Dosa',
      'is_available': true,
      'base_price': 120,
      'prep_time_minutes': 10,
      'stock_remaining': 5,
    });

    await tester.pumpWidget(ChangeNotifierProvider<HomeState>.value(
      value: home,
      child: MaterialApp(home: DishEditScreen(item: item)),
    ));
    await tester.pumpAndSettle();

    final price = _field(tester,
        find.byKey(const Key('dish_price_field')));
    expect(price.keyboardType,
        const TextInputType.numberWithOptions(decimal: true));
    expect(_formatted(price, 'Rs 12.5x'), '12.5',
        reason: 'price keeps digits and the decimal point only');

    final prep = _field(tester, find.byKey(const Key('dish_prep_field')));
    expect(prep.keyboardType, TextInputType.number);
    expect(_formatted(prep, '1a0'), '10',
        reason: 'prep minutes are digits only');

    await tester.ensureVisible(find.byKey(const Key('dish_stock_field')));
    await tester.pumpAndSettle();
    final stock = _field(tester, find.byKey(const Key('dish_stock_field')));
    expect(stock.keyboardType, TextInputType.number);
    expect(_formatted(stock, '-5'), '5',
        reason: 'stock counts are digits only — no sign, no decimals');
  });
}
