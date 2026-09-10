// Location permission must be re-checked AND re-prompted on every deliberate
// tap, not once per session.
//
// The bug: LocationService gated its prompt on a `_prompted` latch that was
// only cleared by `_syncPermission`, which returns early when the OS status has
// not moved. After one denial the status stays `denied`, so the latch stayed
// set and every later tap fell through to a silent refusal — the dialog was
// suppressed by the app, not by the OS. Both "Near me" (Discover) and the
// "Nearest" sort chip went through that same shared app-wide service.
//
// Covered here, for all THREE entry points, in all three permission states:
// (the radius toggle joined them when Near Me / Travel began needing an origin
// of their own — without this it silently sent no radius while the chip lit up
// and the label claimed "within 65 km" over an unfiltered list)
//   granted           -> proceed, no dialog
//   denied (askable)  -> raise the OS dialog, EVERY time
//   deniedForever     -> never raise the OS dialog; show the in-app
//                        explanation with a working Settings hand-off
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
import 'package:customer_app/screens/checkout_screen.dart';
import 'package:customer_app/screens/location_screen.dart';
import 'package:customer_app/screens/outlets_screen.dart';
import 'package:customer_app/services/api_client.dart';
import 'package:customer_app/services/catalog_service.dart';
import 'package:customer_app/services/customer_service.dart';
import 'package:customer_app/services/location_service.dart';
import 'package:customer_app/services/order_service.dart';
import 'package:customer_app/services/places_service.dart';
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

/// Outlets deliberately carry NO distance_km, so the Nearest chip cannot short
/// -circuit on "the list already has distances" and must go to the service.
Map<String, dynamic> _outletJson(String id) => {
      'id': id,
      'name': 'Kitchen $id',
      'address': 'Somewhere',
      'is_open': true,
      'distance_km': null,
    };

ApiClient _api() {
  SharedPreferences.setMockInitialValues({'carevo_access_token': 'valid'});
  return ApiClient(client: MockClient((req) async {
    if (req.url.path.contains('/customer/orders')) return _json(const []);
    if (req.url.path.contains('/customer/outlets')) {
      return _json([_outletJson('a'), _outletJson('b')]);
    }
    if (req.url.path.contains('/customer/areas')) {
      return _json([
        {'city': 'Bengaluru', 'outlet_count': 2},
      ]);
    }
    return _json(const []);
  }));
}

Widget _host(Widget home, LocationService loc) {
  final api = _api();
  return MultiProvider(
    providers: [
      Provider<ApiClient>.value(value: api),
      Provider<CatalogService>(create: (_) => CatalogService(api)),
      Provider<CustomerService>(create: (_) => CustomerService(api)),
      ChangeNotifierProvider<LocationService>.value(value: loc),
      ChangeNotifierProvider<CartState>(create: (_) => CartState()),
      ChangeNotifierProvider<ThemeProvider>(create: (_) => ThemeProvider()),
    ],
    child: MaterialApp(theme: AppTheme.light(), home: home),
  );
}

/// Checkout needs a bound cart to render, plus the services its build reads.
/// Nothing here exercises payment — only the origin picker.
Widget _checkoutHost(LocationService loc) {
  final api = _api();
  SharedPreferences.setMockInitialValues({});
  final cart = CartState();
  cart.setOutlet(Outlet.fromJson(_outletJson('a')));
  cart.addItem(
    MenuItem.fromJson({
      'id': 'i1',
      'name': 'Dosa',
      'base_price': 90,
      'is_veg': true,
      'is_available': true,
      'customizations': const [],
    }),
  );

  return MultiProvider(
    providers: [
      Provider<ApiClient>.value(value: api),
      Provider<CatalogService>(create: (_) => CatalogService(api)),
      Provider<CustomerService>(create: (_) => CustomerService(api)),
      Provider<OrderService>(create: (_) => OrderService(api)),
      Provider<PlacesService>(create: (_) => PlacesService()),
      ChangeNotifierProvider<LocationService>.value(value: loc),
      ChangeNotifierProvider<CartState>.value(value: cart),
      ChangeNotifierProvider<ThemeProvider>(create: (_) => ThemeProvider()),
    ],
    child: MaterialApp(theme: AppTheme.light(), home: const CheckoutScreen()),
  );
}

