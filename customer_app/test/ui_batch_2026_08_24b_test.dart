// Tests for the second 2026-08-24 UI batch.
//
//   CITY    multi-select city filter reaches the API as repeated params
//   SORT    real sorts work; blocked ones cannot be selected
//   CART    the resume banner appears only with a non-empty cart
//   ITEM    an unavailable item is listed, tappable, and explains itself
//   ALIGN   order-history values form a column (asserted by POSITION)
//   IDENT   the account screen shows one identifier row, correctly labelled
import 'dart:convert';

import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:http/http.dart' as http;
import 'package:http/testing.dart';
import 'package:provider/provider.dart';
import 'package:shared_preferences/shared_preferences.dart';

import 'package:customer_app/models/customer.dart';
import 'package:customer_app/models/menu.dart';
import 'package:customer_app/models/outlet.dart';
import 'package:customer_app/models/outlet_sort.dart';
import 'package:customer_app/screens/home_screen.dart';
import 'package:customer_app/screens/menu_screen.dart';
import 'package:customer_app/screens/order_history_screen.dart';
import 'package:customer_app/screens/outlets_screen.dart';
import 'package:customer_app/services/api_client.dart';
import 'package:customer_app/services/catalog_service.dart';
import 'package:customer_app/services/customer_service.dart';
import 'package:customer_app/services/google_auth_service.dart';
import 'package:customer_app/services/location_service.dart';
import 'package:customer_app/services/order_service.dart';
import 'package:customer_app/services/otp_auth_service.dart';
import 'package:customer_app/services/push_service.dart';
import 'package:customer_app/state/auth_state.dart';
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

ApiClient _client(Future<http.Response> Function(http.Request) handler) {
  SharedPreferences.setMockInitialValues({'carevo_access_token': 'valid'});
  return ApiClient(client: MockClient(handler));
}

Map<String, dynamic> _outletJson({
  required String id,
  String name = 'Test Kitchen',
  double? distanceKm,
  String? createdAt,
  int offerCount = 0,
  String? offerText,
}) =>
    {
      'id': id,
      'name': name,
      'address': 'Somewhere',
      'is_open': true,
      'distance_km': distanceKm,
      'created_at': createdAt,
      'offer_count': offerCount,
      'offer_text': offerText,
    };

Outlet _outlet({String id = 'o1'}) => Outlet.fromJson(_outletJson(id: id));

MenuItem _item({
  required String id,
  required String name,
  double price = 100,
  bool available = true,
}) =>
    MenuItem.fromJson({
      'id': id,
      'name': name,
      'base_price': price,
      'is_veg': true,
      'is_available': available,
      'prep_time_minutes': 0,
      'tags': const <String>[],
      'customizations': const [],
    });

