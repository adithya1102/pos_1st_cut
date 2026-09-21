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
      //
      // '7', not '19': the wheel parked at index 19 now DRAWS a 12-hour face,
      // so the cell reads 7. Scoped to the hour wheel because a bare find for
      // a single digit would also reach the minute column.
      final digits = tester
          .widgetList<Text>(find.descendant(
            of: find.byKey(const Key('arrival_hour_wheel')),
            matching: find.text('7'),
          ))
          .toList();
      expect(digits, isNotEmpty);
      expect(digits.first.style?.fontWeight, FontWeight.w300);
    });
  });

  // ==========================================================================
  // The hour wheel's 12-hour face
  // ==========================================================================
  //
  // The wheel used to draw "00".."23" and now draws a real clock face:
  // 12, 1 … 11, then 12, 1 … 11 again. ONLY THE PAINT CHANGED — the wheel is
  // still 24 positions long and position N still means hour N — so every test
  // below pins the drawn digit and the resulting DateTime TOGETHER. Asserting
  // either alone would miss the two ways this can break: renumbering the wheel
  // to 12 positions (the DateTime moves, the digits look right), or drawing a
  // 1→12 ladder instead of 12→11 (the digits look plausible, midnight lands
  // after 11 AM).
  group('the hour wheel wears a 12-hour face', () {
    /// The live controller behind a wheel, reached through the ListWheel the
    /// private _Wheel builds. jumpToItem is how these tests select an hour:
    /// dragging by pixels would encode itemExtent into every assertion.
    FixedExtentScrollController ctrl(WidgetTester tester, String key) =>
        tester
            .widget<ListWheelScrollView>(find.descendant(
              of: find.byKey(Key(key)),
              matching: find.byType(ListWheelScrollView),
            ))
            .controller! as FixedExtentScrollController;

    /// Opens the real sheet, parks both wheels, confirms, and hands back what
    /// the picker resolved to. Going through [ArrivalTimePicker.show] rather
    /// than the bare widget is the point: the DateTime that reaches the caller
    /// is the thing the 12-hour face must not have changed.
    Future<DateTime?> pick(WidgetTester tester,
        {required int hour, required int minute}) async {
      DateTime? picked;
      await tester.pumpWidget(MaterialApp(
        theme: AppTheme.light(),
        home: Scaffold(
          body: Builder(
            builder: (context) => Center(
              child: TextButton(
                onPressed: () async {
                  picked = await ArrivalTimePicker.show(
                    context,
                    initial: DateTime(2026, 9, 18, 9, 0),
                    // A full day of headroom. _resolved rolls a past time
                    // forward by at most one day, so every hour 0-23 lands
                    // inside this ceiling no matter what time the suite runs
                    // at — which keeps the confirm button enabled for all 24.
                    maxAhead: const Duration(hours: 24),
                  );
                },
                child: const Text('open'),
              ),
            ),
          ),
        ),
      ));
      await tester.tap(find.text('open'));
      await tester.pumpAndSettle();

      ctrl(tester, 'arrival_hour_wheel').jumpToItem(hour);
      ctrl(tester, 'arrival_minute_wheel').jumpToItem(minute);
      await tester.pumpAndSettle();

      await tester.tap(find.byKey(const Key('arrival_confirm')));
      await tester.pumpAndSettle();
      return picked;
    }

    /// What the hour column is currently showing in its centred cell, proved
    /// by the day-part line rather than guessed from pixel positions.
    String label(WidgetTester tester) =>
        tester.widget<Text>(find.byKey(const Key('arrival_day_part'))).data!;

    Finder inHourWheel(String text) => find.descendant(
          of: find.byKey(const Key('arrival_hour_wheel')),
          matching: find.text(text),
        );

    testWidgets('11 AM to 12 PM: the face turns over at noon, the hour climbs',
        (tester) async {
      // THE forward boundary. On a 12-hour face the digit goes 11 -> 12, which
      // LOOKS like a step backwards; the DateTime must still step forwards.
      await tester.pumpWidget(MaterialApp(
        theme: AppTheme.light(),
        home: Scaffold(
          body: ArrivalTimePicker(
            initial: DateTime(2026, 9, 18, 11, 30),
            maxAhead: const Duration(hours: 24),
          ),
        ),
      ));
      await tester.pumpAndSettle();

      expect(label(tester), '11:30 AM (Morning)');
      expect(inHourWheel('11'), findsOneWidget);

      ctrl(tester, 'arrival_hour_wheel').jumpToItem(12);
      await tester.pumpAndSettle();

      expect(label(tester), '12:30 PM (Afternoon)',
          reason: 'index 12 is noon, not midnight');
      expect(inHourWheel('12'), findsWidgets);
    });

    testWidgets('11 PM to 12 AM: the same turnover at the end of the day',
        (tester) async {
      await tester.pumpWidget(MaterialApp(
        theme: AppTheme.light(),
        home: Scaffold(
          body: ArrivalTimePicker(
            initial: DateTime(2026, 9, 18, 23, 30),
            maxAhead: const Duration(hours: 24),
          ),
        ),
      ));
      await tester.pumpAndSettle();

      expect(label(tester), '11:30 PM (Night)');
      expect(inHourWheel('11'), findsOneWidget);

      ctrl(tester, 'arrival_hour_wheel').jumpToItem(0);
      await tester.pumpAndSettle();

      expect(label(tester), '12:30 AM (Midnight)',
          reason: 'index 0 is midnight, and it draws 12 — not 00');
      expect(inHourWheel('12'), findsWidgets);
      expect(inHourWheel('00'), findsNothing,
          reason: 'the 24-hour face is gone');
    });

    testWidgets('the DateTime that comes out is still the 24-hour index',
        (tester) async {
      // Both halves of the face, and both twelve-o-clocks, resolved for real.
      expect((await pick(tester, hour: 11, minute: 30))?.hour, 11);
      expect((await pick(tester, hour: 12, minute: 30))?.hour, 12);
      expect((await pick(tester, hour: 23, minute: 30))?.hour, 23,
          reason: 'index 23 must still exist — the wheel is 24 long, not 12');
      expect((await pick(tester, hour: 0, minute: 30))?.hour, 0);
      // The minute column was never touched by this change; pinned so a
      // future edit to the shared _Wheel cannot quietly reformat it too.
      expect((await pick(tester, hour: 14, minute: 5))?.minute, 5);
    });

    testWidgets('every one of the 24 positions keeps its own hour',
        (tester) async {
      // The exhaustive version of the two boundary tests: walks the whole
      // wheel and checks the index->hour identity at each stop. A 1→12 ladder
      // (12 at the END of each pass) fails here at index 0 and index 12.
      await tester.pumpWidget(MaterialApp(
        theme: AppTheme.light(),
        home: Scaffold(
          body: ArrivalTimePicker(
            initial: DateTime(2026, 9, 18, 0, 0),
            maxAhead: const Duration(hours: 24),
          ),
        ),
      ));
      await tester.pumpAndSettle();

      const suffix = [
        '12:00 AM', '1:00 AM', '2:00 AM', '3:00 AM', '4:00 AM', '5:00 AM',
        '6:00 AM', '7:00 AM', '8:00 AM', '9:00 AM', '10:00 AM', '11:00 AM',
        '12:00 PM', '1:00 PM', '2:00 PM', '3:00 PM', '4:00 PM', '5:00 PM',
        '6:00 PM', '7:00 PM', '8:00 PM', '9:00 PM', '10:00 PM', '11:00 PM',
      ];

      for (var i = 0; i < 24; i++) {
        ctrl(tester, 'arrival_hour_wheel').jumpToItem(i);
        await tester.pumpAndSettle();
        expect(label(tester), startsWith(suffix[i]), reason: 'index $i');
        // …and the cell under the selection band draws the 12-hour digit.
        expect(inHourWheel(suffix[i].split(':').first), findsWidgets,
            reason: 'index $i draws ${suffix[i].split(':').first}');
      }
    });

    testWidgets('the PM half never draws a 13-23 digit', (tester) async {
      // The regression a face change is most likely to leave half-done.
      await tester.pumpWidget(MaterialApp(
        theme: AppTheme.light(),
        home: Scaffold(
          body: ArrivalTimePicker(
            initial: DateTime(2026, 9, 18, 19, 30),
            maxAhead: const Duration(hours: 24),
          ),
        ),
      ));
      await tester.pumpAndSettle();

      for (final h in ['13', '15', '17', '19', '20', '21', '23']) {
        expect(inHourWheel(h), findsNothing, reason: 'the wheel drew $h');
      }
      expect(inHourWheel('7'), findsOneWidget,
          reason: '19:00 reads as 7 on a clock');
    });
  });
}
