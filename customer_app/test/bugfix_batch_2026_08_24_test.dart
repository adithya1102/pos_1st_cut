// Regression tests for the 2026-08-24 bug batch.
//
// One group per reported bug family. Each asserts the BEHAVIOUR that was wrong,
// not the shape of the fix, so a later refactor that keeps the behaviour keeps
// the test.
//
//   A  layout stability   — fixed columns, so controls stop moving between rows
//   B  empty-state copy   — a definitionally-empty filter explains itself
//   C  confirmations      — cart removal asks; delete-account copy is accurate
//   E  cart persistence   — survives a cold start and re-syncs on resume
//   F  permissions        — an OS-side change is picked up without a restart
//   +  Home/Discover      — first-run and returning are different screens, and
//                           neither touches location
import 'dart:convert';

import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:geolocator/geolocator.dart';
import 'package:http/http.dart' as http;
import 'package:http/testing.dart';
import 'package:provider/provider.dart';
import 'package:shared_preferences/shared_preferences.dart';

import 'package:customer_app/models/menu.dart';
import 'package:customer_app/models/outlet.dart';
import 'package:customer_app/screens/cart_screen.dart';
import 'package:customer_app/screens/home_screen.dart';
import 'package:customer_app/screens/menu_screen.dart';
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
import 'package:customer_app/theme/widgets/neo_text_field.dart';
import 'package:customer_app/widgets/focus_release.dart';
import 'package:customer_app/widgets/veg_badge.dart';
import 'package:customer_app/widgets/menu_item_card.dart';

// ---------------------------------------------------------------------------
// helpers
// ---------------------------------------------------------------------------

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

MenuItem _item({
  required String id,
  required String name,
  required double price,
  bool isVeg = true,
  bool available = true,
  String? imageUrl,
  List<CustomizationGroup> customizations = const [],
}) =>
    MenuItem.fromJson({
      'id': id,
      'name': name,
      'base_price': price,
      'is_veg': isVeg,
      'is_available': available,
      'image_url': imageUrl,
      'prep_time_minutes': 0,
      'tags': const <String>[],
      'customizations': customizations.isEmpty
          ? const []
          : [
              {
                'name': 'Size',
                'required': false,
                'multi_select': false,
                'options': [
                  {'name': 'Large', 'price_delta': 20},
                ],
              }
            ],
    });

Outlet _outlet({String id = 'o1'}) => Outlet.fromJson({
      'id': id,
      'name': 'Test Kitchen',
      'address': 'Somewhere',
      'is_open': true,
    });

