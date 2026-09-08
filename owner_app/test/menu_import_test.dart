// Menu photo import: the review screen's four bulk actions, and the boundary
// that keeps OCR guesses out of the live menu.
//
// The safety property this feature stands on: OCR SUGGESTS, the owner DECIDES.
// A candidate is a guess read off a photograph — frequently a wrong one — and
// nothing exists in the database for it. The tests that matter most here are
// therefore the negative ones: rejecting writes nothing, an unticked row is
// never created, and leaving the screen creates nothing.
//
// Driven through the real HomeState/MenuService over a MockClient, so approval
// genuinely goes down the ordinary POST /pos/menu-items path. The request log
// is the proof; a screen assertion alone could pass while nothing was saved.
import 'dart:convert';

import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:http/http.dart' as http;
import 'package:http/testing.dart';
import 'package:provider/provider.dart';
import 'package:shared_preferences/shared_preferences.dart';

import 'package:owner_app/models/menu_candidate.dart';
import 'package:owner_app/screens/menu_import_review_screen.dart';
import 'package:owner_app/services/api_client.dart';
import 'package:owner_app/services/menu_service.dart';
import 'package:owner_app/services/outlet_service.dart';
import 'package:owner_app/state/home_state.dart';

late List<String> requestLog;
late List<Map<String, dynamic>> createdItems;

const _categoryId = 'cccccccc-dddd-eeee-ffff-000000000001';
const _create = 'POST /api/v1/pos/menu-items';

/// A backend that records every dish creation.
http.Client _backend({bool createFails = false}) {
  http.Response json(Object b, [int code = 200]) => http.Response(
      jsonEncode(b), code, headers: {'content-type': 'application/json'});

  return MockClient((req) async {
    final path = req.url.path;
    requestLog.add('${req.method} $path');

    if (path.endsWith('/pos/menu-items') && req.method == 'POST') {
      if (createFails) return json({'detail': 'boom'}, 500);
      final body = jsonDecode(req.body) as Map<String, dynamic>;
      createdItems.add(body);
      return json({
        'id': 'item-${createdItems.length}',
        'name': body['name'],
        'is_available': true,
        'is_active': true,
        'base_price': body['base_price'],
        'is_veg': body['is_veg'] ?? true,
        'category_id': body['category_id'],
      }, 201);
    }

    if (path.endsWith('/pos/menu-items')) return json(const <dynamic>[]);
    if (path.endsWith('/pos/categories')) {
      return json([
        {'id': _categoryId, 'name': 'Mains'},
      ]);
    }
    if (path.endsWith('/pos/outlet')) {
      return json({
        'id': 'aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee',
        'location_name': 'Anand Bhavan',
        'is_visible': true,
        'image_url': null,
      });
    }
    return json({'detail': 'unexpected ${req.url}'}, 404);
  });
}

Future<HomeState> _loadedHome(http.Client backend) async {
  SharedPreferences.setMockInitialValues({'gusto_owner_access_token': 'staff'});
  final api = ApiClient(httpClient: backend);
  final home = HomeState(OutletService(api), MenuService(api));
  await home.load();
  return home;
}

MenuOcrResult _result(
  List<(String, double)> rows, {
  int received = 1,
  int read = 1,
}) =>
    MenuOcrResult(
      candidates: [
        for (final (name, price) in rows) MenuCandidate(name: name, price: price),
      ],
      imagesReceived: received,
      imagesRead: read,
    );

Widget _host(HomeState home, MenuOcrResult result) =>
    ChangeNotifierProvider<HomeState>.value(
      value: home,
      child: MaterialApp(
        home: MenuImportReviewScreen(result: result, categoryId: _categoryId),
      ),
    );

int _createCount() => requestLog.where((e) => e == _create).length;

Future<void> _tap(WidgetTester tester, Key key) async {
  await tester.ensureVisible(find.byKey(key));
  await tester.pumpAndSettle();
  await tester.tap(find.byKey(key));
  await tester.pumpAndSettle();
}

const _threeDishes = [
  ('Masala Dosa', 120.0),
  ('Paneer Tikka', 260.0),
  ('Filter Coffee', 40.0),
];

