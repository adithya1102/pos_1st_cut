// Smoke tests for CareVo Skip pure logic (no network / plugin dependencies).

import 'package:flutter_test/flutter_test.dart';

import 'package:customer_app/models/menu.dart';
import 'package:customer_app/models/order.dart';
import 'package:customer_app/services/payment_service.dart';

void main() {
  test('OrderStatus maps backend status to the correct stepper index', () {
    OrderStatus make(String s) => OrderStatus.fromJson({
          'id': '1',
          'status': s,
          'payment_status': 'PAID',
          'total_amount': 100,
          'items': const [],
        });

    expect(make('CREATED').stepIndex, 0);
    expect(make('PAID').stepIndex, 0);
    expect(make('PREPARING').stepIndex, 1);
    expect(make('READY').stepIndex, 2);
    expect(make('COMPLETED').stepIndex, 2);
  });

  test('CustomizationGroup tolerates a flat list of strings', () {
    final groups = CustomizationGroup.listFrom(['Small', 'Large']);
    expect(groups.length, 1);
    expect(groups.first.options.length, 2);
    expect(groups.first.multiSelect, isFalse);
  });

  test('CustomizationGroup parses structured option groups', () {
    final groups = CustomizationGroup.listFrom([
      {
        'name': 'Size',
        'required': true,
        'type': 'single',
        'options': [
          {'name': 'Regular', 'price_delta': 0},
          {'name': 'Large', 'price_delta': 40},
        ],
      },
    ]);
    expect(groups.single.name, 'Size');
    expect(groups.single.required, isTrue);
    expect(groups.single.options[1].priceDelta, 40);
  });

  test('PaymentMethod wire values match the API contract', () {
    expect(PaymentMethod.upi.wire, 'upi');
    expect(PaymentMethod.card.wire, 'card');
    expect(PaymentMethod.netbanking.wire, 'netbanking');
  });
}
