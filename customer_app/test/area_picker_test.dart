import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';

import 'package:customer_app/services/catalog_service.dart';
import 'package:customer_app/theme/app_theme.dart';
import 'package:customer_app/theme/widgets/neo_chip.dart';
import 'package:customer_app/widgets/area_picker.dart';

/// Builds n cities named City1..CityN.
List<AreaOption> _cities(int n) => List.generate(
      n,
      (i) => AreaOption(city: 'City${i + 1}', outletCount: i + 1),
    );

Widget _host(Widget child) => MaterialApp(
      theme: AppTheme.light(),
      home: Scaffold(body: SingleChildScrollView(child: child)),
    );

Widget _picker(List<AreaOption>? areas, {String? selected, String? error}) =>
    _host(AreaPicker(
      areas: areas,
      error: error,
      selected: selected,
      onSelect: (_) {},
      onRetry: () {},
    ));

void main() {
  group('threshold', () {
    test('boundary: 8 stays chips, 9 switches to search', () {
      expect(AreaPicker.searchThreshold, 8);
      expect(AreaPicker.usesSearch(0), isFalse);
      expect(AreaPicker.usesSearch(8), isFalse);
      expect(AreaPicker.usesSearch(9), isTrue);
    });
  });

  group('rendering', () {
    testWidgets('TODAY\'S PROD SHAPE: 2 cities renders chips, no search field',
        (tester) async {
      // This is the case that actually ships tonight — prod has exactly two
      // cities (Bengaluru, Chennai). It must look exactly as it did before the
      // threshold existed: chips, and no search box anywhere.
      await tester.pumpWidget(_picker([
        const AreaOption(city: 'Bengaluru', outletCount: 2),
        const AreaOption(city: 'Chennai', outletCount: 2),
      ]));

      expect(find.byType(NeoChip), findsNWidgets(2));
      expect(find.byType(TextField), findsNothing);
      expect(find.textContaining('Bengaluru'), findsOneWidget);
      expect(find.textContaining('Chennai'), findsOneWidget);
      // Count label comes through on the chip.
      expect(find.textContaining('2 restaurants'), findsNWidgets(2));
    });

    testWidgets('8 cities: still chips only', (tester) async {
      await tester.pumpWidget(_picker(_cities(8)));
      expect(find.byType(NeoChip), findsNWidgets(8));
      expect(find.byType(TextField), findsNothing);
    });

    testWidgets('9 cities: search field appears above the chips',
        (tester) async {
      await tester.pumpWidget(_picker(_cities(9)));
      expect(find.byType(TextField), findsOneWidget);
      expect(find.byType(NeoChip), findsNWidgets(9));
      expect(find.text('Search 9 cities'), findsOneWidget);
    });

    testWidgets('singular count label for a one-outlet city', (tester) async {
      await tester.pumpWidget(
        _picker([const AreaOption(city: 'Solo', outletCount: 1)]),
      );
      expect(find.textContaining('1 restaurant'), findsOneWidget);
    });
  });

  group('search filtering', () {
    testWidgets('typing filters the chips live', (tester) async {
      final areas = [
        ..._cities(8),
        const AreaOption(city: 'Bengaluru', outletCount: 3),
        const AreaOption(city: 'Chennai', outletCount: 1),
      ];
      await tester.pumpWidget(_picker(areas));
      expect(find.byType(NeoChip), findsNWidgets(10));

      await tester.enterText(find.byType(TextField), 'chen');
      await tester.pump();

      expect(find.byType(NeoChip), findsOneWidget);
      expect(find.textContaining('Chennai'), findsOneWidget);
    });

    testWidgets('filter is case-insensitive', (tester) async {
      final areas = [..._cities(8), const AreaOption(city: 'Bengaluru', outletCount: 3)];
      await tester.pumpWidget(_picker(areas));

      await tester.enterText(find.byType(TextField), 'BENGAL');
      await tester.pump();

      expect(find.byType(NeoChip), findsOneWidget);
      expect(find.textContaining('Bengaluru'), findsOneWidget);
    });

    testWidgets('no match shows a message rather than an empty void',
        (tester) async {
      await tester.pumpWidget(_picker(_cities(9)));
      await tester.enterText(find.byType(TextField), 'zzzz');
      await tester.pump();

      expect(find.byType(NeoChip), findsNothing);
      expect(find.textContaining('No city matches'), findsOneWidget);
    });

    testWidgets('clear button restores the full list', (tester) async {
      await tester.pumpWidget(_picker(_cities(9)));
      await tester.enterText(find.byType(TextField), 'City1');
      await tester.pump();
      expect(find.byType(NeoChip), findsOneWidget);

      await tester.tap(find.byTooltip('Clear search'));
      await tester.pump();
      expect(find.byType(NeoChip), findsNWidgets(9));
    });
  });

  group('non-list states', () {
    testWidgets('null areas shows a spinner', (tester) async {
      await tester.pumpWidget(_picker(null));
      expect(find.byType(CircularProgressIndicator), findsOneWidget);
      expect(find.byType(NeoChip), findsNothing);
    });

    testWidgets('error shows retry', (tester) async {
      await tester.pumpWidget(_picker(const [], error: 'boom'));
      expect(find.text('Retry'), findsOneWidget);
    });

    testWidgets('empty list shows the honest empty state', (tester) async {
      await tester.pumpWidget(_picker(const []));
      expect(find.textContaining('No restaurants are taking pickup orders yet'),
          findsOneWidget);
      expect(find.byType(NeoChip), findsNothing);
    });
  });
}
