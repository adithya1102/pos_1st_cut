// The train-mode arrival picker: day-part banding and the mandatory rule.
//
// The band ranges here are ASSUMED defaults, not confirmed with the product
// owner — Morning 05-11, Afternoon 12-16, Evening 17-20, Night 21-04. They are
// pinned by test so that if they are wrong, changing them is a deliberate edit
// with a visible diff rather than a silent drift.
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

    test('Morning is 05:00-11:59', () {
      for (var h = 5; h <= 11; h++) {
        expect(DayPart.forHour(h), DayPart.morning, reason: 'hour $h');
      }
    });

    test('Afternoon is 12:00-16:59', () {
      for (var h = 12; h <= 16; h++) {
        expect(DayPart.forHour(h), DayPart.afternoon, reason: 'hour $h');
      }
    });

    test('Evening is 17:00-20:59', () {
      for (var h = 17; h <= 20; h++) {
        expect(DayPart.forHour(h), DayPart.evening, reason: 'hour $h');
      }
    });

    test('Night wraps midnight: 21:00-23:59 AND 00:00-04:59', () {
      // The wrap is the only band that spans the day boundary, and the only
      // one a naive range table gets wrong.
      for (final h in [21, 22, 23, 0, 1, 2, 3, 4]) {
        expect(DayPart.forHour(h), DayPart.night, reason: 'hour $h');
      }
    });

    test('boundaries flip on the exact hour, not one either side', () {
      expect(DayPart.forHour(4), DayPart.night);
      expect(DayPart.forHour(5), DayPart.morning);
      expect(DayPart.forHour(11), DayPart.morning);
      expect(DayPart.forHour(12), DayPart.afternoon);
      expect(DayPart.forHour(16), DayPart.afternoon);
      expect(DayPart.forHour(17), DayPart.evening);
      expect(DayPart.forHour(20), DayPart.evening);
      expect(DayPart.forHour(21), DayPart.night);
    });

    test('hours outside 0-23 wrap rather than throwing', () {
      // Callers pass DateTime.hour, but an arithmetic slip upstream should
      // degrade to a sensible band, not crash the sheet.
      expect(DayPart.forHour(24), DayPart.night); // 00:00
      expect(DayPart.forHour(30), DayPart.morning); // 06:00
    });

    test('labels are the four the design asks for', () {
      expect(
        DayPart.values.map((p) => p.label).toList(),
        ['Morning', 'Afternoon', 'Evening', 'Night'],
      );
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
      expect(label.data, 'Evening');
    });

    testWidgets('the band label updates as the hour wheel scrolls',
        (tester) async {
      await tester.pumpWidget(host(DateTime(2026, 8, 12, 19, 30)));
      await tester.pump();

      expect(
        tester.widget<Text>(find.byKey(const Key('arrival_day_part'))).data,
        'Evening',
      );

      // Scroll the hour wheel back from 19 to 09 — Evening becomes Morning.
      await tester.drag(
        find.byKey(const Key('arrival_hour_wheel')),
        const Offset(0, 460),
      );
      await tester.pumpAndSettle();

      final after =
          tester.widget<Text>(find.byKey(const Key('arrival_day_part'))).data;
      expect(after, isNot('Evening'),
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
