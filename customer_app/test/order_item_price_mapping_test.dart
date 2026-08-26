// Order line items must read the keys the backend actually sends.
//
// `OrderItemOut` (carevo_customer/schema.py:232-239) serialises `name_snap`,
// `price_snap` and `quantity`. The parser used to ask for `name`/
// `menu_item_name` and `line_total`/`total` — none of which have ever existed
// in this API — so every line on the pickup screen rendered as "Item ₹0" while
// the order total, read from the correct key, stayed correct. Prod data was
// never at fault: 123 order lines, zero of them priced 0.
//
// The other half of the bug was the fallback chains. A missing key fell
// through to a plausible-looking 0 instead of failing loudly, which is why a
// wrong field name survived to a release. These tests pin the correct keys AND
// pin that the old ones are no longer consulted.
import 'package:flutter_test/flutter_test.dart';

import 'package:customer_app/models/order.dart';

/// One line exactly as the API emits it.
Map<String, dynamic> line({
  String? nameSnap = 'Mysore Masala Dosa',
  num priceSnap = 120,
  int quantity = 1,
}) =>
    {
      'id': '11111111-1111-1111-1111-111111111111',
      'menu_item_id': '22222222-2222-2222-2222-222222222222',
      'name_snap': nameSnap,
      'price_snap': priceSnap,
      'quantity': quantity,
      'customizations': null,
      'item_notes': null,
    };

/// A whole order, shaped like `OrderOut`.
Map<String, dynamic> order({
  List<Map<String, dynamic>>? items,
  num totalAmount = 285,
}) =>
    {
      'id': '33333333-3333-3333-3333-333333333333',
      'status': 'RECEIVED',
      'payment_status': 'PAID',
      'pickup_code': '234567',
      'total_amount': totalAmount,
      'original_amount': totalAmount,
      'discount_amount': 0,
      'final_amount': totalAmount,
      'items': items ?? [line()],
      'created_at': '2026-08-26T19:04:38.189077Z',
      'updated_at': '2026-08-26T19:04:38.189077Z',
    };