void main() {
  setUp(() {
    requestLog = [];
    createdItems = [];
  });

  group('the review list', () {
    testWidgets('every candidate is listed and pre-selected', (tester) async {
      // Pre-selected because the common case is "most of this is right" —
      // ticking twenty correct rows by hand would defeat the feature.
      final home = await _loadedHome(_backend());
      await tester.pumpWidget(_host(home, _result(_threeDishes)));
      await tester.pumpAndSettle();

      expect(find.byKey(MenuImportReviewScreen.listKey), findsOneWidget);
      expect(find.text('3 of 3 selected'), findsOneWidget);
      for (var i = 0; i < 3; i++) {
        final box = tester.widget<Checkbox>(
            find.byKey(MenuImportReviewScreen.checkboxKey(i)));
        expect(box.value, isTrue);
      }
    });

    testWidgets('it says these were read from photos', (tester) async {
      final home = await _loadedHome(_backend());
      await tester.pumpWidget(_host(home, _result(_threeDishes)));
      await tester.pumpAndSettle();

      expect(find.textContaining('Read from your photos'), findsOneWidget);
    });

    testWidgets('unreadable photos are called out', (tester) async {
      // Explains a short list, rather than leaving the owner to wonder
      // whether OCR ran at all.
      final home = await _loadedHome(_backend());
      await tester.pumpWidget(
          _host(home, _result(_threeDishes, received: 5, read: 3)));
      await tester.pumpAndSettle();

      expect(find.textContaining('2 of 5 photos could not be read'),
          findsOneWidget);
    });

    testWidgets('unticking one updates the count', (tester) async {
      final home = await _loadedHome(_backend());
      await tester.pumpWidget(_host(home, _result(_threeDishes)));
      await tester.pumpAndSettle();

      await _tap(tester, MenuImportReviewScreen.checkboxKey(1));
      expect(find.text('2 of 3 selected'), findsOneWidget);
    });
  });

  group('Approve Selected', () {
    testWidgets('creates only the ticked rows', (tester) async {
      // THE boundary test: an unticked guess must never reach the menu.
      final home = await _loadedHome(_backend());
      await tester.pumpWidget(_host(home, _result(_threeDishes)));
      await tester.pumpAndSettle();

      await _tap(tester, MenuImportReviewScreen.checkboxKey(1)); // untick
      await _tap(tester, MenuImportReviewScreen.approveSelectedKey);

      expect(_createCount(), 2);
      final names = createdItems.map((i) => i['name']).toList();
      expect(names, ['Masala Dosa', 'Filter Coffee']);
      expect(names, isNot(contains('Paneer Tikka')));
    });

    testWidgets('it uses the ordinary menu-item creation path', (tester) async {
      // No parallel creation route: the same endpoint and the same body shape
      // the Add-dish form sends.
      final home = await _loadedHome(_backend());
      await tester.pumpWidget(_host(home, _result([_threeDishes.first])));
      await tester.pumpAndSettle();

      await _tap(tester, MenuImportReviewScreen.approveSelectedKey);

      expect(_createCount(), 1);
      expect(createdItems.single['name'], 'Masala Dosa');
      expect(createdItems.single['base_price'], 120.0);
      expect(createdItems.single['category_id'], _categoryId);
    });

    testWidgets('the rejected rows stay for a second pass', (tester) async {
      final home = await _loadedHome(_backend());
      await tester.pumpWidget(_host(home, _result(_threeDishes)));
      await tester.pumpAndSettle();

      await _tap(tester, MenuImportReviewScreen.checkboxKey(1));
      await _tap(tester, MenuImportReviewScreen.approveSelectedKey);

      expect(find.text('0 of 1 selected'), findsOneWidget);
      expect(find.text('Paneer Tikka'), findsOneWidget);
    });

    testWidgets('with nothing ticked it creates nothing', (tester) async {
      final home = await _loadedHome(_backend());
      await tester.pumpWidget(_host(home, _result(_threeDishes)));
      await tester.pumpAndSettle();

      for (var i = 0; i < 3; i++) {
        await _tap(tester, MenuImportReviewScreen.checkboxKey(i));
      }
      await _tap(tester, MenuImportReviewScreen.approveSelectedKey);

      expect(_createCount(), 0);
      expect(find.text('Nothing is selected.'), findsOneWidget);
    });
  });

  group('Approve All', () {
    testWidgets('creates every row, including unticked ones', (tester) async {
      // "Approve all" means ALL — it ticks first, so a row the owner unticked
      // and then changed their mind about is not silently skipped.
      final home = await _loadedHome(_backend());
      await tester.pumpWidget(_host(home, _result(_threeDishes)));
      await tester.pumpAndSettle();

      await _tap(tester, MenuImportReviewScreen.checkboxKey(0));
      await _tap(tester, MenuImportReviewScreen.approveAllKey);

      expect(_createCount(), 3);
      expect(createdItems.map((i) => i['name']).toList(),
          ['Masala Dosa', 'Paneer Tikka', 'Filter Coffee']);
    });

    testWidgets('it empties the list and closes', (tester) async {
      final home = await _loadedHome(_backend());
      await tester.pumpWidget(_host(home, _result(_threeDishes)));
      await tester.pumpAndSettle();

      await _tap(tester, MenuImportReviewScreen.approveAllKey);

      expect(find.byType(MenuImportReviewScreen), findsNothing,
          reason: 'nothing left to review, so the screen is done');
    });
  });

  group('Reject Selected and Reject All', () {
    testWidgets('Reject Selected drops rows and writes nothing',
        (tester) async {
      final home = await _loadedHome(_backend());
      await tester.pumpWidget(_host(home, _result(_threeDishes)));
      await tester.pumpAndSettle();

      await _tap(tester, MenuImportReviewScreen.checkboxKey(2)); // keep this one
      await _tap(tester, MenuImportReviewScreen.rejectSelectedKey);

      expect(_createCount(), 0, reason: 'rejecting is not a database operation');
      expect(find.text('0 of 1 selected'), findsOneWidget);
      expect(find.text('Filter Coffee'), findsOneWidget);
      expect(find.text('Masala Dosa'), findsNothing);
    });

    testWidgets('Reject All empties the list and writes nothing',
        (tester) async {
      final home = await _loadedHome(_backend());
      await tester.pumpWidget(_host(home, _result(_threeDishes)));
      await tester.pumpAndSettle();

      await _tap(tester, MenuImportReviewScreen.rejectAllKey);

      expect(_createCount(), 0);
      expect(find.byKey(MenuImportReviewScreen.emptyKey), findsOneWidget);
      expect(find.text('0 of 0 selected'), findsOneWidget);
    });

    testWidgets('Reject Selected with nothing ticked changes nothing',
        (tester) async {
      final home = await _loadedHome(_backend());
      await tester.pumpWidget(_host(home, _result(_threeDishes)));
      await tester.pumpAndSettle();

      await _tap(tester, MenuImportReviewScreen.checkboxKey(0));
      await _tap(tester, MenuImportReviewScreen.checkboxKey(1));
      await _tap(tester, MenuImportReviewScreen.checkboxKey(2));
      await _tap(tester, MenuImportReviewScreen.rejectSelectedKey);

      expect(find.text('Nothing is selected.'), findsOneWidget);
      expect(find.text('0 of 3 selected'), findsOneWidget);
    });
  });

  group('the owner corrects what OCR got wrong', () {
    testWidgets('an edited name is what gets created', (tester) async {
      // The whole reason the fields are editable: the parse is best-effort
      // and mis-reads names constantly.
      final home = await _loadedHome(_backend());
      await tester.pumpWidget(_host(home, _result([('Masaia D0sa', 120.0)])));
      await tester.pumpAndSettle();

      await tester.enterText(
          find.byKey(MenuImportReviewScreen.nameKey(0)), 'Masala Dosa');
      await tester.pumpAndSettle();
      await _tap(tester, MenuImportReviewScreen.approveSelectedKey);

      expect(createdItems.single['name'], 'Masala Dosa');
    });

    testWidgets('an edited price is what gets created', (tester) async {
      final home = await _loadedHome(_backend());
      await tester.pumpWidget(_host(home, _result([('Masala Dosa', 12.0)])));
      await tester.pumpAndSettle();

      await tester.enterText(
          find.byKey(MenuImportReviewScreen.priceKey(0)), '120');
      await tester.pumpAndSettle();
      await _tap(tester, MenuImportReviewScreen.approveSelectedKey);

      expect(createdItems.single['base_price'], 120.0);
    });

    testWidgets('an emptied name blocks the import and says so', (tester) async {
      // Caught before the POST, so the owner is told which row to fix rather
      // than watching a partial import fail item by item.
      final home = await _loadedHome(_backend());
      await tester.pumpWidget(_host(home, _result(_threeDishes)));
      await tester.pumpAndSettle();

      await tester.enterText(find.byKey(MenuImportReviewScreen.nameKey(0)), '');
      await tester.pumpAndSettle();
      await _tap(tester, MenuImportReviewScreen.approveSelectedKey);

      expect(_createCount(), 0);
      expect(find.textContaining('Fix 1 row'), findsOneWidget);
    });

    testWidgets('an edit survives a bulk selection change', (tester) async {
      // The controllers are keyed by index, so a list rebuild must carry
      // in-flight edits with it rather than reverting them.
      final home = await _loadedHome(_backend());
      await tester.pumpWidget(_host(home, _result(_threeDishes)));
      await tester.pumpAndSettle();

      await tester.enterText(
          find.byKey(MenuImportReviewScreen.nameKey(2)), 'Filter Kaapi');
      await tester.pumpAndSettle();

      // Reject only row 0, so the edited row shifts from index 2 to index 1.
      await _tap(tester, MenuImportReviewScreen.checkboxKey(1));
      await _tap(tester, MenuImportReviewScreen.checkboxKey(2));
      await _tap(tester, MenuImportReviewScreen.rejectSelectedKey);

      expect(find.text('Masala Dosa'), findsNothing, reason: 'rejected');
      // The edit followed its row across the reindex. Without the
      // controller-resync in _replaceAll this reverts to "Filter Coffee".
      expect(find.text('Filter Kaapi'), findsOneWidget);
      expect(find.text('Paneer Tikka'), findsOneWidget);
    });
  });

  group('a failed save is not silently swallowed', () {
    testWidgets('the row stays so it can be retried', (tester) async {
      final home = await _loadedHome(_backend(createFails: true));
      await tester.pumpWidget(_host(home, _result([_threeDishes.first])));
      await tester.pumpAndSettle();

      await _tap(tester, MenuImportReviewScreen.approveSelectedKey);

      expect(find.textContaining('could not be saved'), findsOneWidget);
      expect(find.text('Masala Dosa'), findsOneWidget,
          reason: 'a candidate that failed to save must not vanish');
    });
  });
}
