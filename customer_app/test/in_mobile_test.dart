// TASK 2 — the shared Indian-mobile rule, and login's use of it.
import 'package:flutter_test/flutter_test.dart';

import 'package:customer_app/screens/login_screen.dart' show normalisePhone;
import 'package:customer_app/utils/in_mobile.dart';

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

  group('login normalisePhone applies the shared rule', () {
    test('still accepts every good spelling', () {
      for (final raw in good) {
        expect(normalisePhone(raw), '+919499956612', reason: raw);
      }
    });

    test('rejects numbers outside the 6-9 mobile space', () {
      expect(normalisePhone('0000000000'), isNull);
      expect(normalisePhone('5499956612'), isNull);
    });

    test('keeps the stricter truncated-+91 refusal', () {
      // "+9198765432" declares 91 as a country code, leaving 8 digits —
      // a truncated number, not the 10-digit 9198765432 it resembles.
      expect(normalisePhone('+9198765432'), isNull);
    });
  });
}
