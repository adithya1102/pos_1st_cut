// TASK 2 — the shared Indian-mobile rule, and its use at the dial site.
import 'package:flutter_test/flutter_test.dart';

import 'package:owner_app/models/order.dart';
import 'package:owner_app/utils/in_mobile.dart';

Order _order(String? contactPhone) => Order.fromJson({
      'order_id': 'aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee',
      'status': 'READY',
      'payment_status': 'PENDING',
      'is_locked': false,
      'total_amount': 100,
      'created_at': '2026-10-28T10:00:00Z',
      'items': const [
        {'id': 'i1', 'name': 'Dosa', 'quantity': 1}
      ],
      if (contactPhone != null) 'contact_phone': contactPhone,
    });

void main() {
  const good = [
    '919499956612',
    '+919499956612',
    '09499956612',
    '9499956612',
    '94999 56612',
    '+91-94999-56612',
  ];
  const bad = ['12345', '', '0000000000', '5499956612'];

  test('every good spelling gives the same ten digits', () {
    for (final raw in good) {
      expect(normalizeInMobile(raw), '9499956612', reason: raw);
    }
  });

  test('bad inputs are rejected', () {
    for (final raw in bad) {
      expect(normalizeInMobile(raw), isNull, reason: raw);
    }
  });

  test('canonical form is +91 plus the ten digits', () {
    expect(canonicalInMobile('09499956612'), '+919499956612');
  });

  group('telUri dials the normalized +91 number', () {
    test('a legacy bare ten-digit contact is dialed as +91', () {
      expect(_order('9499956612').telUri, Uri.parse('tel:+919499956612'));
    });

    test('a canonical contact stays as it is', () {
      expect(_order('+919499956612').telUri, Uri.parse('tel:+919499956612'));
    });

    test('an unreadable value keeps the old strip-and-dial behaviour', () {
      expect(_order('12 34').telUri, Uri.parse('tel:1234'));
    });

    test('no contact, no URI', () {
      expect(_order(null).telUri, isNull);
    });
  });
}