/// Taps "Near me" on Discover.
Future<void> tapNearMe(WidgetTester tester) async {
  await tester.tap(find.byKey(const Key('use_my_location')));
  await tester.pump();
  await tester.pump(const Duration(milliseconds: 400));
}

/// Picks the Nearest sort on the outlet list.
///
/// Two taps since the sort bar was collapsed: open the filter sheet, then
/// choose the option. The sheet closes itself on selection.
Future<void> tapNearestSort(WidgetTester tester) async {
  await tester.tap(find.byKey(const Key('filter_button')));
  await tester.pumpAndSettle();
  await tester.tap(find.byKey(const Key('sort_nearest')));
  await tester.pump();
  await tester.pump(const Duration(milliseconds: 400));
}

void main() {
  late _FakeGeolocator fake;
  late LocationService service;

  setUp(() {
    fake = _FakeGeolocator();
    GeolocatorPlatform.instance = fake;
    service = LocationService();
  });

  // =========================================================================
  // Service-level: the latch must not swallow a deliberate re-ask
  // =========================================================================
  group('service: a user-initiated call re-prompts every time', () {
    test('two consecutive denials raise the OS dialog TWICE', () async {
      fake.permission = LocationPermission.denied;
      fake.grantOnRequest = LocationPermission.denied; // user says no, twice

      final first = await service.getCurrentLocation(userInitiated: true);
      expect(first.outcome, LocationOutcome.denied);
      expect(fake.requestCount, 1);

      // THE REGRESSION. The status has not moved, so `_syncPermission` returns
      // early and never clears `_prompted`; before the fix this second call
      // returned a silent refusal without ever reaching the OS.
      final second = await service.getCurrentLocation(userInitiated: true);
      expect(second.outcome, LocationOutcome.denied);
      expect(fake.requestCount, 2,
          reason: 'a deliberate second tap must reach the OS dialog again');
    });

    test('a third and fourth tap keep asking — the latch never re-arms',
        () async {
      fake.permission = LocationPermission.denied;
      fake.grantOnRequest = LocationPermission.denied;

      for (var i = 1; i <= 4; i++) {
        await service.getCurrentLocation(userInitiated: true);
        expect(fake.requestCount, i);
      }
    });

    test('a denial that later becomes a grant proceeds normally', () async {
      fake.permission = LocationPermission.denied;
      fake.grantOnRequest = LocationPermission.denied;
      await service.getCurrentLocation(userInitiated: true);

      // Customer relents on the second ask.
      fake.grantOnRequest = LocationPermission.whileInUse;
      final result = await service.getCurrentLocation(userInitiated: true);

      expect(result.outcome, LocationOutcome.granted);
      expect(result.hasCoordinates, isTrue);
      expect(fake.requestCount, 2);
    });

    test('deniedForever is NEVER re-asked, however deliberate the tap',
        () async {
      fake.permission = LocationPermission.deniedForever;

      for (var i = 0; i < 3; i++) {
        final r = await service.getCurrentLocation(userInitiated: true);
        expect(r.outcome, LocationOutcome.deniedForever);
      }
      expect(fake.requestCount, 0,
          reason: 'the OS suppresses that dialog; calling it is a no-op wait');
      expect(service.isBlocked, isTrue);
    });

    test('an incidental caller still asks only once per grant state', () async {
      // The latch was added for these and must keep working — the fix narrows
      // it to non-user-initiated callers rather than deleting it.
      fake.permission = LocationPermission.denied;
      fake.grantOnRequest = LocationPermission.denied;

      await service.getCurrentLocation();
      await service.getCurrentLocation();

      expect(fake.requestCount, 1,
          reason: 'the default path must not start double-prompting');
    });

    test('an automatic caller still never prompts at all', () async {
      fake.permission = LocationPermission.denied;
      await service.getCurrentLocation(allowPrompt: false);
      expect(fake.requestCount, 0);
    });

    test('the status is re-read from the OS on every call', () async {
      fake.permission = LocationPermission.denied;
      fake.grantOnRequest = LocationPermission.denied;
      await service.getCurrentLocation(userInitiated: true);
      expect(service.hasPermission, isFalse);

      // Granted in system settings while the app sat there.
      fake.permission = LocationPermission.whileInUse;
      final r = await service.getCurrentLocation(userInitiated: true);

      expect(r.outcome, LocationOutcome.granted);
      expect(fake.requestCount, 1,
          reason: 'already granted — there is nothing to ask for');
    });
  });

  // =========================================================================
  // "Near me" on Discover
  // =========================================================================
  group('Near me: all three states', () {
    testWidgets('granted -> proceeds to the outlet list', (tester) async {
      _sizeSurface(tester);
      fake.permission = LocationPermission.whileInUse;
      await tester.pumpWidget(_host(const LocationScreen(), service));
      await tester.pump(const Duration(milliseconds: 400));

      await tapNearMe(tester);
      await tester.pumpAndSettle();

      expect(find.byType(OutletsScreen), findsOneWidget);
      expect(find.byKey(const Key('location_blocked_dialog')), findsNothing);
    });

    testWidgets('denied -> prompts, and RE-PROMPTS on the second tap',
        (tester) async {
      _sizeSurface(tester);
      fake.permission = LocationPermission.denied;
      fake.grantOnRequest = LocationPermission.denied;
      await tester.pumpWidget(_host(const LocationScreen(), service));
      await tester.pump(const Duration(milliseconds: 400));

      await tapNearMe(tester);
      expect(fake.requestCount, 1);

      await tapNearMe(tester);
      expect(fake.requestCount, 2,
          reason: 'tapping Near me again must ask again, not fail silently');

      // A plain denial stays on a SnackBar — it is momentary and the customer
      // just made the choice deliberately.
      expect(find.byKey(const Key('location_blocked_dialog')), findsNothing);
    });

    testWidgets('deniedForever -> no OS dialog, shows the explanation instead',
        (tester) async {
      _sizeSurface(tester);
      fake.permission = LocationPermission.deniedForever;
      await tester.pumpWidget(_host(const LocationScreen(), service));
      await tester.pump(const Duration(milliseconds: 400));

      await tapNearMe(tester);
      await tester.pumpAndSettle();

      expect(fake.requestCount, 0,
          reason: 'the OS blocks this dialog regardless of app code');
      expect(find.byKey(const Key('location_blocked_dialog')), findsOneWidget);
      expect(find.textContaining('find restaurants near you'), findsOneWidget);
    });

    testWidgets('the explanation opens the device settings page',
        (tester) async {
      _sizeSurface(tester);
      fake.permission = LocationPermission.deniedForever;
      await tester.pumpWidget(_host(const LocationScreen(), service));
      await tester.pump(const Duration(milliseconds: 400));

      await tapNearMe(tester);
      await tester.pumpAndSettle();
      await tester.tap(find.byKey(const Key('location_blocked_open_settings')));
      await tester.pumpAndSettle();

      expect(fake.openAppSettingsCount, 1,
          reason: 'the only control that can fix a permanent denial');
      expect(find.byKey(const Key('location_blocked_dialog')), findsNothing,
          reason: 'dialog closes so settings does not come back to a modal');
    });

    testWidgets('the explanation can be dismissed without leaving the app',
        (tester) async {
      _sizeSurface(tester);
      fake.permission = LocationPermission.deniedForever;
      await tester.pumpWidget(_host(const LocationScreen(), service));
      await tester.pump(const Duration(milliseconds: 400));

      await tapNearMe(tester);
      await tester.pumpAndSettle();
      await tester.tap(find.byKey(const Key('location_blocked_dismiss')));
      await tester.pumpAndSettle();

      expect(fake.openAppSettingsCount, 0);
      expect(find.byType(LocationScreen), findsOneWidget,
          reason: 'the city picker is still a complete alternative');
    });
  });

  // =========================================================================
  // "Nearest" sort on the outlet list
  // =========================================================================
  group('Nearest sort: all three states', () {
    Widget outlets() => _host(const OutletsScreen(), service);

    testWidgets('granted -> acquires the origin and re-fetches', (tester) async {
      _sizeSurface(tester);
      fake.permission = LocationPermission.whileInUse;
      await tester.pumpWidget(outlets());
      await tester.pump(const Duration(milliseconds: 600));

      await tapNearestSort(tester);
      await tester.pump(const Duration(milliseconds: 600));

      expect(fake.positionCount, greaterThan(0));
      expect(find.byKey(const Key('location_blocked_dialog')), findsNothing);
    });

    testWidgets('denied -> prompts, and RE-PROMPTS on the second tap',
        (tester) async {
      _sizeSurface(tester);
      fake.permission = LocationPermission.denied;
      fake.grantOnRequest = LocationPermission.denied;
      await tester.pumpWidget(outlets());
      await tester.pump(const Duration(milliseconds: 600));

      await tapNearestSort(tester);
      expect(fake.requestCount, 1);

      await tapNearestSort(tester);
      expect(fake.requestCount, 2,
          reason: 'the Nearest chip must ask again on a second press');
    });

    testWidgets('deniedForever -> no OS dialog, shows the explanation instead',
        (tester) async {
      _sizeSurface(tester);
      fake.permission = LocationPermission.deniedForever;
      await tester.pumpWidget(outlets());
      await tester.pump(const Duration(milliseconds: 600));

      await tapNearestSort(tester);
      await tester.pumpAndSettle();

      expect(fake.requestCount, 0);
      expect(find.byKey(const Key('location_blocked_dialog')), findsOneWidget);
      expect(find.textContaining('sort restaurants by how close'),
          findsOneWidget);
    });

    testWidgets('its explanation also opens the device settings page',
        (tester) async {
      _sizeSurface(tester);
      fake.permission = LocationPermission.deniedForever;
      await tester.pumpWidget(outlets());
      await tester.pump(const Duration(milliseconds: 600));

      await tapNearestSort(tester);
      await tester.pumpAndSettle();
      await tester.tap(find.byKey(const Key('location_blocked_open_settings')));
      await tester.pumpAndSettle();

      expect(fake.openAppSettingsCount, 1);
    });
  });

  // =========================================================================
  // Near Me / Travel radius chips on the outlet list
  //
  // A radius needs an ORIGIN, so these go through the same dance. The extra
  // thing pinned here, which the other entry points cannot express: the
  // chip must not LOOK selected unless the radius was actually applied.
  // =========================================================================
  group('radius toggle: all three states', () {
    Widget outlets() => _host(const OutletsScreen(), service);

    Future<void> tapNearMe(WidgetTester tester) async {
      final target = find.byKey(const Key('radius_near_me'));
      await tester.ensureVisible(target);
      await tester.pump();
      await tester.tap(target);
      await tester.pump(const Duration(milliseconds: 600));
    }

    testWidgets('with no origin the chips start UNSELECTED', (tester) async {
      // The honesty case. Defaulting to Near Me here would light the chip and
      // render "within 65 km" over a list no radius was ever applied to.
      _sizeSurface(tester);
      fake.permission = LocationPermission.denied;
      await tester.pumpWidget(outlets());
      await tester.pump(const Duration(milliseconds: 600));

      expect(find.textContaining('within'), findsNothing,
          reason: 'no origin means no radius, so nothing may claim one');
    });

    testWidgets('granted -> acquires the origin and applies the radius',
        (tester) async {
      _sizeSurface(tester);
      fake.permission = LocationPermission.whileInUse;
      await tester.pumpWidget(outlets());
      await tester.pump(const Duration(milliseconds: 600));

      await tapNearMe(tester);
      await tester.pump(const Duration(milliseconds: 600));

      expect(fake.positionCount, greaterThan(0));
      expect(find.byKey(const Key('location_blocked_dialog')), findsNothing);
      expect(find.text('within 65 km'), findsOneWidget,
          reason: 'once the origin lands the chip may claim its radius');
    });

    testWidgets('denied -> prompts, RE-PROMPTS, and stays unselected',
        (tester) async {
      _sizeSurface(tester);
      fake.permission = LocationPermission.denied;
      fake.grantOnRequest = LocationPermission.denied;
      await tester.pumpWidget(outlets());
      await tester.pump(const Duration(milliseconds: 600));

      await tapNearMe(tester);
      expect(fake.requestCount, 1);

      await tapNearMe(tester);
      expect(fake.requestCount, 2,
          reason: 'a radius chip must ask again on a second press');

      await tester.pump(const Duration(milliseconds: 600));
      expect(find.textContaining('within'), findsNothing,
          reason: 'a refused radius must not show as applied');
    });

    testWidgets('deniedForever -> no OS dialog, shows the explanation instead',
        (tester) async {
      _sizeSurface(tester);
      fake.permission = LocationPermission.deniedForever;
      await tester.pumpWidget(outlets());
      await tester.pump(const Duration(milliseconds: 600));

      await tapNearMe(tester);
      await tester.pumpAndSettle();

      expect(fake.requestCount, 0);
      expect(find.byKey(const Key('location_blocked_dialog')), findsOneWidget);
      expect(find.textContaining('within a distance of you'), findsOneWidget,
          reason: 'the dialog should name THIS purpose, not the sort one');
    });

  });

  // =========================================================================
  // =========================================================================
  // Checkout: the transport chip is the ONLY location control
  //
  // The standalone "Your starting point" card and its Use-GPS / Search-address
  // buttons were removed. A first tap on a chip resolves the origin; a RE-TAP
  // on the already-selected chip is the retry, and is the only way left to
  // force a fresh prompt.
  // =========================================================================
  group('checkout: the chip is the only location control', () {
    testWidgets('the standalone starting-point control is gone',
        (tester) async {
      _sizeSurface(tester);
      fake.permission = LocationPermission.whileInUse;
      await tester.pumpWidget(_checkoutHost(service));
      await tester.pump(const Duration(milliseconds: 400));

      expect(find.byKey(const Key('checkout_use_gps')), findsNothing,
          reason: 'the Use GPS button was removed with the card');
      expect(find.text('Your starting point'), findsNothing);
      expect(find.text('Search address'), findsNothing);
      // What replaced it is a status line, not a control.
      expect(find.byKey(const Key('checkout_origin_status')), findsOneWidget);
    });

    testWidgets('granted -> a chip tap fills the origin, no dialog',
        (tester) async {
      _sizeSurface(tester);
      fake.permission = LocationPermission.whileInUse;
      await tester.pumpWidget(_checkoutHost(service));
      await tester.pump(const Duration(milliseconds: 400));

      await tapMode(tester, 'Car');

      expect(fake.requestCount, 0, reason: 'already granted - nothing to ask');
      expect(fake.positionCount, 1);
      expect(find.text('Current location'), findsOneWidget);
      expect(find.byKey(const Key('location_blocked_dialog')), findsNothing);
    });

    testWidgets('RE-TAPPING the selected chip retries and re-prompts',
        (tester) async {
      // The retry gesture. With no Use-GPS button left, this is the only way to
      // force the OS dialog after a refusal - and it must bypass the
      // one-prompt latch or it would be a dead control.
      _sizeSurface(tester);
      fake.permission = LocationPermission.denied;
      fake.grantOnRequest = LocationPermission.denied;
      await tester.pumpWidget(_checkoutHost(service));
      await tester.pump(const Duration(milliseconds: 400));

      await tapMode(tester, 'Car');
      expect(fake.requestCount, 1, reason: 'first tap asks once');

      await tapMode(tester, 'Car');
      expect(fake.requestCount, 2,
          reason: 'a re-tap on the SELECTED chip must reach the OS dialog again');

      await tapMode(tester, 'Car');
      expect(fake.requestCount, 3, reason: 'and again - it is a retry control');
    });

    testWidgets('a re-tap re-fetches even when an origin already exists',
        (tester) async {
      // Distinct from switching chips, which must NOT clobber a good origin.
      _sizeSurface(tester);
      fake.permission = LocationPermission.whileInUse;
      await tester.pumpWidget(_checkoutHost(service));
      await tester.pump(const Duration(milliseconds: 400));

      await tapMode(tester, 'Car');
      expect(fake.positionCount, 1);

      await tapMode(tester, 'Bus');
      expect(fake.positionCount, 1,
          reason: 'switching mode must not re-read a good origin');

      await tapMode(tester, 'Bus');
      expect(fake.positionCount, 2,
          reason: 're-tapping the SELECTED chip is a deliberate refresh');
    });

    testWidgets('already deniedForever -> a deliberate tap explains',
        (tester) async {
      // Arriving with permission already permanently denied. The OS will never
      // show its dialog, so a deliberate tap must explain or it is a dead
      // control.
      _sizeSurface(tester);
      fake.permission = LocationPermission.deniedForever;
      await tester.pumpWidget(_checkoutHost(service));
      await tester.pump(const Duration(milliseconds: 400));

      await tapMode(tester, 'Car');
      await tester.pumpAndSettle();

      expect(fake.requestCount, 0, reason: 'deniedForever is never re-asked');
      expect(find.byKey(const Key('location_blocked_dialog')), findsOneWidget);
      expect(find.byKey(const Key('location_blocked_open_settings')),
          findsOneWidget);
    });

    testWidgets('FR-C6: a refusal still leaves checkout payable',
        (tester) async {
      _sizeSurface(tester);
      fake.permission = LocationPermission.denied;
      fake.grantOnRequest = LocationPermission.denied;
      await tester.pumpWidget(_checkoutHost(service));
      await tester.pump(const Duration(milliseconds: 400));

      await tapMode(tester, 'Car');
      await tester.pumpAndSettle();

      // The status line says what happened AND how to retry - without a
      // separate button, a customer with no location needs telling.
      expect(find.byKey(const Key('checkout_origin_status')), findsOneWidget);
      expect(find.textContaining('tap your travel mode again'), findsOneWidget);
      // And the order can still be placed.
      expect(find.textContaining('Pay'), findsWidgets);
    });
  });


  // =========================================================================
  // The decline escalation, as ONE sequence
  //
  // Stage 1  first decline     -> nothing forceful. No dialog, no snackbar.
  //                               The chip stays tappable and a re-tap
  //                               re-prompts.
  // Stage 2  second decline    -> Android flips the status to deniedForever,
  //          (or that status)     and the app explains, with a button that
  //                               opens system settings.
  //
  // The bug this pins: the escalation used to live on the NEXT tap, because
  // _resolveOrigin's result was discarded. Someone who declined twice and
  // stopped tapping was simply never told why location had stopped working.
  // =========================================================================
  group('location decline escalates in two stages', () {
    testWidgets('stage 1: a first decline is silent and stays retryable',
        (tester) async {
      _sizeSurface(tester);
      fake.permission = LocationPermission.denied;
      fake.grantOnRequest = LocationPermission.denied;

      await tester.pumpWidget(_checkoutHost(service));
      await tester.pump(const Duration(milliseconds: 400));

      await tapMode(tester, 'Car');
      await tester.pumpAndSettle();

      expect(fake.requestCount, 1, reason: 'the OS dialog was raised once');
      // Nothing forceful.
      expect(find.byKey(const Key('location_blocked_dialog')), findsNothing);
      expect(find.byType(SnackBar), findsNothing);
      // The chip is still there and still says what it is.
      expect(find.text('Car'), findsOneWidget);
      // And checkout is still payable.
      expect(find.textContaining('Pay'), findsWidgets);
    });

    testWidgets('stage 1 -> a later tap re-prompts normally', (tester) async {
      _sizeSurface(tester);
      fake.permission = LocationPermission.denied;
      fake.grantOnRequest = LocationPermission.denied;

      await tester.pumpWidget(_checkoutHost(service));
      await tester.pump(const Duration(milliseconds: 400));

      await tapMode(tester, 'Car');
      expect(fake.requestCount, 1);

      await tapMode(tester, 'Car');
      await tester.pumpAndSettle();
      expect(fake.requestCount, 2,
          reason: 'a first decline must NOT mute the next deliberate tap');
    });

    testWidgets('stage 2: the SECOND decline explains, immediately',
        (tester) async {
      // The real Android sequence: refuse once -> denied; refuse again -> the
      // OS reports deniedForever. The explanation must land on THAT tap.
      _sizeSurface(tester);
      fake.permission = LocationPermission.denied;
      fake.grantOnRequest = LocationPermission.denied;

      await tester.pumpWidget(_checkoutHost(service));
      await tester.pump(const Duration(milliseconds: 400));

      // First decline - silent.
      await tapMode(tester, 'Car');
      await tester.pumpAndSettle();
      expect(find.byKey(const Key('location_blocked_dialog')), findsNothing);

      // Second decline: this is the one Android makes permanent.
      fake.grantOnRequest = LocationPermission.deniedForever;
      await tapMode(tester, 'Car');
      await tester.pumpAndSettle();

      expect(find.byKey(const Key('location_blocked_dialog')), findsOneWidget,
          reason: 'the escalation must land on the declining tap itself, '
              'not on some later tap the customer may never make');
    });

    testWidgets('stage 2 offers a working route to system settings',
        (tester) async {
      _sizeSurface(tester);
      fake.permission = LocationPermission.denied;
      fake.grantOnRequest = LocationPermission.denied;

      await tester.pumpWidget(_checkoutHost(service));
      await tester.pump(const Duration(milliseconds: 400));

      await tapMode(tester, 'Car');
      await tester.pumpAndSettle();

      fake.grantOnRequest = LocationPermission.deniedForever;
      await tapMode(tester, 'Car');
      await tester.pumpAndSettle();

      final settings = find.byKey(const Key('location_blocked_open_settings'));
      expect(settings, findsOneWidget);
      await tester.tap(settings);
      await tester.pumpAndSettle();

      expect(fake.openAppSettingsCount, 1,
          reason: 'the button must actually reach the OS settings page');
    });

    testWidgets('stage 2 never re-asks the OS', (tester) async {
      _sizeSurface(tester);
      fake.permission = LocationPermission.deniedForever;

      await tester.pumpWidget(_checkoutHost(service));
      await tester.pump(const Duration(milliseconds: 400));

      await tapMode(tester, 'Car');
      await tester.pumpAndSettle();
      await tester.tap(find.byKey(const Key('location_blocked_dismiss')));
      await tester.pumpAndSettle();
      await tapMode(tester, 'Car');
      await tester.pumpAndSettle();

      expect(fake.requestCount, 0,
          reason: 'the OS swallows that dialog - asking would be a no-op wait');
    });
  });

  // =========================================================================
  // All three entry points share one service — they must not silence each other
  // =========================================================================
  group('the entry points do not silence one another', () {
    testWidgets('a Near-me denial does not suppress the Nearest sort prompt',
        (tester) async {
      // LocationService is a single app-wide provider, so the latch was shared:
      // denying on Discover also killed the prompt on the outlet list.
      _sizeSurface(tester);
      fake.permission = LocationPermission.denied;
      fake.grantOnRequest = LocationPermission.denied;

      await tester.pumpWidget(_host(const LocationScreen(), service));
      await tester.pump(const Duration(milliseconds: 400));
      await tapNearMe(tester);
      expect(fake.requestCount, 1);

      // Same service instance, different screen.
      await tester.pumpWidget(_host(const OutletsScreen(), service));
      await tester.pump(const Duration(milliseconds: 600));
      await tapNearestSort(tester);

      expect(fake.requestCount, 2,
          reason: 'a denial on one screen must not mute the other');
    });

    testWidgets('a Near-me denial does not suppress the checkout prompt',
        (tester) async {
      _sizeSurface(tester);
      fake.permission = LocationPermission.denied;
      fake.grantOnRequest = LocationPermission.denied;

      await tester.pumpWidget(_host(const LocationScreen(), service));
      await tester.pump(const Duration(milliseconds: 400));
      await tapNearMe(tester);
      expect(fake.requestCount, 1);

      await tester.pumpWidget(_checkoutHost(service));
      await tester.pump(const Duration(milliseconds: 400));
      await tapMode(tester, 'Car');

      expect(fake.requestCount, 2,
          reason: 'checkout is the third entry point onto the same service');
    });
  });

  // =========================================================================
  // Choosing a transport mode IS the location request
  //
  // "I'm coming by car" already answers "from where?" — so the ask belongs to
  // that tap. Before this, the chip only set a mode and the customer had to
  // find a separate "Use GPS" control further down the page; most did not, and
  // orders arrived carrying a mode with no origin.
  // =========================================================================
  group('transport mode selection carries the location ask', () {
    testWidgets('an existing grant is REUSED — origin fills, no prompt',
        (tester) async {
      _sizeSurface(tester);
      fake.permission = LocationPermission.whileInUse;

      await tester.pumpWidget(_checkoutHost(service));
      await tester.pump(const Duration(milliseconds: 400));
      await tapMode(tester, 'Car');

      expect(fake.requestCount, 0,
          reason: 'permission is already held — nothing to ask for');
      expect(fake.positionCount, 1, reason: 'the grant was used, not re-sought');
      expect(find.text('Current location'), findsOneWidget);
    });

    testWidgets('with no grant yet, the chip tap raises the prompt itself',
        (tester) async {
      _sizeSurface(tester);
      fake.permission = LocationPermission.denied;
      fake.grantOnRequest = LocationPermission.whileInUse;

      await tester.pumpWidget(_checkoutHost(service));
      await tester.pump(const Duration(milliseconds: 400));
      await tapMode(tester, 'Walk');

      expect(fake.requestCount, 1,
          reason: 'the ask is part of selecting a mode, not a separate step');
      expect(find.text('Current location'), findsOneWidget);
    });

    testWidgets('changing mode does NOT ask a second time', (tester) async {
      // The whole complaint: being asked again for something already answered.
      _sizeSurface(tester);
      fake.permission = LocationPermission.denied;
      fake.grantOnRequest = LocationPermission.denied;

      await tester.pumpWidget(_checkoutHost(service));
      await tester.pump(const Duration(milliseconds: 400));

      await tapMode(tester, 'Walk');
      expect(fake.requestCount, 1);

      await tapMode(tester, 'Car');
      await tapMode(tester, 'Auto');
      expect(fake.requestCount, 1,
          reason: 'tapping through chips must not stack OS dialogs');
    });

    testWidgets('a granted origin is not re-fetched by the next chip',
        (tester) async {
      _sizeSurface(tester);
      fake.permission = LocationPermission.whileInUse;

      await tester.pumpWidget(_checkoutHost(service));
      await tester.pump(const Duration(milliseconds: 400));

      await tapMode(tester, 'Car');
      expect(fake.positionCount, 1);

      await tapMode(tester, 'Bus');
      expect(fake.positionCount, 1,
          reason: 'the origin already exists — re-reading GPS buys nothing');
    });

    testWidgets('a blocked permission is never re-asked from a chip',
        (tester) async {
      _sizeSurface(tester);
      fake.permission = LocationPermission.deniedForever;

      await tester.pumpWidget(_checkoutHost(service));
      await tester.pump(const Duration(milliseconds: 400));
      await tapMode(tester, 'Car');
      await tester.pumpAndSettle();

      expect(fake.requestCount, 0);
      // The dialog IS shown now, and that is the point: with the Use-GPS
      // button gone there is no other control to carry the explanation, so a
      // deliberate tap that cannot prompt has to say why or it is dead.
      // A plain switch between chips still shows nothing — see the escalation
      // group, which pins the full two-stage sequence.
      expect(find.byKey(const Key('location_blocked_dialog')), findsOneWidget);
    });

    testWidgets('but a plain chip SWITCH while blocked stays silent',
        (tester) async {
      // The nagging guard: only a deliberate tap (first resolve, or a re-tap)
      // explains. Browsing across chips must not throw a modal each time.
      _sizeSurface(tester);
      fake.permission = LocationPermission.deniedForever;

      await tester.pumpWidget(_checkoutHost(service));
      await tester.pump(const Duration(milliseconds: 400));

      await tapMode(tester, 'Car');
      await tester.pumpAndSettle();
      await tester.tap(find.byKey(const Key('location_blocked_dismiss')));
      await tester.pumpAndSettle();

      await tapMode(tester, 'Bus');
      await tester.pumpAndSettle();
      expect(find.byKey(const Key('location_blocked_dialog')), findsNothing,
          reason: 'switching chips is not a deliberate location request');
    });

    testWidgets('FR-C6: a refusal still leaves checkout payable',
        (tester) async {
      _sizeSurface(tester);
      fake.permission = LocationPermission.denied;
      fake.grantOnRequest = LocationPermission.denied;

      await tester.pumpWidget(_checkoutHost(service));
      await tester.pump(const Duration(milliseconds: 400));
      await tapMode(tester, 'Car');
      await tester.pumpAndSettle();

      expect(find.byKey(const Key('checkout_origin_status')), findsOneWidget);
      expect(find.textContaining('tap your travel mode again'), findsOneWidget);
    });
  });
}

/// Taps a transport-mode chip by its label.
///
/// Scrolled into view first, exactly like [tapUseGps] — the chip row sits below
/// the fold on the test surface, and a bare `tap()` there hits empty space.
Future<void> tapMode(WidgetTester tester, String label) async {
  final target = find.text(label);
  await tester.ensureVisible(target);
  await tester.pump();
  await tester.tap(target);
  await tester.pump();
  await tester.pump(const Duration(milliseconds: 400));
}

/// A scripted geolocator, so permission states can be driven exactly.
class _FakeGeolocator extends GeolocatorPlatform {
  LocationPermission permission = LocationPermission.denied;

  /// What the OS dialog answers when raised.
  LocationPermission grantOnRequest = LocationPermission.whileInUse;

  bool serviceEnabled = true;

  int requestCount = 0;
  int positionCount = 0;
  int openAppSettingsCount = 0;

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
  Future<bool> openAppSettings() async {
    openAppSettingsCount++;
    return true;
  }

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
