// The collapsed filter control on the restaurant list, and the enlarged cards.
//
// The horizontal ten-chip sort bar was replaced by a single filter icon that
// opens a bottom sheet. Collapsing a control hides its state, so the two things
// that must hold are:
//
//   * the sheet OPENS, applies a selection, and CLOSES itself;
//   * the icon still says whether a non-default sort is applied, since the row
//     that used to show it is gone.
//
// Which options are enabled is NOT retested here — that is
// ui_batch_2026_08_24b_test.dart's SORT group and comes from OutletSort. What
// IS retested is that collapsing the control did not quietly make a blocked
// option tappable.
import 'dart:convert';

import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:http/http.dart' as http;
import 'package:http/testing.dart';
import 'package:provider/provider.dart';
import 'package:shared_preferences/shared_preferences.dart';

import 'package:customer_app/models/outlet_sort.dart';
import 'package:customer_app/screens/outlets_screen.dart';
import 'package:customer_app/services/api_client.dart';
import 'package:customer_app/services/catalog_service.dart';
import 'package:customer_app/services/customer_service.dart';
import 'package:customer_app/services/location_service.dart';
import 'package:customer_app/state/cart_state.dart';
import 'package:customer_app/theme/app_theme.dart';
import 'package:customer_app/theme/theme_provider.dart';

void _sizeSurface(WidgetTester tester) {
  tester.view.physicalSize = const Size(1170, 2532);
  tester.view.devicePixelRatio = 3.0;
  addTearDown(tester.view.reset);
}

http.Response _json(Object body, {int status = 200}) =>
    http.Response(jsonEncode(body), status,
        headers: {'content-type': 'application/json'});

/// Outlets carry a distance so the Nearest option resolves without touching
/// LocationService — this file is about the control, not the permission path.
Map<String, dynamic> _outletJson({
  required String id,
  String name = 'Test Kitchen',
  double distanceKm = 1.0,
  String? createdAt,
  int offerCount = 0,
  String? offerText,
}) =>
    {
      'id': id,
      'name': name,
      'address': 'Anna Nagar, Chennai',
      'is_open': true,
      'distance_km': distanceKm,
      'created_at': createdAt,
      'offer_count': offerCount,
      'offer_text': offerText,
    };

Widget _host(List<Map<String, dynamic>> outlets) {
  SharedPreferences.setMockInitialValues({'carevo_access_token': 'valid'});
  final api = ApiClient(client: MockClient((req) async {
    if (req.url.path.contains('/customer/orders')) return _json(const []);
    if (req.url.path.contains('/customer/outlets')) return _json(outlets);
    return _json(const []);
  }));
  return MultiProvider(
    providers: [
      Provider<ApiClient>.value(value: api),
      Provider<CatalogService>(create: (_) => CatalogService(api)),
      Provider<CustomerService>(create: (_) => CustomerService(api)),
      ChangeNotifierProvider<LocationService>(create: (_) => LocationService()),
      ChangeNotifierProvider<CartState>(create: (_) => CartState()),
      ChangeNotifierProvider<ThemeProvider>(create: (_) => ThemeProvider()),
    ],
    child: MaterialApp(theme: AppTheme.light(), home: const OutletsScreen()),
  );
}

Future<void> _load(WidgetTester tester,
    [List<Map<String, dynamic>>? outlets]) async {
  await tester.pumpWidget(_host(outlets ?? [_outletJson(id: 'a')]));
  await tester.pump(const Duration(milliseconds: 600));
}

Future<void> _openSheet(WidgetTester tester) async {
  await tester.tap(find.byKey(const Key('filter_button')));
  await tester.pumpAndSettle();
}

