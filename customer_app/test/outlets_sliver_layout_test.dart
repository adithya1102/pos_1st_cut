// The outlet list is ONE scroll region with ONE pinned element.
//
// It used to be a Column of five fixed children over an Expanded(ListView): the
// header, the active-order strip, the search row, the result count and the
// offers chip all held their space permanently, and only the cards scrolled.
// Two things came out of that, and both are what these tests pin:
//
//  * the active-order strip had to be capped at 38% of the viewport with a
//    ListView of its own, because every pixel it took came out of the list's.
//    That cap is gone, and so is the nested scrollable it needed;
//  * the RefreshIndicator wrapped only the success branch, so pulling did
//    nothing in the error, empty and filtered-to-nothing states — the three a
//    customer would most want to refresh from.
//
// Now: one CustomScrollView, one RefreshIndicator around all of it, and the
// search row pinned via SliverPersistentHeader.
import 'dart:convert';

import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:http/http.dart' as http;
import 'package:http/testing.dart';
import 'package:provider/provider.dart';
import 'package:shared_preferences/shared_preferences.dart';

import 'package:customer_app/screens/outlets_screen.dart';
import 'package:customer_app/services/api_client.dart';
import 'package:customer_app/services/catalog_service.dart';
import 'package:customer_app/services/customer_service.dart';
import 'package:customer_app/services/location_service.dart';
import 'package:customer_app/services/order_service.dart';
import 'package:customer_app/state/cart_state.dart';
import 'package:customer_app/theme/app_theme.dart';
import 'package:customer_app/theme/theme_provider.dart';

http.Response _json(Object body, {int status = 200}) =>
    http.Response(jsonEncode(body), status,
        headers: {'content-type': 'application/json'});

/// How many times the outlet list has been requested — the evidence that a
/// pull-to-refresh actually re-fetched rather than merely animating.
late int outletFetches;

Map<String, dynamic> _outlet(int i) => {
      'id': 'o$i',
      'name': 'Kitchen $i',
      'address': 'Somewhere, Bengaluru',
      'city': 'Bengaluru',
      'is_open': true,
      'order_status': 'ACCEPTING',
      'offer_count': 0,
    };

Map<String, dynamic> _order(int i) => {
      'order_id': 'ord$i',
      'id': 'ord$i',
      'status': 'READY',
      'outlet_name': 'Kitchen $i',
      'payment_status': 'PAID',
      'total_amount': 250,
      'discount_amount': 0,
      'created_at': DateTime.now().toIso8601String(),
      'pickup_code': 'CODE$i',
      'items': [
        {'name': 'Dosa', 'quantity': 1, 'line_total': 250}
      ],
    };

/// [outletStatus] drives the error branch; [outletCount] the empty one.
Widget _host({
  int outletCount = 12,
  int activeOrders = 0,
  int outletStatus = 200,
}) {
  SharedPreferences.setMockInitialValues({'carevo_access_token': 'valid'});
  final api = ApiClient(client: MockClient((req) async {
    final path = req.url.path;
    if (path.endsWith('/customer/outlets')) {
      outletFetches++;
      if (outletStatus != 200) {
        return _json({'detail': 'boom'}, status: outletStatus);
      }
      return _json(List.generate(outletCount, _outlet));
    }
    if (path.endsWith('/customer/orders')) {
      return _json(List.generate(activeOrders, _order));
    }
    if (path.endsWith('/customer/areas')) return _json(const []);
    return _json(const []);
  }));

  return MultiProvider(
    providers: [
      Provider<ApiClient>.value(value: api),
      Provider<CatalogService>(create: (_) => CatalogService(api)),
      Provider<CustomerService>(create: (_) => CustomerService(api)),
      Provider<OrderService>(create: (_) => OrderService(api)),
      ChangeNotifierProvider<LocationService>(create: (_) => LocationService()),
      ChangeNotifierProvider<CartState>(create: (_) => CartState()),
      ChangeNotifierProvider<ThemeProvider>(create: (_) => ThemeProvider()),
    ],
    child: MaterialApp(
      theme: AppTheme.light(),
      home: const OutletsScreen(),
    ),
  );
}

/// A tall-enough surface that a 12-outlet list genuinely overflows it.
void _sizeSurface(WidgetTester tester) {
  tester.view.physicalSize = const Size(420, 900);
  tester.view.devicePixelRatio = 1.0;
  addTearDown(tester.view.reset);
}

/// Drag the list UP by [dy] logical pixels, scrolling content off the top.
///
/// The distance actually scrolled is [dy] minus the touch slop the gesture
/// spends reaching the drag threshold, so nothing below asserts an absolute
/// travel — the assertions compare widgets against EACH OTHER, which is the
/// real property anyway: one region or two.
Future<void> _scrollUp(WidgetTester tester, double dy) async {
  await tester.drag(find.byType(CustomScrollView), Offset(0, -dy));
  await tester.pumpAndSettle();
}

