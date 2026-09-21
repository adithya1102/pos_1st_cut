// Migration 030: the offered travel modes come from the SERVER, and Tram.
//
// 029 stored a column per mode and derived Metro from `city_type`. That shape
// could not grow — every new mode meant a column, a migration, a backend field
// and an app release. 030 replaces it with a per-city grid plus a catalog, and
// the outlet payload now carries the resolved list.
//
// The claim under test here is the one that matters: a mode this build has
// NEVER HEARD OF still renders and still behaves correctly, because
// `uses_declared_arrival` travels with the data instead of being inferred from
// a name. Without that, "no app release needed" is not true.
import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:provider/provider.dart';
import 'package:shared_preferences/shared_preferences.dart';

import 'package:customer_app/config/city_transport.dart';
import 'package:customer_app/models/menu.dart';
import 'package:customer_app/models/outlet.dart';
import 'package:customer_app/screens/checkout_screen.dart';
import 'package:customer_app/services/api_client.dart';
import 'package:customer_app/services/catalog_service.dart';
import 'package:customer_app/services/customer_service.dart';
import 'package:customer_app/services/location_service.dart';
import 'package:customer_app/services/order_service.dart';
import 'package:customer_app/state/cart_state.dart';
import 'package:customer_app/theme/app_theme.dart';
import 'package:customer_app/theme/theme_provider.dart';

/// A server mode entry, as `/customer/outlets` sends it.
Map<String, dynamic> mode(String code, String label, {bool declared = false}) =>
    {'code': code, 'label': label, 'uses_declared_arrival': declared};

/// The five road modes every city gets by default.
final _road = [
  mode('walk', 'Walk'),
  mode('bike', 'Bike'),
  mode('car', 'Car'),
  mode('auto', 'Auto'),
  mode('bus', 'Bus'),
];

Map<String, dynamic> _outletJson({
  String? city,
  List<Map<String, dynamic>>? modes,
}) =>
    {
      'id': 'outlet-1',
      'name': 'Test Kitchen',
      'address': 'Somewhere',
      'is_open': true,
      'city': ?city,
      // Omitted entirely when null, so "the server did not say" is a real case
      // rather than an empty list.
      'transport_modes': ?modes,
    };

void _sizeSurface(WidgetTester tester) {
  tester.view.physicalSize = const Size(1170, 2532);
  tester.view.devicePixelRatio = 3.0;
  addTearDown(tester.view.reset);
}

Widget _checkout(Outlet outlet) {
  SharedPreferences.setMockInitialValues({});
  final api = ApiClient();
  final cart = CartState();
  cart.setOutlet(outlet);
  cart.addItem(MenuItem.fromJson({
    'id': 'i1',
    'name': 'Dosa',
    'base_price': 90,
    'is_veg': true,
    'is_available': true,
    'customizations': const [],
  }));

  return MultiProvider(
    providers: [
      Provider<ApiClient>.value(value: api),
      Provider<CatalogService>(create: (_) => CatalogService(api)),
      Provider<CustomerService>(create: (_) => CustomerService(api)),
      Provider<OrderService>(create: (_) => OrderService(api)),
      ChangeNotifierProvider<LocationService>(create: (_) => LocationService()),
      ChangeNotifierProvider<CartState>.value(value: cart),
      ChangeNotifierProvider<ThemeProvider>(create: (_) => ThemeProvider()),
    ],
    child: MaterialApp(theme: AppTheme.light(), home: const CheckoutScreen()),
  );
}

Future<void> tapMode(WidgetTester tester, String label) async {
  final target = find.text(label);
  await tester.ensureVisible(target);
  await tester.pump();
  await tester.tap(target);
  await tester.pump();
  await tester.pump(const Duration(milliseconds: 400));
}

