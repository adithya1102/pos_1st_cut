// City picker: search + alphabetical rows, and selection that does NOT navigate.
//
// The chip/threshold model this file used to test is gone by design — chips
// wrapped into an unscannable block and gave the restaurant count no room, and
// a search field that appeared only past 8 cities meant the screen a customer
// learned was not the screen they got next month. One presentation now, at
// every list size.
import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';

import 'package:customer_app/services/catalog_service.dart';
import 'package:customer_app/theme/app_theme.dart';
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

Widget _picker(
  List<AreaOption>? areas, {
  String? selected,
  String? error,
  ValueChanged<String>? onSelect,
}) =>
    _host(AreaPicker(
      areas: areas,
      error: error,
      selected: selected,
      onSelect: onSelect ?? (_) {},
      onRetry: () {},
    ));

/// Row order as rendered, read off the city-name Text widgets.
List<String> _renderedOrder(WidgetTester tester, List<String> candidates) {
  final seen = <String>[];
  for (final w in tester.widgetList<Text>(find.byType(Text))) {
    final t = w.data;
    if (t != null && candidates.contains(t)) seen.add(t);
  }
  return seen;
}

void main() {
  group('alphabetical ascending', () {
    testWidgets('rows are sorted by name, not by outlet count', (tester) async {
      // Deliberately supplied in count-descending order — which is exactly what
      // GET /customer/areas returns — to prove the widget re-sorts.
      await tester.pumpWidget(_picker(const [
        AreaOption(city: 'Mumbai', outletCount: 9),
        AreaOption(city: 'Bengaluru', outletCount: 5),
        AreaOption(city: 'Chennai', outletCount: 2),
        AreaOption(city: 'Ahmedabad', outletCount: 1),
      ]));

      expect(
        _renderedOrder(tester, ['Ahmedabad', 'Bengaluru', 'Chennai', 'Mumbai']),
        ['Ahmedabad', 'Bengaluru', 'Chennai', 'Mumbai'],
      );
    });

    test('sorting is case-insensitive', () {
      final sorted = AreaPicker.sortedAlphabetically(const [
        AreaOption(city: 'delhi', outletCount: 1),
        AreaOption(city: 'Bengaluru', outletCount: 1),
        AreaOption(city: 'chennai', outletCount: 1),
      ]);
      expect(sorted.map((a) => a.city).toList(),
          ['Bengaluru', 'chennai', 'delhi']);
    });
  });

  group('rendering', () {
    testWidgets('search field is present even for a tiny list', (tester) async {
      // Prod currently has two cities. The old build showed no search box at
      // this size; that inconsistency is what was removed.
      await tester.pumpWidget(_picker(const [
        AreaOption(city: 'Bengaluru', outletCount: 2),
        AreaOption(city: 'Chennai', outletCount: 2),
      ]));

      expect(find.byKey(const Key('city_search_field')), findsOneWidget);
      expect(find.text('Bengaluru'), findsOneWidget);
      expect(find.text('Chennai'), findsOneWidget);
    });

    testWidgets('every row carries its restaurant count', (tester) async {
      await tester.pumpWidget(_picker(const [
        AreaOption(city: 'Bengaluru', outletCount: 4),
        AreaOption(city: 'Solo', outletCount: 1),
      ]));

      expect(find.text('4 restaurants'), findsOneWidget);
      // Singular, not "1 restaurants".
      expect(find.text('1 restaurant'), findsOneWidget);
    });

    testWidgets('a large list renders every city as a row', (tester) async {
      await tester.pumpWidget(_picker(_cities(12)));
      expect(find.text('City12'), findsOneWidget);
      expect(find.byKey(const Key('city_search_field')), findsOneWidget);
    });
  });

  group('selection is NOT navigation', () {
    testWidgets('tapping a row reports the selection and nothing else',
        (tester) async {
      final picked = <String>[];
      await tester.pumpWidget(_picker(
        const [
          AreaOption(city: 'Bengaluru', outletCount: 2),
          AreaOption(city: 'Chennai', outletCount: 2),
        ],
        onSelect: picked.add,
      ));

      await tester.tap(find.text('Chennai'));
      await tester.pump();

      expect(picked, ['Chennai']);
      // The picker is handed no navigator and no route — a tap physically
      // cannot move the app. This is the guarantee: a mis-tap while scanning
      // costs one more tap, not a screen transition to back out of.
      expect(find.byType(Navigator), findsOneWidget);
    });

    testWidgets('exactly one row reports itself selected', (tester) async {
      await tester.pumpWidget(_picker(
        const [
          AreaOption(city: 'Bengaluru', outletCount: 2),
          AreaOption(city: 'Chennai', outletCount: 2),
        ],
        selected: 'Chennai',
      ));

      // Selection is announced, not merely coloured — colour alone would leave
      // a screen-reader user with no way to tell which city is armed.
      final selectedRows = find.byWidgetPredicate(
        (w) => w is Semantics && w.properties.selected == true,
      );
      expect(selectedRows, findsOneWidget);

      // And that one row is the Chennai row.
      expect(
        find.descendant(of: selectedRows, matching: find.text('Chennai')),
        findsOneWidget,
      );
    });
  });

  group('search filtering', () {
    testWidgets('typing filters the rows live', (tester) async {
      await tester.pumpWidget(_picker([
        ..._cities(8),
        const AreaOption(city: 'Bengaluru', outletCount: 3),
        const AreaOption(city: 'Chennai', outletCount: 1),
      ]));

      await tester.enterText(
          find.byKey(const Key('city_search_field')), 'chen');
      await tester.pump();

      expect(find.text('Chennai'), findsOneWidget);
      expect(find.text('Bengaluru'), findsNothing);
      expect(find.text('City1'), findsNothing);
    });

    testWidgets('filter is case-insensitive', (tester) async {
      await tester.pumpWidget(_picker([
        ..._cities(8),
        const AreaOption(city: 'Bengaluru', outletCount: 3),
      ]));

      await tester.enterText(
          find.byKey(const Key('city_search_field')), 'BENGAL');
      await tester.pump();

      expect(find.text('Bengaluru'), findsOneWidget);
      expect(find.text('City1'), findsNothing);
    });

    testWidgets('no match explains itself rather than showing an empty void',
        (tester) async {
      await tester.pumpWidget(_picker(_cities(9)));
      await tester.enterText(
          find.byKey(const Key('city_search_field')), 'zzzz');
      await tester.pump();

      expect(find.textContaining('No city matches'), findsOneWidget);
      expect(find.text('City1'), findsNothing);
    });

    testWidgets('clear button restores the full list', (tester) async {
      await tester.pumpWidget(_picker(_cities(9)));
      await tester.enterText(
          find.byKey(const Key('city_search_field')), 'City1');
      await tester.pump();
      expect(find.text('City2'), findsNothing);

      await tester.tap(find.byTooltip('Clear search'));
      await tester.pump();
      expect(find.text('City2'), findsOneWidget);
    });
  });

  group('non-list states', () {
    testWidgets('null areas shows a spinner', (tester) async {
      await tester.pumpWidget(_picker(null));
      expect(find.byType(CircularProgressIndicator), findsOneWidget);
      expect(find.byKey(const Key('city_search_field')), findsNothing);
    });

    testWidgets('error shows retry', (tester) async {
      await tester.pumpWidget(_picker(const [], error: 'boom'));
      expect(find.text('Retry'), findsOneWidget);
    });

    testWidgets('empty list shows the honest empty state', (tester) async {
      await tester.pumpWidget(_picker(const []));
      expect(find.textContaining('No restaurants are taking pickup orders yet'),
          findsOneWidget);
      expect(find.byKey(const Key('city_search_field')), findsNothing);
    });
  });
}
