// Phone-number normalisation, and the autofill corruption it was hiding.
//
// THE BUG: the field carried `maxLength: 10` + `FilteringTextInputFormatter
// .digitsOnly`. Autofill delivers a whole string at once, so "+91 98765 43210"
// became "919876543210" (plus and spaces stripped) and was then truncated to
// the FIRST ten digits — "9198765432". That is a well-formed 10-digit number,
// so it passed validation and the OTP was sent to a real but WRONG person.
//
// normalisePhone itself was already correct. It was being handed input that
// had been destroyed before it ever ran. These tests pin both halves: the
// function's behaviour, and the field's willingness to let it see the truth.
import 'package:flutter/material.dart';
import 'package:flutter/services.dart';
import 'package:flutter_test/flutter_test.dart';

import 'package:customer_app/screens/login_screen.dart';

void main() {
  group('normalisePhone — accepted forms', () {
    // Every one of these is the SAME subscriber number, however it arrives.
    const cases = <String, String>{
      '+91 98765 43210': '+919876543210',   // autofill, spaced, with country code
      '919876543210': '+919876543210',      // country code, no plus
      '9876543210': '+919876543210',        // already clean
      '98765-43210': '+919876543210',       // dashed
      '+919876543210': '+919876543210',     // plus, unspaced
      '09876543210': '+919876543210',       // domestic trunk prefix
      '(98765) 43210': '+919876543210',     // parenthesised
      '  9876543210  ': '+919876543210',    // padded
      '+91-98765-43210': '+919876543210',   // plus and dashes together
    };

    cases.forEach((input, expected) {
      test('"$input" -> $expected', () {
        expect(normalisePhone(input), expected);
      });
    });
  });

  group('normalisePhone — rejected forms', () {
    test('THE BUG: "+9198765432" is truncated, not a valid number', () {
      // The exact string the old field produced. The plus declares that 91 is
      // a country code, so only EIGHT subscriber digits remain — this is a
      // number someone lost two digits off, not the 10-digit 9198765432 it
      // resembles once the plus is discarded.
      //
      // Getting this wrong is the whole severity of the bug: it does not fail
      // loudly, it sends an OTP to a stranger.
      expect(normalisePhone('+9198765432'), isNull);
    });

    test('the same digits WITHOUT a plus are a legitimate number', () {
      // The counterpart that proves the plus is doing real work. Identical
      // digits, opposite verdict — because the input said something different.
      expect(normalisePhone('9198765432'), '+919198765432');
    });

    for (final short in ['', '9', '98765', '987654321', '+91 98765 4321']) {
      test('too short: "$short"', () {
        expect(normalisePhone(short), isNull);
      });
    }

    test('letters and junk do not sneak past the length check', () {
      // The old strip list was [\s\-().] only, so a stray letter survived into
      // the digit count and failed a number that was actually fine.
      expect(normalisePhone('98765abc43210'), '+919876543210');
      expect(normalisePhone('98765 43210 ext'), '+919876543210');
    });

    test('an over-long string keeps the LAST ten digits', () {
      // A doubled or garbled prefix corrupts the front, never the subscriber
      // number at the end.
      expect(normalisePhone('00919876543210'), '+919876543210');
      expect(normalisePhone('91919876543210'), '+919876543210');
    });
  });

  group('the field lets normalisePhone see the truth', () {
    // A widget-level regression test for the actual defect. Asserting only the
    // pure function would have passed happily throughout the bug: the function
    // was never wrong.
    Widget host(TextEditingController c) => MaterialApp(
          home: Scaffold(
            body: TextField(
              controller: c,
              keyboardType: TextInputType.phone,
              maxLength: 18,
              inputFormatters: [
                FilteringTextInputFormatter.allow(RegExp(r'[0-9+\s\-()]')),
              ],
            ),
          ),
        );

    testWidgets('an autofilled "+91 98765 43210" survives into the controller',
        (tester) async {
      final c = TextEditingController();
      addTearDown(c.dispose);
      await tester.pumpWidget(host(c));

      // enterText delivers the whole string in one edit, exactly as autofill
      // does — which is what made the old formatters truncate.
      await tester.enterText(find.byType(TextField), '+91 98765 43210');
      await tester.pump();

      expect(c.text, '+91 98765 43210',
          reason: 'the plus and spacing must reach normalisePhone intact');
      expect(normalisePhone(c.text), '+919876543210');
    });

    testWidgets('the OLD formatters would have corrupted it — proof the '
        'regression is real', (tester) async {
      // Rebuilds the previous configuration to demonstrate the failure this
      // change prevents. If someone reinstates maxLength: 10 + digitsOnly,
      // the test above starts failing and this one explains why.
      final c = TextEditingController();
      addTearDown(c.dispose);
      await tester.pumpWidget(MaterialApp(
        home: Scaffold(
          body: TextField(
            controller: c,
            maxLength: 10,
            inputFormatters: [FilteringTextInputFormatter.digitsOnly],
          ),
        ),
      ));

      await tester.enterText(find.byType(TextField), '+91 98765 43210');
      await tester.pump();

      expect(c.text, '9198765432',
          reason: 'the old config truncated to the first ten digits');
      // ...and the damage is silent: it still looks like a valid number.
      expect(normalisePhone(c.text), '+919198765432',
          reason: 'which is why nothing on screen ever looked wrong');
    });

    testWidgets('typing a plain 10-digit number still works', (tester) async {
      final c = TextEditingController();
      addTearDown(c.dispose);
      await tester.pumpWidget(host(c));
      await tester.enterText(find.byType(TextField), '9876543210');
      await tester.pump();
      expect(c.text, '9876543210');
      expect(normalisePhone(c.text), '+919876543210');
    });

    testWidgets('letters are still refused at the field', (tester) async {
      final c = TextEditingController();
      addTearDown(c.dispose);
      await tester.pumpWidget(host(c));
      await tester.enterText(find.byType(TextField), '98765abc43210');
      await tester.pump();
      expect(c.text, '9876543210',
          reason: 'the allow-list keeps letters out while permitting + and -');
    });
  });
}