void main() {
  group('unit price x quantity', () {
    test('a single unit costs the unit price', () {
      final l = OrderItemLine.fromJson(line(priceSnap: 120, quantity: 1));
      expect(l.unitPrice, 120);
      expect(l.lineTotal, 120);
    });

    test('quantity multiplies — price_snap is per-unit, not a line total', () {
      // The real case that made this visible: Kesari Bath, 3 x ₹60 = ₹180.
      // Reading price_snap as if it were already a line total would show ₹60.
      final l = OrderItemLine.fromJson(line(priceSnap: 60, quantity: 3));
      expect(l.unitPrice, 60);
      expect(l.lineTotal, 180);
    });

    test('holds across a range of quantities', () {
      for (final q in [1, 2, 5, 10, 99]) {
        final l = OrderItemLine.fromJson(line(priceSnap: 45, quantity: q));
        expect(l.lineTotal, 45 * q, reason: 'quantity $q');
      }
    });

    test('decimal unit prices survive the multiply', () {
      final l = OrderItemLine.fromJson(line(priceSnap: 12.50, quantity: 4));
      expect(l.lineTotal, closeTo(50.0, 1e-9));
    });

    test('lineTotal is derived, so it cannot disagree with its inputs', () {
      final l = OrderItemLine(name: 'X', quantity: 7, unitPrice: 11);
      expect(l.lineTotal, 77);
    });

    test('a genuinely free item is still ₹0 — 0 is a price, not a failure', () {
      final l = OrderItemLine.fromJson(line(priceSnap: 0, quantity: 2));
      expect(l.lineTotal, 0);
    });
  });

  group('item names', () {
    test('reads name_snap rather than falling back to "Item"', () {
      final l = OrderItemLine.fromJson(line(nameSnap: 'Mutton Chukka'));
      expect(l.name, 'Mutton Chukka');
      expect(l.name, isNot('Item'));
    });

    test('name_snap is nullable server-side, so null still falls back', () {
      // schema.py:235 is Optional[str]; the column is nullable=True. This
      // fallback covers a real server state, unlike the removed name/
      // menu_item_name chain which covered a spelling that never existed.
      final l = OrderItemLine.fromJson(line(nameSnap: null));
      expect(l.name, 'Item');
    });
  });

  group('the old keys are no longer consulted', () {
    // Without these, the fix would pass just as well if the parser kept
    // reading both the new and old names — and the next wrong key would go
    // silent again.
    test('line_total and total are ignored', () {
      final l = OrderItemLine.fromJson({
        'name_snap': 'Rava Kesari',
        'quantity': 2,
        'price_snap': 45,
        // Deliberately contradictory: if either of these were still read, the
        // line would come out at 999 or 888 rather than 45 x 2.
        'line_total': 999,
        'total': 888,
      });
      expect(l.lineTotal, 90);
    });

    test('name and menu_item_name are ignored', () {
      final l = OrderItemLine.fromJson({
        'name_snap': 'Bengali Cha',
        'name': 'WRONG',
        'menu_item_name': 'ALSO WRONG',
        'quantity': 1,
        'price_snap': 20,
      });
      expect(l.name, 'Bengali Cha');
    });

    test('a payload carrying ONLY the old keys yields no price and no name', () {
      // This is precisely the shape the app used to be built around, and it
      // must now come out empty rather than looking like real data.
      final l = OrderItemLine.fromJson({
        'name': 'Shorshe Ilish',
        'menu_item_name': 'Shorshe Ilish',
        'quantity': 1,
        'line_total': 320,
      });
      expect(l.lineTotal, 0);
      expect(l.name, 'Item');
    });
  });

  group('the order total is untouched by this change', () {
    test('totalAmount still reads total_amount', () {
      final s = OrderStatus.fromJson(order(totalAmount: 285));
      expect(s.totalAmount, 285);
    });

    test('the total is the server figure, NOT a sum of the lines', () {
      // The total is authoritative — it accounts for discounts the lines know
      // nothing about. A fix that started deriving it from line items would
      // silently drop the discount, so this pins that it does not.
      final s = OrderStatus.fromJson({
        ...order(totalAmount: 200),
        'items': [line(priceSnap: 120, quantity: 1), line(priceSnap: 60, quantity: 3)],
        'original_amount': 300,
        'discount_amount': 100,
      });
      expect(s.totalAmount, 200);
      final sumOfLines =
          s.items.fold<double>(0, (sum, i) => sum + i.lineTotal);
      expect(sumOfLines, 300);
      expect(s.totalAmount, isNot(sumOfLines));
    });
  });

  group('a real order end to end', () {
    test('the 2026-08-26 discounted order parses correctly', () {
      // Order 316d3097…cbc7b4, straight from prod: ₹120 x1 + ₹60 x3 = ₹300 of
      // lines against total_amount ₹285, the ₹15 gap being discount_amount.
      //
      // Worth keeping as the headline case precisely because the lines do NOT
      // sum to the total. An earlier draft of this test asserted they did and
      // failed — the arithmetic assumption was wrong, not the parser. Any
      // future "fix" that derives the total from the lines will fail here.
      final s = OrderStatus.fromJson({
        ...order(totalAmount: 285),
        'items': [
          line(nameSnap: 'Mysore Masala Dosa', priceSnap: 120, quantity: 1),
          line(nameSnap: 'Kesari Bath', priceSnap: 60, quantity: 3),
        ],
        'original_amount': 300,
        'discount_amount': 15,
      });

      expect(s.items, hasLength(2));
      expect(s.items[0].name, 'Mysore Masala Dosa');
      expect(s.items[0].lineTotal, 120);
      expect(s.items[1].name, 'Kesari Bath');
      expect(s.items[1].lineTotal, 180);

      final sumOfLines =
          s.items.fold<double>(0, (sum, i) => sum + i.lineTotal);
      expect(sumOfLines, 300);
      expect(s.totalAmount, 285);
      expect(sumOfLines - s.totalAmount, 15);
    });

    test('an undiscounted order has lines that DO sum to the total', () {
      // 94 of 103 prod orders look like this. It is why the ₹0 bug was
      // noticeable at all: the total stayed right while the lines summed to 0.
      final s = OrderStatus.fromJson({
        ...order(totalAmount: 280),
        'items': [line(nameSnap: 'Mutton Chukka', priceSnap: 280, quantity: 1)],
      });

      final sumOfLines =
          s.items.fold<double>(0, (sum, i) => sum + i.lineTotal);
      expect(sumOfLines, 280);
      expect(s.totalAmount, 280);
      expect(sumOfLines, s.totalAmount);
    });
  });
}