void main() {
  // =========================================================================
  // The collapsed control
  // =========================================================================
  group('filter button collapses the sort bar', () {
    testWidgets('the horizontal sort bar is GONE from the screen',
        (tester) async {
      _sizeSurface(tester);
      await _load(tester);

      // The whole point of the change: none of the ten options occupies
      // screen space until asked for.
      for (final s in OutletSort.values) {
        expect(find.byKey(Key('sort_${s.name}')), findsNothing,
            reason: '${s.label} must not be on screen before the sheet opens');
      }
      expect(find.byKey(const Key('sort_sheet')), findsNothing);
      expect(find.byKey(const Key('filter_button')), findsOneWidget);
    });

    testWidgets('tapping the filter icon opens the sheet with ALL ten options',
        (tester) async {
      _sizeSurface(tester);
      await _load(tester);
      await _openSheet(tester);

      expect(find.byKey(const Key('sort_sheet')), findsOneWidget);
      for (final s in OutletSort.values) {
        expect(find.byKey(Key('sort_${s.name}')), findsOneWidget,
            reason: '${s.label} should be in the sheet');
      }
    });

    testWidgets('selecting an option CLOSES the sheet', (tester) async {
      _sizeSurface(tester);
      await _load(tester);
      await _openSheet(tester);
      expect(find.byKey(const Key('sort_sheet')), findsOneWidget);

      await tester.tap(find.byKey(const Key('sort_newest')));
      await tester.pumpAndSettle();

      expect(find.byKey(const Key('sort_sheet')), findsNothing);
    });

    testWidgets('selecting an option APPLIES it — the order actually changes',
        (tester) async {
      _sizeSurface(tester);
      // Newest-first must reverse these: 'old' is nearer, so the default
      // Nearest sort puts it first.
      await _load(tester, [
        _outletJson(
            id: 'old',
            name: 'Old Kitchen',
            distanceKm: 1,
            createdAt: '2024-01-01T00:00:00Z'),
        _outletJson(
            id: 'new',
            name: 'New Kitchen',
            distanceKm: 9,
            createdAt: '2026-01-01T00:00:00Z'),
      ]);

      double y(String id) =>
          tester.getTopLeft(find.byKey(Key('outlet_card_$id'))).dy;
      expect(y('old'), lessThan(y('new')),
          reason: 'precondition: default Nearest puts the closer one first');

      await _openSheet(tester);
      await tester.tap(find.byKey(const Key('sort_newest')));
      await tester.pumpAndSettle();

      expect(y('new'), lessThan(y('old')),
          reason: 'Newest must reorder the list, not just close the sheet');
    });

    testWidgets('dismissing without choosing leaves the sort untouched',
        (tester) async {
      _sizeSurface(tester);
      await _load(tester);
      await _openSheet(tester);

      // Tap the scrim above the sheet.
      await tester.tapAt(const Offset(10, 10));
      await tester.pumpAndSettle();

      expect(find.byKey(const Key('sort_sheet')), findsNothing);
      // Default sort still active, so no badge.
      expect(find.byKey(const Key('filter_active_badge')), findsNothing);
    });
  });

  // =========================================================================
  // The badge — the state the collapsed control would otherwise hide
  // =========================================================================
  group('the icon reports a non-default sort', () {
    testWidgets('no badge on the default sort', (tester) async {
      _sizeSurface(tester);
      await _load(tester);

      expect(OutletSort.initial, OutletSort.nearest,
          reason: 'this test assumes which sort is the default');
      expect(find.byKey(const Key('filter_active_badge')), findsNothing,
          reason: 'a badge that is always on communicates nothing');
    });

    testWidgets('badge appears once a non-default sort is applied',
        (tester) async {
      _sizeSurface(tester);
      await _load(tester);
      await _openSheet(tester);
      await tester.tap(find.byKey(const Key('sort_bestOffers')));
      await tester.pumpAndSettle();

      expect(find.byKey(const Key('filter_active_badge')), findsOneWidget,
          reason: 'the row that used to show the active sort is gone, so the '
              'icon has to carry it');
    });

    testWidgets('badge clears again when the default is reselected',
        (tester) async {
      _sizeSurface(tester);
      await _load(tester);
      await _openSheet(tester);
      await tester.tap(find.byKey(const Key('sort_newest')));
      await tester.pumpAndSettle();
      expect(find.byKey(const Key('filter_active_badge')), findsOneWidget);

      await _openSheet(tester);
      await tester.tap(find.byKey(const Key('sort_nearest')));
      await tester.pumpAndSettle();

      expect(find.byKey(const Key('filter_active_badge')), findsNothing);
    });

    testWidgets('the sheet shows which option is currently active',
        (tester) async {
      _sizeSurface(tester);
      await _load(tester);
      await _openSheet(tester);

      // Exactly one row reports itself selected — reopening the sheet has to
      // answer "what is applied?", not just "what is available?".
      final selected = find.byWidgetPredicate(
        (w) => w is Semantics && w.properties.selected == true,
      );
      expect(selected, findsOneWidget);
      expect(
        find.descendant(of: selected, matching: find.text('Nearest')),
        findsOneWidget,
      );
    });
  });

  // =========================================================================
  // Collapsing must not have made a blocked option reachable
  // =========================================================================
  group('blocked options stay blocked inside the sheet', () {
    testWidgets('a "Coming soon" option does not close the sheet or apply',
        (tester) async {
      _sizeSurface(tester);
      await _load(tester);
      await _openSheet(tester);

      await tester.tap(find.byKey(const Key('sort_highestRated')),
          warnIfMissed: false);
      await tester.pumpAndSettle();

      // Still open: the tap never reached a handler, so nothing popped.
      expect(find.byKey(const Key('sort_sheet')), findsOneWidget,
          reason: 'a blocked option must not behave like a selection');
      // And it did not become the active sort.
      final selected = find.byWidgetPredicate(
        (w) => w is Semantics && w.properties.selected == true,
      );
      expect(
        find.descendant(of: selected, matching: find.text('Highest Rated')),
        findsNothing,
      );
    });

    testWidgets('every blocked option is announced as disabled',
        (tester) async {
      _sizeSurface(tester);
      await _load(tester);
      await _openSheet(tester);

      for (final s in OutletSort.comingSoon) {
        final row = find.byKey(Key('sort_${s.name}'));
        final semantics = tester.widget<Semantics>(
          find.ancestor(of: row, matching: find.byType(Semantics)).first,
        );
        expect(semantics.properties.enabled, isFalse,
            reason: '${s.label} must read as disabled, not merely look grey');
      }
    });
  });

  // =========================================================================
  // Card size
  // =========================================================================
  group('restaurant cards are larger', () {
    testWidgets('the storefront thumbnail is 76x76', (tester) async {
      _sizeSurface(tester);
      await _load(tester);

      // Was 52x52. Asserted by measured size rather than by reading the
      // constant, so a change to the constant that does not reach the screen
      // still fails.
      final thumb = find.descendant(
        of: find.byKey(const Key('outlet_card_a')),
        matching: find.byType(Container),
      );
      final sizes = <Size>[];
      for (final e in thumb.evaluate()) {
        sizes.add(tester.getSize(find.byWidget(e.widget)));
      }
      expect(sizes.any((s) => s.width == 76 && s.height == 76), isTrue,
          reason: 'expected a 76x76 thumbnail, got: $sizes');
    });

    testWidgets('card padding is 20, not the NeoCard default 16',
        (tester) async {
      _sizeSurface(tester);
      await _load(tester);

      // Measured as the inset from the card's own top-left to the thumbnail's,
      // which is what padding actually produces on screen — reading the
      // constant back would prove nothing about the rendered result.
      final cardTopLeft =
          tester.getTopLeft(find.byKey(const Key('outlet_card_a')));
      final thumb = find
          .descendant(
            of: find.byKey(const Key('outlet_card_a')),
            matching: find.byType(Container),
          )
          .evaluate()
          .map((e) => find.byWidget(e.widget))
          .firstWhere((f) => tester.getSize(f).width == 76);
      final thumbTopLeft = tester.getTopLeft(thumb);

      // 23 = NeoCard's 3px border (AppTheme.borderWidth, which sits OUTSIDE
      // the padding) + the 20px padding. The old layout produced 3 + 16 = 19,
      // so this still discriminates between them.
      expect(thumbTopLeft.dx - cardTopLeft.dx, closeTo(23, 0.5));
      expect(thumbTopLeft.dy - cardTopLeft.dy, closeTo(23, 0.5));
    });

    testWidgets('the card is taller than the old layout', (tester) async {
      _sizeSurface(tester);
      await _load(tester);

      final h = tester.getSize(find.byKey(const Key('outlet_card_a'))).height;

      // Measured: 185.0 before this batch, 193.0 after. The threshold sits
      // between the two so the OLD layout genuinely fails it — the `> 150`
      // this replaced passed either way and tested nothing.
      //
      // Only +8 because the TEXT column, not the thumbnail, sets the card's
      // height at this content length, so the +24 on the thumb is absorbed and
      // the growth is the +4/+4 padding. The thumbnail test above is what pins
      // the larger image.
      expect(h, greaterThan(188), reason: 'measured $h, old layout was 185');
    });
  });
}