void main() {
  // =========================================================================
  // CITY — multi-select reaches the API as repeated params
  // =========================================================================
  group('CITY: several cities are sent as repeated query params', () {
    test('two cities produce ?city=A&city=B, not one joined value', () async {
      final urls = <Uri>[];
      final api = _client((req) async {
        urls.add(req.url);
        return _json(const []);
      });

      await CatalogService(api)
          .fetchOutlets(cities: {'Bengaluru', 'Chennai'});

      final params = urls.single.queryParametersAll['city'];
      expect(params, isNotNull);
      expect(params!.toSet(), {'Bengaluru', 'Chennai'},
          reason: 'each city must be its own parameter — a single '
              '"[Bengaluru, Chennai]" value is one nonexistent city');
    });

    test('one city still sends a single param, unchanged', () async {
      final urls = <Uri>[];
      final api = _client((req) async {
        urls.add(req.url);
        return _json(const []);
      });

      await CatalogService(api).fetchOutlets(cities: {'Bengaluru'});

      expect(urls.single.queryParametersAll['city'], ['Bengaluru']);
    });

    test('no cities sends no city param at all', () async {
      final urls = <Uri>[];
      final api = _client((req) async {
        urls.add(req.url);
        return _json(const []);
      });

      await CatalogService(api).fetchOutlets();

      expect(urls.single.queryParametersAll.containsKey('city'), isFalse);
    });

    test('blank entries are dropped rather than sent as empty params',
        () async {
      final urls = <Uri>[];
      final api = _client((req) async {
        urls.add(req.url);
        return _json(const []);
      });

      await CatalogService(api).fetchOutlets(cities: {'Bengaluru', '  ', ''});

      expect(urls.single.queryParametersAll['city'], ['Bengaluru']);
    });

    testWidgets('the list shows outlets from ALL selected cities',
        (tester) async {
      _sizeSurface(tester);
      // The server returns the union; this pins that the screen renders it
      // rather than re-narrowing to one city on the client.
      final api = _client((req) async {
        if (req.url.path.contains('/customer/orders')) return _json(const []);
        if (req.url.path.contains('/customer/outlets')) {
          return _json([
            _outletJson(id: 'blr', name: 'Bengaluru Kitchen'),
            _outletJson(id: 'maa', name: 'Chennai Kitchen'),
          ]);
        }
        return _json(const []);
      });

      await tester.pumpWidget(MultiProvider(
        providers: [
          Provider<ApiClient>.value(value: api),
          Provider<CatalogService>(create: (_) => CatalogService(api)),
          Provider<CustomerService>(create: (_) => CustomerService(api)),
          ChangeNotifierProvider<CartState>(create: (_) => CartState()),
          ChangeNotifierProvider<ThemeProvider>(create: (_) => ThemeProvider()),
        ],
        child: MaterialApp(
          theme: AppTheme.light(),
          home: const OutletsScreen(cities: {'Bengaluru', 'Chennai'}),
        ),
      ));
      await tester.pump(const Duration(milliseconds: 600));

      expect(find.text('Bengaluru Kitchen'), findsOneWidget);
      expect(find.text('Chennai Kitchen'), findsOneWidget);
      // Subtitle names both rather than claiming one.
      expect(find.text('In Bengaluru & Chennai'), findsOneWidget);
    });
  });

  // =========================================================================
  // SORT — real options work, blocked options cannot be selected
  // =========================================================================
  group('SORT: only the three backed options do anything', () {
    test('exactly three options are available; six more say "coming soon"', () {
      // Was "seven are not". Recommended is hidden rather than greyed, so it
      // has left comingSoon — the enabled three are unchanged.
      expect(OutletSort.enabled,
          [OutletSort.nearest, OutletSort.newest, OutletSort.bestOffers]);
      expect(OutletSort.comingSoon, hasLength(6));
      expect(OutletSort.comingSoon, isNot(contains(OutletSort.recommended)));
    });

    test('every blocked option states WHY it is blocked', () {
      for (final s in OutletSort.comingSoon) {
        expect(s.blockedBy, isNotNull, reason: '${s.name} needs a reason');
        expect(s.blockedBy, isNotEmpty);
      }
      // And the working ones claim no blocker.
      for (final s in OutletSort.enabled) {
        expect(s.blockedBy, isNull);
      }
    });

    test('nearest sorts by distance, unknown last', () {
      final sorted = OutletSort.nearest.apply([
        Outlet.fromJson(_outletJson(id: 'far', distanceKm: 9)),
        Outlet.fromJson(_outletJson(id: 'unk')),
        Outlet.fromJson(_outletJson(id: 'near', distanceKm: 0.5)),
      ]);
      expect(sorted.map((o) => o.id), ['near', 'far', 'unk']);
    });

    test('newest sorts by creation date descending, unknown last', () {
      final sorted = OutletSort.newest.apply([
        Outlet.fromJson(
            _outletJson(id: 'old', createdAt: '2024-01-01T00:00:00Z')),
        Outlet.fromJson(_outletJson(id: 'unk')),
        Outlet.fromJson(
            _outletJson(id: 'new', createdAt: '2026-01-01T00:00:00Z')),
      ]);
      expect(sorted.map((o) => o.id), ['new', 'old', 'unk']);
    });

    test('bestOffers floats outlets with the most offers first', () {
      final sorted = OutletSort.bestOffers.apply([
        Outlet.fromJson(_outletJson(id: 'none')),
        Outlet.fromJson(
            _outletJson(id: 'two', offerCount: 2, offerText: '20% off')),
        Outlet.fromJson(
            _outletJson(id: 'one', offerCount: 1, offerText: '10% off')),
      ]);
      expect(sorted.map((o) => o.id), ['two', 'one', 'none']);
    });

    test('a blocked option leaves the order untouched rather than faking one',
        () {
      final input = [
        Outlet.fromJson(_outletJson(id: 'b', distanceKm: 9)),
        Outlet.fromJson(_outletJson(id: 'a', distanceKm: 1)),
      ];
      for (final s in OutletSort.comingSoon) {
        expect(s.apply(input).map((o) => o.id), ['b', 'a'],
            reason: '${s.name} must not invent an ordering');
      }
    });

    test('apply never mutates its input', () {
      final input = [
        Outlet.fromJson(_outletJson(id: 'far', distanceKm: 9)),
        Outlet.fromJson(_outletJson(id: 'near', distanceKm: 1)),
      ];
      OutletSort.nearest.apply(input);
      expect(input.map((o) => o.id), ['far', 'near']);
    });

    Widget sortHost() {
      final api = _client((req) async {
        if (req.url.path.contains('/customer/orders')) return _json(const []);
        if (req.url.path.contains('/customer/outlets')) {
          return _json([_outletJson(id: 'a', distanceKm: 1)]);
        }
        return _json(const []);
      });
      return MultiProvider(
        providers: [
          Provider<ApiClient>.value(value: api),
          Provider<CatalogService>(create: (_) => CatalogService(api)),
          Provider<CustomerService>(create: (_) => CustomerService(api)),
          ChangeNotifierProvider<LocationService>(
              create: (_) => LocationService()),
          ChangeNotifierProvider<CartState>(create: (_) => CartState()),
          ChangeNotifierProvider<ThemeProvider>(create: (_) => ThemeProvider()),
        ],
        child: MaterialApp(theme: AppTheme.light(), home: const OutletsScreen()),
      );
    }

    /// Open the collapsed filter sheet.
    ///
    /// The horizontal sort bar was replaced by a filter button (2026-08-25),
    /// so the options are reached by opening the sheet rather than by
    /// scrolling a row. Every option is built at once inside it, so no
    /// per-option scrolling is needed any more.
    Future<void> openSortSheet(WidgetTester tester) async {
      await tester.tap(find.byKey(const Key('filter_button')));
      await tester.pumpAndSettle();
    }

    /// Bring a sort option into view inside the open sheet.
    Future<void> scrollToSort(WidgetTester tester, OutletSort s) async {
      final target = find.byKey(Key('sort_${s.name}'));
      if (target.evaluate().isNotEmpty) return;
      await tester.scrollUntilVisible(target, 80,
          scrollable: find.descendant(
            of: find.byKey(const Key('sort_sheet')),
            matching: find.byType(Scrollable),
          ).first);
      await tester.pump();
    }

    testWidgets('every VISIBLE option is reachable, not just the working three',
        (tester) async {
      // Was "all ten". Recommended is hidden now; the remaining blocked
      // options are still shown so the intended shape stays honest.
      _sizeSurface(tester);
      await tester.pumpWidget(sortHost());
      await tester.pump(const Duration(milliseconds: 600));
      await openSortSheet(tester);

      for (final s in OutletSort.visible) {
        await scrollToSort(tester, s);
        expect(find.byKey(Key('sort_${s.name}')), findsOneWidget,
            reason: '${s.label} should be present in the bar');
      }
      expect(find.byKey(const Key('sort_recommended')), findsNothing);
    });

    testWidgets('every blocked option carries a "Coming soon" caption',
        (tester) async {
      _sizeSurface(tester);
      await tester.pumpWidget(sortHost());
      await tester.pump(const Duration(milliseconds: 600));

      await openSortSheet(tester);

      // Asserted per-option rather than by counting, so virtualisation cannot
      // make a missing caption look like a scrolled-out one.
      for (final s in OutletSort.comingSoon) {
        await scrollToSort(tester, s);
        expect(
          find.descendant(
            of: find.byKey(Key('sort_${s.name}')),
            matching: find.text('Coming soon'),
          ),
          findsOneWidget,
          reason: '${s.label} must say it is not ready, not just look grey',
        );
      }
    });

    testWidgets('a working option carries NO "Coming soon" caption',
        (tester) async {
      _sizeSurface(tester);
      await tester.pumpWidget(sortHost());
      await tester.pump(const Duration(milliseconds: 600));

      await openSortSheet(tester);

      for (final s in OutletSort.enabled) {
        await scrollToSort(tester, s);
        expect(
          find.descendant(
            of: find.byKey(Key('sort_${s.name}')),
            matching: find.text('Coming soon'),
          ),
          findsNothing,
        );
      }
    });

    testWidgets('a blocked option is NOT selectable and does nothing when hit',
        (tester) async {
      _sizeSurface(tester);
      await tester.pumpWidget(sortHost());
      await tester.pump(const Duration(milliseconds: 600));

      await openSortSheet(tester);
      await scrollToSort(tester, OutletSort.highestRated);
      final blocked = find.byKey(const Key('sort_highestRated'));
      expect(blocked, findsOneWidget);

      // Announced as disabled to a screen reader, not merely drawn grey.
      final semantics = tester.widget<Semantics>(
        find.ancestor(of: blocked, matching: find.byType(Semantics)).first,
      );
      expect(semantics.properties.enabled, isFalse);

      // The tap is swallowed by IgnorePointer — the widget does not even
      // receive it, so it cannot silently no-op.
      await tester.tap(blocked, warnIfMissed: false);
      await tester.pump(const Duration(milliseconds: 300));

      // It did not become the active sort.
      expect(
        find.descendant(of: blocked, matching: find.text('Coming soon')),
        findsOneWidget,
        reason: 'a blocked option must stay blocked after being tapped',
      );
    });

    testWidgets('an enabled option IS selectable', (tester) async {
      _sizeSurface(tester);
      await tester.pumpWidget(sortHost());
      await tester.pump(const Duration(milliseconds: 600));

      await openSortSheet(tester);
      await tester.tap(find.byKey(const Key('sort_newest')));
      await tester.pumpAndSettle();

      // Selecting CLOSES the sheet — the contrast with the blocked case above
      // (which stays open because the tap never lands) is the point.
      expect(find.byKey(const Key('sort_sheet')), findsNothing);
    });
  });

  // =========================================================================
  // CART — resume banner visibility
  // =========================================================================
  group('CART: the resume banner tracks whether the cart has anything in it',
      () {
    Widget homeHost(CartState cart, {List<Map<String, dynamic>> orders = const []}) {
      final api = _client((req) async {
        if (req.url.path.endsWith('/customer/orders')) return _json(orders);
        if (req.url.path.endsWith('/customer/me')) {
          return _json({'id': 'c1', 'name': 'Asha'});
        }
        return _json(const {});
      });
      final otp = StubOtpService(api);
      return MultiProvider(
        providers: [
          Provider<ApiClient>.value(value: api),
          Provider<CustomerService>(create: (_) => CustomerService(api)),
          Provider<CatalogService>(create: (_) => CatalogService(api)),
          Provider<OrderService>(create: (_) => OrderService(api)),
          ChangeNotifierProvider<LocationService>(
              create: (_) => LocationService()),
          ChangeNotifierProvider<CartState>.value(value: cart),
          ChangeNotifierProvider<ThemeProvider>(create: (_) => ThemeProvider()),
          ChangeNotifierProvider<AuthState>(
            create: (_) => AuthState(
                api, otp, GoogleAuthService(api), PushService(api)),
          ),
        ],
        child: MaterialApp(theme: AppTheme.light(), home: const HomeScreen()),
      );
    }

    CartState emptyCart() {
      SharedPreferences.setMockInitialValues({});
      return CartState();
    }

    CartState filledCart() {
      final cart = emptyCart();
      cart.setOutlet(_outlet());
      cart.addItem(_item(id: 'i1', name: 'Dosa'), quantity: 2);
      return cart;
    }

    testWidgets('NO banner when the cart is empty', (tester) async {
      _sizeSurface(tester);
      await tester.pumpWidget(homeHost(emptyCart()));
      await tester.pump(const Duration(milliseconds: 600));

      expect(find.byKey(const Key('home_resume_cart')), findsNothing);
      expect(find.text('Continue where you left off'), findsNothing);
    });

    testWidgets('banner appears when the cart has items', (tester) async {
      _sizeSurface(tester);
      await tester.pumpWidget(homeHost(filledCart()));
      await tester.pump(const Duration(milliseconds: 600));

      expect(find.byKey(const Key('home_resume_cart')), findsOneWidget);
      expect(find.text('Continue where you left off'), findsOneWidget);
      // Names the restaurant and the quantity, so it is a prompt and not a
      // question about whose order this is.
      expect(find.textContaining('2 items from Test Kitchen'), findsOneWidget);
    });

    testWidgets('it appears for a FIRST-RUN customer too', (tester) async {
      // Zero orders says nothing about the cart: someone who browsed, added
      // items and closed the app is still first-run, and most needs this.
      _sizeSurface(tester);
      await tester.pumpWidget(homeHost(filledCart(), orders: const []));
      await tester.pump(const Duration(milliseconds: 600));

      expect(find.byKey(const Key('home_first_run')), findsOneWidget);
      expect(find.byKey(const Key('home_resume_cart')), findsOneWidget);
    });

    testWidgets('the banner and the order link coexist — two elements',
        (tester) async {
      _sizeSurface(tester);
      await tester.pumpWidget(homeHost(filledCart(), orders: [
        {
          'order_id': 'o1',
          'status': 'READY',
          'outlet_name': 'Test Kitchen',
          'payment_status': 'PAID',
          'total_amount': 150,
          'discount_amount': 0,
          'created_at': DateTime.now().toIso8601String(),
          'pickup_code': '4821',
          'items': const [],
        }
      ]));
      await tester.pump(const Duration(milliseconds: 600));

      // Shrinking the order card must not have taken the cart banner with it.
      expect(find.byKey(const Key('home_resume_cart')), findsOneWidget);
      expect(find.byKey(const Key('home_active_orders_link')), findsOneWidget);
    });

    testWidgets('emptying the cart removes the banner without a refetch',
        (tester) async {
      _sizeSurface(tester);
      final cart = filledCart();
      await tester.pumpWidget(homeHost(cart));
      await tester.pump(const Duration(milliseconds: 600));
      expect(find.byKey(const Key('home_resume_cart')), findsOneWidget);

      cart.clear();
      await tester.pump();

      expect(find.byKey(const Key('home_resume_cart')), findsNothing);
    });
  });

  // =========================================================================
  // ITEM — unavailable placeholder
  // =========================================================================
  group('ITEM: a sold-out item is listed, tappable, and explains itself', () {
    final navKey = GlobalKey<NavigatorState>();

    Widget menuHost() {
      final api = _client((req) async {
        if (req.url.path.contains('/customer/menu')) {
          return _json({
            'categories': [
              {
                'id': 'c1',
                'name': 'Mains',
                'items': [
                  {
                    'id': 'i1',
                    'name': 'Masala Dosa',
                    'base_price': 90,
                    'is_veg': true,
                    'is_available': true,
                  },
                  {
                    'id': 'i2',
                    'name': 'Paneer Tikka',
                    'base_price': 220,
                    'is_veg': true,
                    'is_available': false,
                  },
                ],
              }
            ]
          });
        }
        return _json(const {});
      });
      return MultiProvider(
        providers: [
          Provider<ApiClient>.value(value: api),
          Provider<CatalogService>(create: (_) => CatalogService(api)),
          ChangeNotifierProvider<CartState>(create: (_) => CartState()),
          ChangeNotifierProvider<ThemeProvider>(create: (_) => ThemeProvider()),
        ],
        child: MaterialApp(
          theme: AppTheme.light(),
          navigatorKey: navKey,
          home: const Scaffold(body: SizedBox.shrink()),
        ),
      );
    }

    Future<void> openMenu(WidgetTester tester) async {
      navKey.currentState!.push(
        MaterialPageRoute(builder: (_) => MenuScreen(outlet: _outlet())),
      );
      await tester.pump();
      await tester.pump(const Duration(milliseconds: 600));
    }

    testWidgets('it is LISTED rather than hidden', (tester) async {
      _sizeSurface(tester);
      await tester.pumpWidget(menuHost());
      await openMenu(tester);

      expect(find.text('Paneer Tikka'), findsOneWidget,
          reason: 'hiding it makes "sold out" indistinguishable from '
              '"removed from the menu"');
      // And it is visibly marked, not silently identical to an orderable row.
      expect(find.text('OUT'), findsOneWidget);
      expect(find.text('ADD'), findsOneWidget);
    });

    testWidgets('tapping it says "{item name} — not available"',
        (tester) async {
      _sizeSurface(tester);
      await tester.pumpWidget(menuHost());
      await openMenu(tester);

      await tester.tap(find.text('Paneer Tikka'));
      await tester.pump(const Duration(milliseconds: 300));

      expect(find.text('Paneer Tikka — not available'), findsOneWidget);
    });

    testWidgets('tapping it does NOT open the dish screen', (tester) async {
      _sizeSurface(tester);
      await tester.pumpWidget(menuHost());
      await openMenu(tester);

      await tester.tap(find.text('Paneer Tikka'));
      await tester.pump(const Duration(milliseconds: 400));

      // Still on the menu — the dish screen exists to build an order line and
      // there is nothing to build.
      expect(find.byType(MenuScreen), findsOneWidget);
      expect(find.text('Customise'), findsNothing);
    });

    testWidgets('an AVAILABLE item still opens normally', (tester) async {
      _sizeSurface(tester);
      await tester.pumpWidget(menuHost());
      await openMenu(tester);

      await tester.tap(find.text('Masala Dosa'));
      await tester.pumpAndSettle();

      expect(find.text('Customise'), findsOneWidget);
      expect(find.textContaining('not available'), findsNothing);
    });
  });

  // =========================================================================
  // ALIGN — order history column geometry, asserted by POSITION
  // =========================================================================
  group('ALIGN: order-history values form a column', () {
    Widget historyHost(Map<String, dynamic> order) {
      final api = _client((req) async {
        if (req.url.path.contains('/customer/orders')) return _json([order]);
        return _json(const []);
      });
      return MultiProvider(
        providers: [
          Provider<ApiClient>.value(value: api),
          Provider<CustomerService>(create: (_) => CustomerService(api)),
          ChangeNotifierProvider<ThemeProvider>(create: (_) => ThemeProvider()),
        ],
        child: MaterialApp(
          theme: AppTheme.light(),
          home: const OrderHistoryScreen(),
        ),
      );
    }

    Map<String, dynamic> order({
      required double amount,
      required String status,
      String? code,
    }) =>
        {
          'order_id': 'o1',
          'status': status,
          'outlet_name': 'Test Kitchen',
          'payment_status': 'PAID',
          'total_amount': amount,
          'discount_amount': 0,
          'created_at': DateTime.now().toIso8601String(),
          'pickup_code': code,
          'items': const [],
        };

    testWidgets('price, status and pickup code share a right edge',
        (tester) async {
      _sizeSurface(tester);
      await tester.pumpWidget(
          historyHost(order(amount: 150, status: 'READY', code: '4821')));
      await tester.pump(const Duration(milliseconds: 600));

      double rightOf(Finder f) =>
          tester.getTopRight(f).dx;

      final priceRight = rightOf(find.text('₹150.00'));
      final statusRight = rightOf(find.text('READY'));
      final codeRight = rightOf(find.text('4821'));

      expect(statusRight, closeTo(priceRight, 0.5),
          reason: 'status must sit under the price, not offset from it');
      expect(codeRight, closeTo(priceRight, 0.5),
          reason: 'pickup code must sit under the price too');
    });

    testWidgets('they share a LEFT edge as well, for values that fit the slot',
        (tester) async {
      // The right edges always matched; what was ragged was the left. The
      // min-width slot is what gives short values a common start.
      _sizeSurface(tester);
      await tester.pumpWidget(
          historyHost(order(amount: 150, status: 'READY', code: '4821')));
      await tester.pump(const Duration(milliseconds: 600));

      final priceLeft = tester.getTopLeft(find.text('₹150.00')).dx;
      final statusLeft = tester.getTopLeft(find.text('READY')).dx;
      final codeLeft = tester.getTopLeft(find.text('4821')).dx;

      expect(statusLeft, closeTo(priceLeft, 0.5));
      expect(codeLeft, closeTo(priceLeft, 0.5));
    });

    testWidgets('alignment holds when the amount changes digit count',
        (tester) async {
      _sizeSurface(tester);
      await tester.pumpWidget(
          historyHost(order(amount: 9, status: 'READY', code: '4821')));
      await tester.pump(const Duration(milliseconds: 600));
      final shortRight = tester.getTopRight(find.text('₹9.00')).dx;
      final shortStatusRight = tester.getTopRight(find.text('READY')).dx;
      expect(shortStatusRight, closeTo(shortRight, 0.5));

      // Fully unmount before the second case. Pumping another historyHost
      // straight away reuses the same OrderHistoryScreen element, so initState
      // never re-runs and the FIRST order stays on screen — the assertion
      // would then silently re-measure the old amount.
      await tester.pumpWidget(const MaterialApp(home: SizedBox()));
      await tester.pump();

      await tester.pumpWidget(
          historyHost(order(amount: 12345.67, status: 'READY', code: '4821')));
      await tester.pump(const Duration(milliseconds: 600));
      final longRight = tester.getTopRight(find.text('₹12345.67')).dx;
      final longStatusRight = tester.getTopRight(find.text('READY')).dx;

      expect(longStatusRight, closeTo(longRight, 0.5),
          reason: 'a longer amount must not knock the column out of line');
    });
  });

  // =========================================================================
  // IDENT — one identifier row on the account screen
  // =========================================================================
  group('IDENT: the account shows ONE identifier, labelled to match', () {
    Customer phoneOnly() => Customer.fromJson(
        {'id': 'c1', 'name': 'Asha', 'phone_number': '+919876543210'});
    Customer emailOnly() => Customer.fromJson(
        {'id': 'c1', 'name': 'Asha', 'email': 'asha@example.com'});
    Customer both() => Customer.fromJson({
          'id': 'c1',
          'name': 'Asha',
          'phone_number': '+919876543210',
          'email': 'asha@example.com',
        });
    Customer neither() => Customer.fromJson({'id': 'c1', 'name': 'Asha'});

    test('a phone-signed-in account shows its phone', () {
      expect(phoneOnly().identifierLabel, 'Phone');
      expect(phoneOnly().identifierDisplay, '+919876543210');
    });

    test('a Google-signed-in account shows its email', () {
      expect(emailOnly().identifierLabel, 'Email');
      expect(emailOnly().identifierDisplay, 'asha@example.com');
    });

    test('if BOTH are somehow set, phone wins — deterministically', () {
      // Nothing populates both today, but nothing forbids it either, so the
      // tie is broken on purpose rather than by whichever branch ran first.
      expect(both().identifierLabel, 'Phone');
      expect(both().identifierDisplay, '+919876543210');
    });

    test('neither set falls back to a combined label and a dash', () {
      expect(neither().identifierLabel, 'Phone/Email');
      expect(neither().identifierDisplay, '—');
    });
  });
}