void main() {
  // =========================================================================
  // Tram — a real mode, same shape as Metro
  // =========================================================================
  group('Tram', () {
    testWidgets('appears only where the server enabled it', (tester) async {
      _sizeSurface(tester);
      await tester.pumpWidget(_checkout(Outlet.fromJson(_outletJson(
        city: 'Kolkata',
        modes: [..._road, mode('tram', 'Tram', declared: true)],
      ))));
      await tester.pumpAndSettle();

      expect(find.text('Tram'), findsOneWidget);
    });

    testWidgets('is absent when the server did not enable it', (tester) async {
      _sizeSurface(tester);
      await tester.pumpWidget(_checkout(Outlet.fromJson(_outletJson(
        city: 'Kolkata',
        modes: [..._road, mode('metro', 'Metro', declared: true)],
      ))));
      await tester.pumpAndSettle();

      expect(find.text('Tram'), findsNothing);
      expect(find.text('Metro'), findsOneWidget);
    });

    testWidgets('asks for an arrival TIME, not a location', (tester) async {
      // The whole reason tram is declared-arrival: a tram runs a scheduled
      // route you read a time off, and the backend has no MODE_SPEED_MPS entry
      // for it — a speed-based tram would silently be timed as a bike ride.
      _sizeSurface(tester);
      await tester.pumpWidget(_checkout(Outlet.fromJson(_outletJson(
        city: 'Kolkata',
        modes: [..._road, mode('tram', 'Tram', declared: true)],
      ))));
      await tester.pumpAndSettle();

      await tapMode(tester, 'Tram');

      // The ONE time control, in its declared-arrival form. The page asks the
      // question generically now — the vehicle noun moved into the sheet this
      // card opens (asserted by the next test), because there is a single card
      // serving all four (mode, order type) combinations and it cannot carry
      // four different headings.
      expect(find.byKey(const Key('time_field')), findsOneWidget);
      expect(find.text('When do you arrive?'), findsOneWidget);
      // And no origin status line: a stated time replaces the origin entirely.
      expect(find.byKey(const Key('checkout_origin_status')), findsNothing);
    });

    testWidgets('the opened picker sheet also says tram', (tester) async {
      // The bug caught on Metro: the page heading was mode-aware but the sheet
      // it opened kept a hardcoded "train".
      _sizeSurface(tester);
      await tester.pumpWidget(_checkout(Outlet.fromJson(_outletJson(
        city: 'Kolkata',
        modes: [..._road, mode('tram', 'Tram', declared: true)],
      ))));
      await tester.pumpAndSettle();

      await tapMode(tester, 'Tram');
      await tester.tap(find.byKey(const Key('time_field')));
      await tester.pumpAndSettle();

      expect(find.byKey(const Key('arrival_day_part')), findsOneWidget);
      expect(find.textContaining('train'), findsNothing);
      expect(find.text('When does your tram arrive?'), findsWidgets);
    });
  });

  // =========================================================================
  // The server list IS the answer — including modes this build predates
  // =========================================================================
  group('server-driven mode list', () {
    testWidgets('renders exactly the modes the server sent, in its order',
        (tester) async {
      _sizeSurface(tester);
      await tester.pumpWidget(_checkout(Outlet.fromJson(_outletJson(
        city: 'Chennai',
        modes: [mode('walk', 'Walk'), mode('metro', 'Metro', declared: true)],
      ))));
      await tester.pumpAndSettle();

      expect(find.text('Walk'), findsOneWidget);
      expect(find.text('Metro'), findsOneWidget);
      // NOT offered by this server response, so not rendered — even though the
      // app knows perfectly well what they are.
      expect(find.text('Bike'), findsNothing);
      expect(find.text('Car'), findsNothing);
      expect(find.text('Train'), findsNothing);
    });

    testWidgets('a mode this build has NEVER heard of still renders',
        (tester) async {
      // THE extensibility claim. A ninth mode is one INSERT server-side; it has
      // no enum case, no icon and no label here, and it must still appear.
      _sizeSurface(tester);
      await tester.pumpWidget(_checkout(Outlet.fromJson(_outletJson(
        city: 'Chennai',
        modes: [..._road, mode('ferry', 'Ferry', declared: true)],
      ))));
      await tester.pumpAndSettle();

      expect(find.text('Ferry'), findsOneWidget,
          reason: 'an unknown mode must render from the server label');
    });

    testWidgets('an unknown declared-arrival mode BEHAVES correctly',
        (tester) async {
      // Rendering it is not enough — it has to do the right thing. The app
      // cannot know a ferry is declared-arrival, so the flag has to travel
      // with the data.
      _sizeSurface(tester);
      await tester.pumpWidget(_checkout(Outlet.fromJson(_outletJson(
        city: 'Chennai',
        modes: [..._road, mode('ferry', 'Ferry', declared: true)],
      ))));
      await tester.pumpAndSettle();

      await tapMode(tester, 'Ferry');

      expect(find.byKey(const Key('time_field')), findsOneWidget,
          reason: 'uses_declared_arrival travels with the mode');
      expect(find.text('When do you arrive?'), findsOneWidget,
          reason: 'the declared-arrival label, not the pickup-slot one');

      // The server's own label still drives the copy — it just does so in the
      // sheet now that the page asks the question generically. Opening it is
      // the only place the ferry can still be named, so this is where the
      // "no hardcoded switch" claim has to be proved.
      await tester.tap(find.byKey(const Key('time_field')));
      await tester.pumpAndSettle();
      expect(find.text('When does your ferry arrive?'), findsWidgets,
          reason: 'copy is built from the server label, not a hardcoded switch');
    });

    testWidgets('an unknown SPEED-based mode asks for location instead',
        (tester) async {
      _sizeSurface(tester);
      await tester.pumpWidget(_checkout(Outlet.fromJson(_outletJson(
        city: 'Chennai',
        modes: [..._road, mode('scooter', 'Scooter')],
      ))));
      await tester.pumpAndSettle();

      await tapMode(tester, 'Scooter');

      // GPS mode + Order now = no time control at all. The origin and the
      // clock already answer "when will you be here?", so there is nothing
      // left to ask.
      expect(find.byKey(const Key('time_field')), findsNothing);
      expect(find.byKey(const Key('checkout_origin_status')), findsOneWidget);
    });

    testWidgets('an EMPTY server list is honoured, not treated as absent',
        (tester) async {
      // "This city offers nothing" is a real answer. Collapsing it to the
      // built-in fallback would silently re-offer five modes an admin had
      // deliberately switched off.
      _sizeSurface(tester);
      await tester.pumpWidget(_checkout(
          Outlet.fromJson(_outletJson(city: 'Chennai', modes: []))));
      await tester.pumpAndSettle();

      for (final m in ['Walk', 'Bike', 'Car', 'Auto', 'Bus', 'Train', 'Metro']) {
        expect(find.text(m), findsNothing, reason: m);
      }
    });
  });

  // =========================================================================
  // Fallback: a backend that has not run 030
  // =========================================================================
  group('pre-030 fallback', () {
    testWidgets('no transport_modes key -> the 029/local answer still works',
        (tester) async {
      _sizeSurface(tester);
      await tester.pumpWidget(
          _checkout(Outlet.fromJson(_outletJson(city: 'Chennai'))));
      await tester.pumpAndSettle();

      // The built-in rail map still covers Chennai.
      expect(find.text('Train'), findsOneWidget);
      expect(find.text('Metro'), findsOneWidget);
      for (final m in ['Walk', 'Bike', 'Car', 'Auto', 'Bus']) {
        expect(find.text(m), findsOneWidget, reason: m);
      }
    });

    testWidgets('Tram is NOT guessed by the fallback', (tester) async {
      // Nothing older than 030 knows tram exists, so the honest answer is no.
      // Inferring it from "has a metro" would offer trams in four cities.
      _sizeSurface(tester);
      await tester.pumpWidget(
          _checkout(Outlet.fromJson(_outletJson(city: 'Chennai'))));
      await tester.pumpAndSettle();

      expect(find.text('Tram'), findsNothing);
    });

    test('CityTransport helpers read the server list when present', () {
      final o = Outlet.fromJson(_outletJson(city: 'Madurai', modes: [
        mode('tram', 'Tram', declared: true),
      ]));
      expect(CityTransport.tramFor(o), isTrue);
      expect(CityTransport.metroFor(o), isFalse);
      expect(CityTransport.trainFor(o), isFalse);
    });

    test('and fall back to the built-in map when absent', () {
      final o = Outlet.fromJson(_outletJson(city: 'Chennai'));
      expect(o.transportModes, isNull);
      expect(CityTransport.trainFor(o), isTrue);
      expect(CityTransport.metroFor(o), isTrue);
      expect(CityTransport.tramFor(o), isFalse);
    });
  });

  // =========================================================================
  // The list survives the cart's persistence round trip
  // =========================================================================
  test('transport_modes round-trip through toJson/fromJson', () {
    // Checkout renders from the RESTORED outlet, so dropping these would make
    // every chip vanish on a cold start with a saved cart.
    final o = Outlet.fromJson(_outletJson(city: 'Kolkata', modes: [
      mode('walk', 'Walk'),
      mode('tram', 'Tram', declared: true),
    ]));
    final back = Outlet.fromJson(o.toJson());

    expect(back.transportModes, isNotNull);
    expect(back.transportModes!.map((m) => m.code), ['walk', 'tram']);
    expect(back.transportModes!.last.usesDeclaredArrival, isTrue);
  });

  test('a malformed entry is dropped, not rendered blank', () {
    final o = Outlet.fromJson({
      ..._outletJson(city: 'Chennai'),
      'transport_modes': [
        {'code': 'walk', 'label': 'Walk'},
        {'label': 'no code at all'},
        'not even a map',
      ],
    });
    expect(o.transportModes!.map((m) => m.code), ['walk']);
  });
}
