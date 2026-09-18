// The arrival/pickup time picker: day-part banding and the mandatory rule.
//
// The bands are now CONFIRMED, not assumed, and they replaced an earlier guess
// (Morning 05-11, Afternoon 12-16, Evening 17-20, Night 21-04, no Midnight at
// all). Pinned hour by hour so a future change is a deliberate edit with a
// visible diff rather than a silent drift:
//
//   Midnight   00:00-04:59
//   Morning    05:00-11:59
//   Afternoon  12:00-15:59
//   Evening    16:00-18:59
//   Night      19:00-23:59
import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';

import 'package:customer_app/theme/app_theme.dart';
import 'package:customer_app/widgets/arrival_time_picker.dart';

void main() {
  group('day-part banding', () {
    test('every hour of the day lands in exactly one band', () {
      for (var h = 0; h < 24; h++) {
        expect(DayPart.forHour(h), isNotNull);
      }
    });

    test('Midnight is 00:00-04:59', () {
      for (var h = 0; h <= 4; h++) {
        expect(DayPart.forHour(h), DayPart.midnight, reason: 'hour $h');
      }
    });

    test('Morning is 05:00-11:59', () {
      for (var h = 5; h <= 11; h++) {
        expect(DayPart.forHour(h), DayPart.morning, reason: 'hour $h');
      }
    });

    test('Afternoon is 12:00-15:59', () {
      for (var h = 12; h <= 15; h++) {
        expect(DayPart.forHour(h), DayPart.afternoon, reason: 'hour $h');
      }
    });

    test('Evening is 16:00-18:59', () {
      for (var h = 16; h <= 18; h++) {
        expect(DayPart.forHour(h), DayPart.evening, reason: 'hour $h');
      }
    });

    test('Night is 19:00-23:59 and no longer wraps midnight', () {
      for (var h = 19; h <= 23; h++) {
        expect(DayPart.forHour(h), DayPart.night, reason: 'hour $h');
      }
      // The small hours belong to Midnight now. This is the assertion that
      // would have caught the old banding silently surviving the change.
      for (final h in [0, 1, 2, 3, 4]) {
        expect(DayPart.forHour(h), isNot(DayPart.night), reason: 'hour $h');
      }
    });

    test('every boundary flips on the exact hour, not one either side', () {
      // Stated as adjacent pairs so a failure names which cutoff moved.
      expect(DayPart.forHour(4), DayPart.midnight);   // 04:59 -> Midnight
      expect(DayPart.forHour(5), DayPart.morning);    // 05:00 -> Morning
      expect(DayPart.forHour(11), DayPart.morning);   // 11:59 -> Morning
      expect(DayPart.forHour(12), DayPart.afternoon); // 12:00 -> Afternoon
      expect(DayPart.forHour(15), DayPart.afternoon); // 15:59 -> Afternoon
      expect(DayPart.forHour(16), DayPart.evening);   // 16:00 -> Evening
      expect(DayPart.forHour(18), DayPart.evening);   // 18:59 -> Evening
      expect(DayPart.forHour(19), DayPart.night);     // 19:00 -> Night
      expect(DayPart.forHour(23), DayPart.night);     // 23:59 -> Night
    });

    test('the two twelve-o-clocks are the whole point', () {
      // 12:00 AM and 12:00 PM are one character apart on a 12-hour clock and
      // mean opposite ends of the day. Disambiguating THESE is why the band is
      // printed in parentheses at all.
      expect(DayPart.forHour(0).label, 'Midnight');  // 12:00 AM
      expect(DayPart.forHour(12).label, 'Afternoon'); // 12:00 PM
      expect(DayPart.forHour(0), isNot(DayPart.forHour(12)));
    });

    test('hours outside 0-23 wrap rather than throwing', () {
      // Callers pass DateTime.hour, but an arithmetic slip upstream should
      // degrade to a sensible band, not crash the sheet.
      expect(DayPart.forHour(24), DayPart.midnight); // 00:00
      expect(DayPart.forHour(30), DayPart.morning); // 06:00
    });

    test('labels are the five bands the product asked for, in day order', () {
      expect(
        DayPart.values.map((p) => p.label).toList(),
        ['Midnight', 'Morning', 'Afternoon', 'Evening', 'Night'],
      );
    });
  });

  group('the AM/PM + band label format', () {
    // formatWithDayPart needs a BuildContext for locale-aware AM/PM, so these
    // render a throwaway widget rather than calling it bare.
    Future<String> render(WidgetTester tester, TimeOfDay t) async {
      late String out;
      await tester.pumpWidget(MaterialApp(
        home: Builder(builder: (context) {
          out = formatWithDayPart(context, t);
          return const SizedBox();
        }),
      ));
      return out;
    }

    testWidgets('keeps AM/PM and appends the band in parentheses',
        (tester) async {
      expect(await render(tester, const TimeOfDay(hour: 14, minute: 0)),
          '2:00 PM (Afternoon)');
    });

    testWidgets('midnight reads as 12:00 AM (Midnight)', (tester) async {
      expect(await render(tester, const TimeOfDay(hour: 0, minute: 0)),
          '12:00 AM (Midnight)');
    });

    testWidgets('noon reads as 12:00 PM (Afternoon)', (tester) async {
      expect(await render(tester, const TimeOfDay(hour: 12, minute: 0)),
          '12:00 PM (Afternoon)');
    });

    testWidgets('each boundary hour carries its own band', (tester) async {
      expect(await render(tester, const TimeOfDay(hour: 4, minute: 59)),
          '4:59 AM (Midnight)');
      expect(await render(tester, const TimeOfDay(hour: 5, minute: 0)),
          '5:00 AM (Morning)');
      expect(await render(tester, const TimeOfDay(hour: 11, minute: 59)),
          '11:59 AM (Morning)');
      expect(await render(tester, const TimeOfDay(hour: 15, minute: 59)),
          '3:59 PM (Afternoon)');
      expect(await render(tester, const TimeOfDay(hour: 16, minute: 0)),
          '4:00 PM (Evening)');
      expect(await render(tester, const TimeOfDay(hour: 18, minute: 59)),
          '6:59 PM (Evening)');
      expect(await render(tester, const TimeOfDay(hour: 19, minute: 0)),
          '7:00 PM (Night)');
    });

    testWidgets('the DateTime convenience agrees with the TimeOfDay form',
        (tester) async {
      late String a, b;
      await tester.pumpWidget(MaterialApp(
        home: Builder(builder: (context) {
          a = formatDateTimeWithDayPart(context, DateTime(2026, 9, 18, 14, 0));
          b = formatWithDayPart(context, const TimeOfDay(hour: 14, minute: 0));
          return const SizedBox();
        }),
      ));
      expect(a, b);
    });
  });

  group('the picker sheet', () {
    Widget host(DateTime initial) => MaterialApp(
          theme: AppTheme.light(),
          home: Scaffold(
            body: ArrivalTimePicker(
              initial: initial,
              maxAhead: const Duration(hours: 12),
            ),
          ),
        );

    testWidgets('is scrollable wheels, NOT the clock dial', (tester) async {
      await tester.pumpWidget(host(DateTime(2026, 8, 12, 19, 30)));
      await tester.pump();

      expect(find.byKey(const Key('arrival_hour_wheel')), findsOneWidget);
      expect(find.byKey(const Key('arrival_minute_wheel')), findsOneWidget);
      // showTimePicker's dial would bring these; their absence is the point.
      expect(find.byType(ListWheelScrollView), findsNWidgets(2));
    });

    testWidgets('shows the band for the initial hour', (tester) async {
      await tester.pumpWidget(host(DateTime(2026, 8, 12, 19, 30)));
      await tester.pump();

      final label = tester.widget<Text>(
        find.byKey(const Key('arrival_day_part')),
      );
      // The line now echoes the SELECTION, not just its band: the wheels are
      // 24-hour (19) and this is where that is read back in the 12-hour form
      // the customer recognises. 19:30 is Night under the confirmed bands.
      expect(label.data, '7:30 PM (Night)');
    });

    testWidgets('the band label updates as the hour wheel scrolls',
        (tester) async {
      await tester.pumpWidget(host(DateTime(2026, 8, 12, 19, 30)));
      await tester.pump();

      expect(
        tester.widget<Text>(find.byKey(const Key('arrival_day_part'))).data,
        '7:30 PM (Night)',
      );

      // Scroll the hour wheel back from 19 to 09 — Night becomes Morning.
      await tester.drag(
        find.byKey(const Key('arrival_hour_wheel')),
        const Offset(0, 460),
      );
      await tester.pumpAndSettle();

      final after =
          tester.widget<Text>(find.byKey(const Key('arrival_day_part'))).data;
      expect(after, isNot('7:30 PM (Night)'),
          reason: 'the label must track the wheel, not the initial value');
    });

    testWidgets('picker text is lighter than the app default weight',
        (tester) async {
      await tester.pumpWidget(host(DateTime(2026, 8, 12, 19, 30)));
      await tester.pump();

      // "Thinner, not smaller" — the wheel digits carry w300 against the
      // app's usual w700.
      final digits = tester.widgetList<Text>(find.text('19')).toList();
      expect(digits, isNotEmpty);
      expect(digits.first.style?.fontWeight, FontWeight.w300);
    });
  });
}