// ===========================================================================
// A — layout stability
// ===========================================================================
void main() {
  group('A: layout stability — content length must not move controls', () {
    /// Renders a list of items and returns each row's ADD-affordance left edge.
    Future<List<double>> addChipLefts(
      WidgetTester tester,
      List<MenuItem> items, {
      bool reserveThumbnail = false,
    }) async {
      await tester.pumpWidget(MaterialApp(
        theme: AppTheme.light(),
        home: Scaffold(
          body: ListView(
            children: [
              for (final i in items)
                MenuItemCard(
                  item: i,
                  reserveThumbnail: reserveThumbnail,
                  onTap: () {},
                ),
            ],
          ),
        ),
      ));
      await tester.pump();

      final lefts = <double>[];
      for (final label in ['ADD', 'OUT']) {
        for (final e in find.text(label).evaluate()) {
          lefts.add(tester.getTopLeft(find.byWidget(e.widget)).dx);
        }
      }
      return lefts;
    }

    testWidgets('the ADD button sits at the same x whatever the price is',
        (tester) async {
      _sizeSurface(tester);
      // The reported trigger: digit count. ₹9 through ₹12,345.
      final lefts = await addChipLefts(tester, [
        _item(id: '1', name: 'A', price: 9),
        _item(id: '2', name: 'B', price: 99),
        _item(id: '3', name: 'C', price: 999),
        _item(id: '4', name: 'D', price: 12345),
      ]);

      expect(lefts, hasLength(4));
      for (final x in lefts) {
        expect(x, closeTo(lefts.first, 0.5),
            reason: 'price digit count must not move the ADD button');
      }
    });

    testWidgets('the ADD button sits at the same x whatever the name length is',
        (tester) async {
      _sizeSurface(tester);
      final lefts = await addChipLefts(tester, [
        _item(id: '1', name: 'Tea', price: 100),
        _item(
            id: '2',
            name: 'Slow-cooked Hyderabadi Dum Biryani with Boneless Chicken',
            price: 100),
      ]);

      for (final x in lefts) {
        expect(x, closeTo(lefts.first, 0.5),
            reason: 'name length must not move the ADD button');
      }
    });

    testWidgets(
        'ADD, OUT and the customise caption all occupy the same fixed slot',
        (tester) async {
      _sizeSurface(tester);
      // The three states whose intrinsic widths used to differ.
      final lefts = await addChipLefts(tester, [
        _item(id: '1', name: 'Plain', price: 100),
        _item(id: '2', name: 'Sold out', price: 100, available: false),
        _item(
          id: '3',
          name: 'Has options',
          price: 100,
          customizations: [
            CustomizationGroup(
                name: 'Size', required: false, multiSelect: false, options: const []),
          ],
        ),
      ]);

      expect(lefts, hasLength(3));
      for (final x in lefts) {
        expect(x, closeTo(lefts.first, 0.5),
            reason: 'availability and the customise caption must not resize '
                'the action column');
      }
    });

    testWidgets(
        'the veg badge starts at the same x whether or not a row has a photo',
        (tester) async {
      _sizeSurface(tester);
      // A list mixing photo and no-photo rows — the case that misaligned the
      // badges down the whole list.
      await tester.pumpWidget(MaterialApp(
        theme: AppTheme.light(),
        home: Scaffold(
          body: ListView(
            children: [
              MenuItemCard(
                item: _item(
                    id: '1',
                    name: 'With photo',
                    price: 100,
                    imageUrl: 'https://example.invalid/a.png'),
                reserveThumbnail: true,
                onTap: () {},
              ),
              MenuItemCard(
                item: _item(id: '2', name: 'No photo', price: 100),
                reserveThumbnail: true,
                onTap: () {},
              ),
            ],
          ),
        ),
      ));
      await tester.pump();

      final badges = find.byType(VegBadge);
      expect(badges, findsNWidgets(2));
      final withPhoto = tester.getTopLeft(badges.at(0)).dx;
      final withoutPhoto = tester.getTopLeft(badges.at(1)).dx;

      expect(withoutPhoto, closeTo(withPhoto, 0.5),
          reason: 'a photoless row must reserve the thumbnail gutter so its '
              'veg badge lines up with its neighbours');
    });

    testWidgets('a list where NO row has a photo carries no empty gutter',
        (tester) async {
      _sizeSurface(tester);
      // reserveThumbnail is false here, which is what the menu screen passes
      // when nothing in the list has an image — no wasted 72px column.
      await tester.pumpWidget(MaterialApp(
        theme: AppTheme.light(),
        home: Scaffold(
          body: MenuItemCard(
            item: _item(id: '1', name: 'No photo', price: 100),
            onTap: () {},
          ),
        ),
      ));
      await tester.pump();

      final badgeX = tester.getTopLeft(find.byType(VegBadge)).dx;
      expect(badgeX, lessThan(60),
          reason: 'without sibling photos the badge should sit near the card '
              'edge, not behind a reserved gutter');
    });
  });

  // =========================================================================
  // D — keyboard / focus release
  // =========================================================================
  group('D: focus is released, so the IME and caret go with it', () {
    testWidgets('tapping outside a field drops focus', (tester) async {
      _sizeSurface(tester);
      final node = FocusNode();
      addTearDown(node.dispose);

      await tester.pumpWidget(MaterialApp(
        theme: AppTheme.light(),
        home: Scaffold(
          body: Column(
            children: [
              NeoTextField(
                key: const Key('probe_field'),
                focusNode: node,
                hintText: 'Search',
              ),
              const SizedBox(height: 100),
              const Text('somewhere else'),
            ],
          ),
        ),
      ));
      await tester.pump();

      await tester.tap(find.byType(TextField));
      await tester.pump();
      expect(node.hasFocus, isTrue, reason: 'precondition: field is focused');

      // The reported bug: this left the keyboard up and the caret blinking.
      await tester.tapAt(tester.getCenter(find.text('somewhere else')));
      await tester.pump();

      expect(node.hasFocus, isFalse,
          reason: 'a tap outside must release focus — the IME and the caret '
              'are both downstream of it');
    });

    testWidgets('navigating away releases focus', (tester) async {
      _sizeSurface(tester);
      final node = FocusNode();
      addTearDown(node.dispose);
      final navKey = GlobalKey<NavigatorState>();

      await tester.pumpWidget(MaterialApp(
        theme: AppTheme.light(),
        navigatorKey: navKey,
        navigatorObservers: [FocusReleasingObserver()],
        home: Scaffold(
          body: NeoTextField(
            key: const Key('probe_field'),
            focusNode: node,
            hintText: 'Search',
          ),
        ),
      ));
      await tester.pump();

      await tester.tap(find.byType(TextField));
      await tester.pump();
      expect(node.hasFocus, isTrue);

      // Pushing a route used to carry the open keyboard onto a screen with no
      // text field, where nothing could dismiss it.
      navKey.currentState!.push(
        MaterialPageRoute(builder: (_) => const Scaffold(body: Text('next'))),
      );
      await tester.pumpAndSettle();

      expect(node.hasFocus, isFalse);
    });
  });

  // =========================================================================
  // B — empty-state accuracy
  // =========================================================================
  group('B: a definitionally-empty filter explains itself', () {
    final menuNavKey = GlobalKey<NavigatorState>();

    Widget host(List<Map<String, dynamic>> categories) {
      final api = _client((req) async {
        if (req.url.path.contains('/customer/menu')) {
          return _json({'categories': categories});
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
          navigatorKey: menuNavKey,
          home: const Scaffold(body: SizedBox.shrink()),
        ),
      );
    }

    /// MenuScreen binds the cart in initState, which notifies listeners. That
    /// is fine when it is PUSHED (the provider above it is long since built),
    /// and an error when it is built in the same pass as its provider — so the
    /// test reaches it the way the app does.
    Future<void> openMenu(WidgetTester tester) async {
      menuNavKey.currentState!.push(
        MaterialPageRoute(builder: (_) => MenuScreen(outlet: _outlet())),
      );
      await tester.pump();
      await tester.pump(const Duration(milliseconds: 600));
    }

    Map<String, dynamic> beverages() => {
          'id': 'c1',
          'name': 'Beverages',
          'items': [
            {
              'id': 'i1',
              'name': 'Filter Coffee',
              'base_price': 40,
              'is_veg': true,
              'is_available': true,
            },
            {
              'id': 'i2',
              'name': 'Masala Chai',
              'base_price': 30,
              'is_veg': true,
              'is_available': true,
            },
          ],
        };

    testWidgets('Beverages + Non-veg says WHY, not "no items found"',
        (tester) async {
      _sizeSurface(tester);
      await tester.pumpWidget(host([beverages()]));
      await openMenu(tester);

      await tester.tap(find.text('Non-veg'));
      await tester.pump(const Duration(milliseconds: 300));

      // The explanation, in terms of the menu rather than the query.
      expect(find.textContaining('is vegetarian'), findsOneWidget);
      // And NOT the generic message this replaces.
      expect(find.textContaining('No items found'), findsNothing);
      expect(find.text('No non-veg items here.'), findsNothing);
    });

    testWidgets('it offers a way out of the filter it just explained',
        (tester) async {
      _sizeSurface(tester);
      await tester.pumpWidget(host([beverages()]));
      await openMenu(tester);

      await tester.tap(find.text('Non-veg'));
      await tester.pump(const Duration(milliseconds: 300));

      final clear = find.byKey(const Key('clear_veg_filter'));
      expect(clear, findsOneWidget);

      await tester.tap(clear);
      await tester.pump(const Duration(milliseconds: 300));
      // Back to a populated list.
      expect(find.text('Filter Coffee'), findsOneWidget);
    });

    testWidgets('a genuinely empty section is NOT described as filtered out',
        (tester) async {
      _sizeSurface(tester);
      await tester.pumpWidget(host([
        {'id': 'c1', 'name': 'Specials', 'items': const []}
      ]));
      await openMenu(tester);

      // Different cause, different message: nothing to clear here.
      expect(find.textContaining('is vegetarian'), findsNothing);
      expect(find.byKey(const Key('clear_veg_filter')), findsNothing);
    });
  });

  // =========================================================================
  // C — confirmations
  // =========================================================================
  group('C: destructive actions confirm first', () {
    Widget cartHost(CartState cart) => MultiProvider(
          providers: [
            ChangeNotifierProvider<CartState>.value(value: cart),
            ChangeNotifierProvider<ThemeProvider>(create: (_) => ThemeProvider()),
          ],
          child: MaterialApp(
            theme: AppTheme.light(),
            home: const CartScreen(),
          ),
        );

    CartState seededCart() {
      SharedPreferences.setMockInitialValues({});
      final cart = CartState();
      cart.setOutlet(_outlet());
      cart.addItem(_item(id: 'i1', name: 'Paneer Tikka', price: 220), quantity: 2);
      return cart;
    }

    testWidgets('removing a cart line asks first', (tester) async {
      _sizeSurface(tester);
      final cart = seededCart();
      await tester.pumpWidget(cartHost(cart));
      await tester.pump();

      await tester.tap(find.text('Remove'));
      await tester.pump(const Duration(milliseconds: 300));

      expect(find.byKey(const Key('confirm_remove_line')), findsOneWidget);
      // Named, so a mis-tap on the wrong card is visible in the dialog.
      expect(find.textContaining('Paneer Tikka'), findsWidgets);
      // Nothing removed yet.
      expect(cart.items, hasLength(1));
    });

    testWidgets('declining the confirmation keeps the line', (tester) async {
      _sizeSurface(tester);
      final cart = seededCart();
      await tester.pumpWidget(cartHost(cart));
      await tester.pump();

      await tester.tap(find.text('Remove'));
      await tester.pump(const Duration(milliseconds: 300));
      await tester.tap(find.text('Keep it'));
      await tester.pump(const Duration(milliseconds: 300));

      expect(cart.items, hasLength(1), reason: 'cancel must not remove');
    });

    testWidgets('accepting it removes the line', (tester) async {
      _sizeSurface(tester);
      final cart = seededCart();
      await tester.pumpWidget(cartHost(cart));
      await tester.pump();

      await tester.tap(find.text('Remove'));
      await tester.pump(const Duration(milliseconds: 300));
      await tester.tap(find.byKey(const Key('confirm_remove_line_ok')));
      await tester.pump(const Duration(milliseconds: 300));

      expect(cart.items, isEmpty);
    });

    testWidgets('decrementing the LAST unit also asks — same outcome, same gate',
        (tester) async {
      _sizeSurface(tester);
      SharedPreferences.setMockInitialValues({});
      final cart = CartState();
      cart.setOutlet(_outlet());
      cart.addItem(_item(id: 'i1', name: 'Paneer Tikka', price: 220));

      await tester.pumpWidget(cartHost(cart));
      await tester.pump();

      await tester.tap(find.byIcon(Icons.remove));
      await tester.pump(const Duration(milliseconds: 300));

      expect(find.byKey(const Key('confirm_remove_line')), findsOneWidget,
          reason: 'minus on a quantity of 1 removes the line, so it must ask');
      expect(cart.items, hasLength(1));
    });

    testWidgets('decrementing from 2 does NOT ask — it is reversible',
        (tester) async {
      _sizeSurface(tester);
      final cart = seededCart(); // quantity 2
      await tester.pumpWidget(cartHost(cart));
      await tester.pump();

      await tester.tap(find.byIcon(Icons.remove));
      await tester.pump(const Duration(milliseconds: 300));

      expect(find.byKey(const Key('confirm_remove_line')), findsNothing);
      expect(cart.items.first.quantity, 1);
    });
  });

  // =========================================================================
  // E — cart persistence
  // =========================================================================
  group('E: the cart survives a cold start and re-syncs on resume', () {
    test('a mutation reaches disk once flushed, and a fresh state restores it',
        () async {
      SharedPreferences.setMockInitialValues({});
      final first = CartState();
      first.setOutlet(_outlet());
      first.addItem(_item(id: 'i1', name: 'Dosa', price: 80), quantity: 3);

      // The durability guarantee the app shell relies on when it backgrounds.
      await first.flush();

      // Cold start: a brand new state object reading the same storage.
      final second = CartState();
      await second.restore();

      expect(second.items, hasLength(1));
      expect(second.items.first.item.name, 'Dosa');
      expect(second.totalQuantity, 3);
      expect(second.outlet?.id, 'o1');
    });

    test('restore is what populates it — not a later screen visiting it',
        () async {
      SharedPreferences.setMockInitialValues({});
      final writer = CartState();
      writer.setOutlet(_outlet());
      writer.addItem(_item(id: 'i1', name: 'Idli', price: 50));
      await writer.flush();

      final reader = CartState();
      // Before restore, empty. After restore, populated. No screen involved.
      expect(reader.isEmpty, isTrue);
      await reader.restore();
      expect(reader.isEmpty, isFalse);
      expect(reader.restored, isTrue);
    });

    test('syncFromDisk adopts a change made after startup (app resume)',
        () async {
      SharedPreferences.setMockInitialValues({});
      final onScreen = CartState();
      await onScreen.restore();
      expect(onScreen.isEmpty, isTrue);

      // Something else writes the cart while this instance is idle.
      final other = CartState();
      other.setOutlet(_outlet());
      other.addItem(_item(id: 'i1', name: 'Vada', price: 40), quantity: 2);
      await other.flush();

      // The resume hook.
      await onScreen.syncFromDisk();

      expect(onScreen.items, hasLength(1),
          reason: 'resume must re-read, not trust the startup snapshot');
      expect(onScreen.totalQuantity, 2);
    });

    test('syncFromDisk notifies, so a watching screen rebuilds', () async {
      SharedPreferences.setMockInitialValues({});
      final cart = CartState();
      await cart.restore();

      var notifications = 0;
      cart.addListener(() => notifications++);
      await cart.syncFromDisk();

      expect(notifications, greaterThan(0));
    });

    test('an emptied cart stays emptied across a sync', () async {
      SharedPreferences.setMockInitialValues({});
      final cart = CartState();
      cart.setOutlet(_outlet());
      cart.addItem(_item(id: 'i1', name: 'Pongal', price: 60));
      await cart.flush();

      cart.clear();
      await cart.flush();
      await cart.syncFromDisk();

      expect(cart.isEmpty, isTrue,
          reason: 'a cleared cart must not be resurrected by the resume read');
    });

    test('writes are ordered — the last mutation is the one that persists',
        () async {
      SharedPreferences.setMockInitialValues({});
      final cart = CartState();
      cart.setOutlet(_outlet());
      // Three writes queued in the same synchronous run.
      cart.addItem(_item(id: 'i1', name: 'A', price: 10));
      cart.addItem(_item(id: 'i2', name: 'B', price: 10));
      cart.addItem(_item(id: 'i3', name: 'C', price: 10));
      await cart.flush();

      final reloaded = CartState();
      await reloaded.restore();
      expect(reloaded.items, hasLength(3),
          reason: 'a queued write must not clobber a later one');
    });
  });

  // =========================================================================
  // F — location permission re-check on resume
  // =========================================================================
  group('F: permission changes are noticed without an app restart', () {
    late _FakeGeolocator fake;

    setUp(() {
      fake = _FakeGeolocator();
      GeolocatorPlatform.instance = fake;
    });

    test('refreshPermission picks up a grant made in system settings',
        () async {
      fake.permission = LocationPermission.denied;
      final service = LocationService();
      await service.refreshPermission();
      expect(service.hasPermission, isFalse);

      // The customer leaves, flips the switch in Settings, comes back.
      fake.permission = LocationPermission.whileInUse;
      await service.refreshPermission();

      expect(service.hasPermission, isTrue,
          reason: 'an OS-side grant must apply on resume, not next launch');
    });

    test('refreshPermission picks up a revocation too', () async {
      fake.permission = LocationPermission.whileInUse;
      final service = LocationService();
      await service.refreshPermission();
      expect(service.hasPermission, isTrue);

      fake.permission = LocationPermission.denied;
      await service.refreshPermission();
      expect(service.hasPermission, isFalse);
    });

    test('refreshPermission never raises a dialog', () async {
      fake.permission = LocationPermission.denied;
      final service = LocationService();
      await service.refreshPermission();
      await service.refreshPermission();

      expect(fake.requestCount, 0,
          reason: 'returning to the foreground must never prompt');
    });

    test('it notifies listeners only when the answer actually changed',
        () async {
      fake.permission = LocationPermission.denied;
      final service = LocationService();
      await service.refreshPermission();

      var notified = 0;
      service.addListener(() => notified++);

      await service.refreshPermission(); // unchanged
      expect(notified, 0);

      fake.permission = LocationPermission.whileInUse;
      await service.refreshPermission(); // changed
      expect(notified, 1);
    });

    test('"Ask every time": a lapsed one-time grant re-prompts next attempt',
        () async {
      // Android's ONE_TIME grant reads as whileInUse, then reverts to denied
      // once it lapses. The old session-long latch made the next attempt a
      // silent no — this is that exact sequence.
      fake.permission = LocationPermission.denied;
      fake.grantOnRequest = LocationPermission.whileInUse;
      final service = LocationService();

      final first = await service.getCurrentLocation();
      expect(first.outcome, LocationOutcome.granted);
      expect(fake.requestCount, 1);

      // Grant lapses while backgrounded; the app resumes and re-reads.
      fake.permission = LocationPermission.denied;
      await service.refreshPermission();

      // Next order attempt must ASK again rather than fail silently.
      await service.getCurrentLocation();
      expect(fake.requestCount, 2,
          reason: 'a lapsed one-time grant must re-prompt, not silently deny');
    });

    test('a permanent denial is never re-asked, and reports itself as blocked',
        () async {
      fake.permission = LocationPermission.deniedForever;
      final service = LocationService();

      final result = await service.getCurrentLocation();

      expect(result.outcome, LocationOutcome.deniedForever);
      expect(result.isRefusal, isTrue);
      expect(service.isBlocked, isTrue);
      expect(fake.requestCount, 0,
          reason: 'the OS suppresses that dialog; asking is a no-op wait');
    });

    test('"Don\'t allow" is respected — no position is read', () async {
      fake.permission = LocationPermission.denied;
      fake.grantOnRequest = LocationPermission.denied;
      final service = LocationService();

      final result = await service.getCurrentLocation();

      expect(result.outcome, LocationOutcome.denied);
      expect(result.hasCoordinates, isFalse);
      expect(fake.positionCount, 0,
          reason: 'a refusal must not be followed by a position read');
    });

    test('an automatic caller can never be the one that prompts', () async {
      fake.permission = LocationPermission.denied;
      final service = LocationService();

      await service.getCurrentLocation(allowPrompt: false);

      expect(fake.requestCount, 0);
    });
  });

  // =========================================================================
  // H — login field routing
  // =========================================================================
  // REMOVED — the email/phone auto-detect it covered was deliberately removed on
  // 2026-08-25. Replaced by test/login_redesign_test.dart.

  group('Home is the landing screen, and Discover is behind a CTA', () {
    Widget homeHost(List<Map<String, dynamic>> orders, {LocationService? loc}) {
      final api = _client((req) async {
        if (req.url.path.endsWith('/customer/orders')) return _json(orders);
        if (req.url.path.endsWith('/customer/me')) {
          return _json({'id': 'c1', 'name': 'Asha', 'phone_number': '+919876543210'});
        }
        return _json(const {});
      });
      final otp = StubOtpService(api);
      final google = GoogleAuthService(api);
      return MultiProvider(
        providers: [
          Provider<ApiClient>.value(value: api),
          Provider<CustomerService>(create: (_) => CustomerService(api)),
          Provider<CatalogService>(create: (_) => CatalogService(api)),
          Provider<OrderService>(create: (_) => OrderService(api)),
          ChangeNotifierProvider<LocationService>(
              create: (_) => loc ?? LocationService()),
          ChangeNotifierProvider<CartState>(create: (_) => CartState()),
          ChangeNotifierProvider<ThemeProvider>(create: (_) => ThemeProvider()),
          ChangeNotifierProvider<AuthState>(
            create: (_) => AuthState(api, otp, google, PushService(api)),
          ),
        ],
        child: MaterialApp(
          theme: AppTheme.light(),
          home: const HomeScreen(),
        ),
      );
    }

    Map<String, dynamic> order(String status) => {
          'order_id': 'o1',
          'status': status,
          'outlet_name': 'Test Kitchen',
          'payment_status': 'PAID',
          'total_amount': 220,
          'discount_amount': 0,
          'created_at': DateTime.now().toIso8601String(),
          'pickup_code': '4821',
          'items': [
            {'name': 'Dosa', 'quantity': 1}
          ],
        };

    testWidgets('a first-time customer gets the first-run screen',
        (tester) async {
      _sizeSurface(tester);
      await tester.pumpWidget(homeHost(const []));
      await tester.pump(const Duration(milliseconds: 600));

      expect(find.byKey(const Key('home_first_run')), findsOneWidget);
      // It explains the product rather than showing blanked-out sections.
      expect(find.text('Pick a restaurant'), findsOneWidget);
      expect(find.text('Show your code'), findsOneWidget);
      // No status furniture whose only content is absence.
      expect(find.byKey(const Key('home_history_shortcut')), findsNothing);
      expect(find.text('In progress'), findsNothing);
    });

    testWidgets('a returning customer gets the status board instead',
        (tester) async {
      _sizeSurface(tester);
      await tester.pumpWidget(homeHost([order('COMPLETED')]));
      await tester.pump(const Duration(milliseconds: 600));

      expect(find.byKey(const Key('home_first_run')), findsNothing);
      expect(find.byKey(const Key('home_history_shortcut')), findsOneWidget);
      // Distinct layout, not the same one with empty states.
      expect(find.text('Pick a restaurant'), findsNothing);
    });

    testWidgets('an active order is surfaced on Home as a compact LINK',
        (tester) async {
      // Changed 2026-08-24: Home used to render the full ticket card, pickup
      // code and all. Those cards took most of the first screen, so they were
      // replaced by a one-line link into Order History. Home now says an order
      // EXISTS; the pickup screen remains where the code is read.
      _sizeSurface(tester);
      await tester.pumpWidget(homeHost([order('READY')]));
      await tester.pump(const Duration(milliseconds: 600));

      expect(find.byKey(const Key('home_active_orders_link')), findsOneWidget);
      expect(find.text('1 order in progress'), findsOneWidget);
      expect(find.text('View order history'), findsOneWidget);

      // The big ticket card and its code are deliberately NOT on Home.
      expect(find.byKey(const Key('active_order_code_o1')), findsNothing);
      expect(find.text('4821'), findsNothing);
    });

    testWidgets('both variants carry the Discover CTA', (tester) async {
      _sizeSurface(tester);
      await tester.pumpWidget(homeHost(const []));
      await tester.pump(const Duration(milliseconds: 600));
      expect(find.byKey(const Key('home_find_restaurants')), findsOneWidget);

      await tester.pumpWidget(homeHost([order('COMPLETED')]));
      await tester.pump(const Duration(milliseconds: 600));
      expect(find.byKey(const Key('home_find_restaurants')), findsOneWidget);
    });

    testWidgets('Home NEVER touches location — no read, no prompt',
        (tester) async {
      _sizeSurface(tester);
      final fake = _FakeGeolocator()..permission = LocationPermission.denied;
      GeolocatorPlatform.instance = fake;

      await tester.pumpWidget(homeHost([order('READY')]));
      await tester.pump(const Duration(milliseconds: 600));

      expect(fake.requestCount, 0,
          reason: 'landing on Home must not raise a permission dialog');
      expect(fake.positionCount, 0,
          reason: 'Home has nothing to render from coordinates');
    });

    testWidgets('a failed orders lookup does NOT masquerade as a first run',
        (tester) async {
      _sizeSurface(tester);
      final api = _client((req) async {
        if (req.url.path.endsWith('/customer/orders')) {
          return _json({'detail': 'upstream is down'}, status: 500);
        }
        return _json(const {});
      });
      final otp = StubOtpService(api);
      await tester.pumpWidget(MultiProvider(
        providers: [
          Provider<ApiClient>.value(value: api),
          Provider<CustomerService>(create: (_) => CustomerService(api)),
          ChangeNotifierProvider<LocationService>(
              create: (_) => LocationService()),
          ChangeNotifierProvider<CartState>(create: (_) => CartState()),
          ChangeNotifierProvider<ThemeProvider>(create: (_) => ThemeProvider()),
          ChangeNotifierProvider<AuthState>(
            create: (_) =>
                AuthState(api, otp, GoogleAuthService(api), PushService(api)),
          ),
        ],
        child: MaterialApp(
          theme: AppTheme.light(),
          home: const HomeScreen(),
        ),
      ));
      await tester.pump(const Duration(milliseconds: 600));

      // Telling a regular customer their history vanished would be worse than
      // the error itself.
      expect(find.byKey(const Key('home_first_run')), findsNothing);
    });
  });

  // =========================================================================
  // NAME — mandatory name on new signup (2026-08-24 follow-up)
  // =========================================================================
  // REMOVED — the name field on login screen it covered was deliberately removed on
  // 2026-08-25. Replaced by test/login_redesign_test.dart.

  // REMOVED — this group drove AuthState.setPendingName/_applyPendingName,
  // the guard that was deleted on 2026-08-25 when name capture moved to a
  // post-signup screen. Replaced by the 'pending-name guard was removed'
  // group in test/login_redesign_test.dart.

  // REMOVED — the Home blocking gate it covered was deliberately removed on
  // 2026-08-25. Replaced by test/login_redesign_test.dart.

  group('BADGE: is_open is a known-fake signal and must not be displayed', () {
    Map<String, dynamic> outlet({
      required String id,
      bool isOpen = true,
    }) =>
        {
          'id': id,
          'name': 'Test Kitchen',
          'address': 'Koramangala, Bengaluru',
          'is_open': isOpen,
          'distance_km': 1.2,
          'latitude': 12.9352,
          'longitude': 77.6245,
        };

    Widget host(List<Map<String, dynamic>> outlets) {
      final api = _client((req) async {
        if (req.url.path.contains('/customer/orders')) return _json(const []);
        if (req.url.path.contains('/customer/outlets')) return _json(outlets);
        if (req.url.path.contains('/customer/menu')) {
          return _json({'categories': const []});
        }
        return _json(const []);
      });
      return MultiProvider(
        providers: [
          Provider<ApiClient>.value(value: api),
          Provider<CatalogService>(create: (_) => CatalogService(api)),
          Provider<CustomerService>(create: (_) => CustomerService(api)),
          // MenuScreen (which a tap navigates to) reads CartState in
          // initState to bind the outlet — needed even though the last test
          // in this group is the only one that actually navigates.
          ChangeNotifierProvider<CartState>(create: (_) => CartState()),
          ChangeNotifierProvider<ThemeProvider>(create: (_) => ThemeProvider()),
        ],
        child: MaterialApp(theme: AppTheme.light(), home: const OutletsScreen()),
      );
    }

    testWidgets('no OPEN or CLOSED text renders on the outlet list',
        (tester) async {
      _sizeSurface(tester);
      await tester
          .pumpWidget(host([outlet(id: 'a', isOpen: true)]));
      await tester.pump(const Duration(milliseconds: 600));

      expect(find.text('OPEN'), findsNothing);
      expect(find.text('CLOSED'), findsNothing);
    });

    testWidgets('the "Open now" filter chip does not exist', (tester) async {
      _sizeSurface(tester);
      await tester.pumpWidget(host([outlet(id: 'a')]));
      await tester.pump(const Duration(milliseconds: 600));

      expect(find.byKey(const Key('chip_open')), findsNothing);
      expect(find.text('Open now'), findsNothing);
      // The rest of the controls are still there — this is a removal, not a
      // wholesale breakage of the filter row. The sort options moved behind
      // the filter button (2026-08-25), so their presence is asserted through
      // it rather than on the screen directly.
      expect(find.byKey(const Key('filter_button')), findsOneWidget);
      expect(find.byKey(const Key('chip_offers')), findsOneWidget);
    });

    testWidgets('the card stays tappable even when is_open is false',
        (tester) async {
      _sizeSurface(tester);
      // Fed a false value on purpose: the client must not reintroduce a gate
      // on this field even if the server ever sends one.
      await tester.pumpWidget(host([outlet(id: 'a', isOpen: false)]));
      await tester.pump(const Duration(milliseconds: 600));

      expect(find.text('Unavailable'), findsNothing);
      expect(find.byKey(const Key('outlet_card_a')), findsOneWidget);

      await tester.tap(find.byKey(const Key('outlet_card_a')));
      await tester.pumpAndSettle();

      expect(find.byType(MenuScreen), findsOneWidget,
          reason: 'tapping must still navigate — nothing may gate on '
              'is_open any more');
    });
  });
}

// ---------------------------------------------------------------------------
// A scripted geolocator, so permission transitions can be driven exactly.
// ---------------------------------------------------------------------------
class _FakeGeolocator extends GeolocatorPlatform {
  LocationPermission permission = LocationPermission.denied;

  /// What the OS dialog answers when raised.
  LocationPermission grantOnRequest = LocationPermission.whileInUse;

  bool serviceEnabled = true;

  int requestCount = 0;
  int positionCount = 0;

  @override
  Future<LocationPermission> checkPermission() async => permission;

  @override
  Future<LocationPermission> requestPermission() async {
    requestCount++;
    permission = grantOnRequest;
    return permission;
  }

  @override
  Future<bool> isLocationServiceEnabled() async => serviceEnabled;

  @override
  Future<Position> getCurrentPosition({LocationSettings? locationSettings}) async {
    positionCount++;
    return Position(
      latitude: 12.97,
      longitude: 77.59,
      timestamp: DateTime.now(),
      accuracy: 10,
      altitude: 0,
      altitudeAccuracy: 0,
      heading: 0,
      headingAccuracy: 0,
      speed: 0,
      speedAccuracy: 0,
    );
  }
}