/// Pull DOWN far enough to trigger the RefreshIndicator.
Future<void> _pullToRefresh(WidgetTester tester) async {
  await tester.fling(find.byType(CustomScrollView), const Offset(0, 320), 1000);
  await tester.pumpAndSettle();
}

void main() {
  setUp(() => outletFetches = 0);

  // =========================================================================
  // Structure
  // =========================================================================
  group('one scroll view', () {
    testWidgets('the body is a single CustomScrollView', (tester) async {
      _sizeSurface(tester);
      await tester.pumpWidget(_host());
      await tester.pumpAndSettle();

      expect(find.byType(CustomScrollView), findsOneWidget);
    });

    testWidgets('exactly ONE RefreshIndicator, around everything',
        (tester) async {
      // It used to be inside the success branch, which is why the error and
      // empty states could not be refreshed at all.
      _sizeSurface(tester);
      await tester.pumpWidget(_host());
      await tester.pumpAndSettle();

      expect(find.byType(RefreshIndicator), findsOneWidget);
      expect(
        find.descendant(
          of: find.byType(RefreshIndicator),
          matching: find.byType(CustomScrollView),
        ),
        findsOneWidget,
      );
    });
  });

  // =========================================================================
  // Pinning
  // =========================================================================
  group('the search bar is the only pinned element', () {
    testWidgets('it stays put while the list scrolls', (tester) async {
      _sizeSurface(tester);
      await tester.pumpWidget(_host());
      await tester.pumpAndSettle();

      final searchBefore =
          tester.getTopLeft(find.byKey(const Key('outlet_search'))).dy;
      final cardBefore = tester.getTopLeft(find.text('Kitchen 0')).dy;
      await _scrollUp(tester, 400);

      expect(find.byKey(const Key('outlet_search')), findsOneWidget,
          reason: 'the search field must survive a scroll that moves the list');
      final searchAfter =
          tester.getTopLeft(find.byKey(const Key('outlet_search'))).dy;
      final cardAfter = tester.getTopLeft(find.text('Kitchen 0')).dy;

      // The field rose to the pinned position and STOPPED. The content did not
      // — it travelled strictly further, which is the difference between a
      // pinned header and one that merely scrolls with everything else.
      expect(searchAfter, lessThan(searchBefore));
      expect(searchBefore - searchAfter, lessThan(cardBefore - cardAfter));
    });

    testWidgets('a second, larger scroll does not move it again',
        (tester) async {
      // Once pinned it is pinned: the distinguishing property between this and
      // a header that merely scrolls slowly.
      _sizeSurface(tester);
      await tester.pumpWidget(_host());
      await tester.pumpAndSettle();

      await _scrollUp(tester, 400);
      final pinned = tester.getTopLeft(find.byKey(const Key('outlet_search')));
      await _scrollUp(tester, 300);
      final still = tester.getTopLeft(find.byKey(const Key('outlet_search')));

      expect(still.dy, moreOrLessEquals(pinned.dy, epsilon: 0.5));
    });

    testWidgets('everything else scrolls away', (tester) async {
      _sizeSurface(tester);
      await tester.pumpWidget(_host());
      await tester.pumpAndSettle();

      // All present at rest.
      expect(find.text('Pick a spot'), findsOneWidget);
      expect(find.byKey(const Key('location_chip')), findsOneWidget);
      expect(find.byKey(const Key('chip_offers')), findsOneWidget);

      await _scrollUp(tester, 400);

      // Gone, while the search field above is still there — which is the whole
      // point of pinning exactly one thing.
      expect(find.text('Pick a spot'), findsNothing);
      expect(find.byKey(const Key('location_chip')), findsNothing);
      expect(find.byKey(const Key('outlet_search')), findsOneWidget);
    });

    testWidgets('the header block and the cards move TOGETHER', (tester) async {
      // One continuous region: the header and the list must shift by the same
      // amount, not scroll independently as they did when the list was the
      // only scrollable.
      _sizeSurface(tester);
      await tester.pumpWidget(_host());
      await tester.pumpAndSettle();

      final headerBefore = tester.getTopLeft(find.text('Pick a spot')).dy;
      final cardBefore = tester.getTopLeft(find.text('Kitchen 0')).dy;

      await _scrollUp(tester, 60);

      final headerAfter = tester.getTopLeft(find.text('Pick a spot')).dy;
      final cardAfter = tester.getTopLeft(find.text('Kitchen 0')).dy;

      final headerMoved = headerBefore - headerAfter;
      final cardMoved = cardBefore - cardAfter;

      expect(headerMoved, greaterThan(0));
      // The SAME distance. Two scroll regions would move by different amounts,
      // or one would not move at all.
      expect(headerMoved, moreOrLessEquals(cardMoved, epsilon: 0.5));
    });
  });

  // =========================================================================
  // The active-order strip, in its new home
  // =========================================================================
  group('active-order banner', () {
    testWidgets('renders nothing with no active orders', (tester) async {
      _sizeSurface(tester);
      await tester.pumpWidget(_host(activeOrders: 0));
      await tester.pumpAndSettle();

      expect(find.byKey(const Key('active_order_ord0')), findsNothing);
      expect(find.textContaining('orders in progress'), findsNothing);
    });

    testWidgets('one order renders one card and no count', (tester) async {
      _sizeSurface(tester);
      await tester.pumpWidget(_host(activeOrders: 1));
      await tester.pumpAndSettle();

      expect(find.byKey(const Key('active_order_ord0')), findsOneWidget);
      // The count line only appears past one — a "1 order in progress" heading
      // over a single card says nothing the card does not.
      expect(find.textContaining('orders in progress'), findsNothing);
    });

    testWidgets('several orders: every card exists, none clipped away',
        (tester) async {
      // THE regression the 38% cap was protecting against. With the cap gone
      // the strip is as tall as its orders and the page scrolls instead —
      // every code must still be reachable.
      _sizeSurface(tester);
      await tester.pumpWidget(_host(activeOrders: 4));
      await tester.pumpAndSettle();

      expect(find.text('4 orders in progress'), findsOneWidget);

      for (var i = 0; i < 4; i++) {
        final card = find.byKey(Key('active_order_ord$i'));
        await tester.scrollUntilVisible(card, 120,
            scrollable: find.byType(Scrollable).first);
        expect(card, findsOneWidget);
      }
    });

    testWidgets('the outlet list is still reachable past four orders',
        (tester) async {
      // The failure the cap existed to prevent was the restaurant list being
      // squeezed to nothing. Scrolling now solves it, so the cards must still
      // be arrivable at.
      _sizeSurface(tester);
      await tester.pumpWidget(_host(activeOrders: 4));
      await tester.pumpAndSettle();

      await tester.scrollUntilVisible(find.text('Kitchen 0'), 200,
          scrollable: find.byType(Scrollable).first);
      expect(find.text('Kitchen 0'), findsOneWidget);
    });

    testWidgets('introduces NO scrollable of its own', (tester) async {
      // The nested-scroll fix, asserted structurally rather than by feel: the
      // strip used to hold a ListView, so a drag over it went to that ListView
      // instead of the page.
      //
      // Asserted by widget TYPE rather than by counting Scrollables — every
      // TextField carries one internally for its own text, so the search field
      // means a raw Scrollable count is never 1 and would say nothing.
      _sizeSurface(tester);
      await tester.pumpWidget(_host(activeOrders: 4));
      await tester.pumpAndSettle();

      expect(find.byType(ListView), findsNothing);
      expect(find.byType(SingleChildScrollView), findsNothing);
      expect(find.byType(CustomScrollView), findsOneWidget);
    });

    testWidgets('a drag STARTING on an order card scrolls the page',
        (tester) async {
      // The behavioural half of the same fix. Previously this drag would have
      // been consumed by the strip's own ListView and the page would not have
      // moved at all.
      _sizeSurface(tester);
      await tester.pumpWidget(_host(activeOrders: 4));
      await tester.pumpAndSettle();

      final before = tester.getTopLeft(find.text('Pick a spot')).dy;
      await tester.drag(
          find.byKey(const Key('active_order_ord0')), const Offset(0, -80));
      await tester.pumpAndSettle();
      final after = tester.getTopLeft(find.text('Pick a spot')).dy;

      expect(before - after, greaterThan(0),
          reason: 'the drag belongs to the page, not to the strip');
    });
  });

  // =========================================================================
  // Pull-to-refresh, in every state
  // =========================================================================
  group('pull-to-refresh', () {
    testWidgets('works from the success state', (tester) async {
      _sizeSurface(tester);
      await tester.pumpWidget(_host());
      await tester.pumpAndSettle();

      expect(outletFetches, 1);
      await _pullToRefresh(tester);
      expect(outletFetches, 2);
    });

    testWidgets('works from the EMPTY state', (tester) async {
      // Previously impossible: the RefreshIndicator lived in the success
      // branch, so the empty state had none to pull.
      _sizeSurface(tester);
      await tester.pumpWidget(_host(outletCount: 0));
      await tester.pumpAndSettle();

      expect(find.byKey(const Key('error_state_title')), findsOneWidget);
      expect(outletFetches, 1);
      await _pullToRefresh(tester);
      expect(outletFetches, 2);
    });

    testWidgets('works from the ERROR state', (tester) async {
      _sizeSurface(tester);
      await tester.pumpWidget(_host(outletStatus: 500));
      await tester.pumpAndSettle();

      expect(find.byKey(const Key('error_state_title')), findsOneWidget);
      expect(outletFetches, 1);
      await _pullToRefresh(tester);
      expect(outletFetches, 2);
    });

    testWidgets('the error state does not nest a scroll view', (tester) async {
      // Why the above works: ErrorStateView is asked for its non-scrolling
      // shape inside a sliver. Its own SingleChildScrollView would otherwise
      // win the drag and the indicator would never see it.
      _sizeSurface(tester);
      await tester.pumpWidget(_host(outletStatus: 500));
      await tester.pumpAndSettle();

      expect(find.byType(SingleChildScrollView), findsNothing);
      expect(find.byType(CustomScrollView), findsOneWidget);
    });
  });

  // =========================================================================
  // Keys and data flow that had to survive the move
  // =========================================================================
  group('preserved behaviour', () {
    testWidgets('every referenced key still resolves', (tester) async {
      _sizeSurface(tester);
      await tester.pumpWidget(_host());
      await tester.pumpAndSettle();

      for (final key in const [
        Key('outlet_search'),
        Key('chip_offers'),
        Key('filter_button'),
        Key('location_chip'),
        Key('radius_near_me'),
        Key('radius_travel'),
      ]) {
        expect(find.byKey(key), findsOneWidget, reason: '$key went missing');
      }
    });

    testWidgets('the result count still reads the FILTERED length',
        (tester) async {
      // The count is a sliver several positions above the list, and its number
      // comes from the enclosing FutureBuilder — which is why that builder
      // still wraps the whole scroll view rather than just the list.
      _sizeSurface(tester);
      await tester.pumpWidget(_host());
      await tester.pumpAndSettle();

      // Absent while nothing is filtering.
      expect(find.byKey(const Key('outlet_result_count')), findsNothing);

      await tester.enterText(find.byKey(const Key('outlet_search')), 'Kitchen 1');
      await tester.pumpAndSettle();

      // 'Kitchen 1', 'Kitchen 10' and 'Kitchen 11' all match.
      expect(find.text('3 restaurants'), findsOneWidget);

      await tester.enterText(find.byKey(const Key('outlet_search')), 'Kitchen 7');
      await tester.pumpAndSettle();
      expect(find.text('1 restaurant'), findsOneWidget);
    });

    testWidgets('the count SCROLLS AWAY with the rest — it is not pinned',
        (tester) async {
      // A deliberate consequence of pinning exactly one thing. The count used
      // to hold its place because nothing above the list moved at all; now
      // only the search field does, and the count travels with the content.
      //
      // Pinned here so the trade-off is recorded rather than discovered: if it
      // should ride along with the field, it belongs INSIDE the header
      // delegate, and this test is what would have to change.
      _sizeSurface(tester);
      await tester.pumpWidget(_host());
      await tester.pumpAndSettle();

      await tester.enterText(find.byKey(const Key('outlet_search')), 'Kitchen');
      await tester.pumpAndSettle();
      expect(find.byKey(const Key('outlet_result_count')), findsOneWidget);

      await _scrollUp(tester, 400);
      expect(find.byKey(const Key('outlet_result_count')), findsNothing);

      // ...and comes back, so nothing was lost — only moved. Overscrolled well
      // past the top so the scroll clamps at zero rather than landing a touch
      // short of it.
      await _scrollUp(tester, -1200);
      expect(find.byKey(const Key('outlet_result_count')), findsOneWidget);
    });

    testWidgets('the offers filter still filters', (tester) async {
      _sizeSurface(tester);
      await tester.pumpWidget(_host());
      await tester.pumpAndSettle();

      await tester.tap(find.byKey(const Key('chip_offers')));
      await tester.pumpAndSettle();

      // No outlet in this fixture has an offer, so the chip empties the list.
      expect(find.text('No restaurants match those filters.'), findsOneWidget);
    });

    testWidgets('the pinned header opens the sort sheet with the LOADED list',
        (tester) async {
      // The delegate is not rebuilt on every frame, so a callback that closed
      // over the outlet list would keep the empty first-frame one — and the
      // Nearest option would then ask for a location it did not need.
      _sizeSurface(tester);
      await tester.pumpWidget(_host());
      await tester.pumpAndSettle();

      await tester.tap(find.byKey(const Key('filter_button')));
      await tester.pumpAndSettle();

      expect(find.byKey(const Key('sort_sheet')), findsOneWidget);
    });
  });
}
