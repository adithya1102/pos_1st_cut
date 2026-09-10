// Train is offered only where a customer can actually arrive by rail.
//
// Train is unlike the other five modes: it carries no GPS origin and no speed,
// because the customer STATES an arrival time and the server takes it as given.
// Offering it in a city with no rail would collect a declared arrival for a
// journey that cannot happen — and that number goes straight into the timing
// engine, so the mistake would surface as food cooked for a train that was
// never coming, not as a visible error.
//
// The other five (walk/bike/car/auto/bus) are unconditional: walking, cycling
// and road transport exist everywhere, so nothing gates them.
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
import 'package:customer_app/services/places_service.dart';
import 'package:customer_app/state/cart_state.dart';
import 'package:customer_app/theme/app_theme.dart';
import 'package:customer_app/theme/theme_provider.dart';

Map<String, dynamic> _outletJson({String? city}) => {
      'id': 'outlet-1',
      'name': 'Test Kitchen',
      'address': city == null ? 'Somewhere' : 'Locality, $city',
      'is_open': true,
      // Omitted entirely when null, so the "no city field at all" case really
      // exercises an absent key rather than an explicit null.
      'city': ?city,
    };

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
      Provider<PlacesService>(create: (_) => PlacesService()),
      ChangeNotifierProvider<LocationService>(create: (_) => LocationService()),
      ChangeNotifierProvider<CartState>.value(value: cart),
      ChangeNotifierProvider<ThemeProvider>(create: (_) => ThemeProvider()),
    ],
    child: MaterialApp(theme: AppTheme.light(), home: const CheckoutScreen()),
  );
}

/// The five modes that must appear no matter where the outlet is.
const _always = ['Walk', 'Bike', 'Car', 'Auto', 'Bus'];

void main() {
  group('the lookup itself', () {
    test('the four live cities all have rail', () {
      for (final c in ['Chennai', 'Bengaluru', 'Kolkata', 'Kochi']) {
        expect(CityTransport.hasTrainAccess(c), isTrue, reason: c);
      }
    });

    test('matching is case-insensitive and trims', () {
      // outlets.city is free text with no constraint — list_outlets already
      // compares lower() on both sides for the same reason.
      for (final c in ['chennai', 'CHENNAI', 'ChEnNaI', '  Chennai  ']) {
        expect(CityTransport.hasTrainAccess(c), isTrue, reason: '"$c"');
      }
    });

    test('an unknown city is false — the safe default, not an oversight', () {
      // A city can appear in `outlets` through a signup, with no code change.
      // It must not silently start offering a mode nobody has checked.
      expect(CityTransport.hasTrainAccess('Madurai'), isFalse);
      expect(CityTransport.hasTrainAccess('Coimbatore'), isFalse);
    });

    test('null and empty are false, not a crash', () {
      // `city` is null on any response predating the field.
      expect(CityTransport.hasTrainAccess(null), isFalse);
      expect(CityTransport.hasTrainAccess(''), isFalse);
      expect(CityTransport.hasTrainAccess('   '), isFalse);
    });
  });

  group('the checkout chip row', () {
    testWidgets('a rail city offers Train', (tester) async {
      await tester.pumpWidget(_checkout(Outlet.fromJson(_outletJson(city: 'Chennai'))));
      await tester.pumpAndSettle();

      expect(find.text('Train'), findsOneWidget);
      for (final m in _always) {
        expect(find.text(m), findsOneWidget, reason: m);
      }
    });

    testWidgets('a city not in the config does NOT offer Train', (tester) async {
      // Madurai stands in for any future city added by a signup.
      await tester.pumpWidget(_checkout(Outlet.fromJson(_outletJson(city: 'Madurai'))));
      await tester.pumpAndSettle();

      expect(find.text('Train'), findsNothing);
      for (final m in _always) {
        expect(find.text(m), findsOneWidget,
            reason: '$m must not be gated by the rail lookup');
      }
    });

    testWidgets('an outlet with no city at all does NOT offer Train',
        (tester) async {
      // The pre-field response shape: `city` absent entirely.
      await tester.pumpWidget(_checkout(Outlet.fromJson(_outletJson())));
      await tester.pumpAndSettle();

      expect(find.text('Train'), findsNothing);
      for (final m in _always) {
        expect(find.text(m), findsOneWidget, reason: m);
      }
    });

    testWidgets('the arrival picker never appears without Train on offer',
        (tester) async {
      // Train is the only mode that shows it, so a non-rail city must not be
      // able to reach it by any route.
      await tester.pumpWidget(_checkout(Outlet.fromJson(_outletJson(city: 'Madurai'))));
      await tester.pumpAndSettle();

      expect(find.byKey(const Key('arrival_field')), findsNothing);
    });

    testWidgets('every mode is offered case-insensitively of stored city',
        (tester) async {
      await tester.pumpWidget(_checkout(Outlet.fromJson(_outletJson(city: 'kolkata'))));
      await tester.pumpAndSettle();
      expect(find.text('Train'), findsOneWidget);
    });
  });

  // ==========================================================================
  // Metro (migration 029) — server-driven, with the const map as fallback
  //
  // The point of the server flags is that a NEW metro city lights up without a
  // store release. The point of the fallback is that an OLD backend, which
  // sends no flags at all, must not silently strip Train from Chennai.
  // ==========================================================================
  group('server flags decide, when the server sent them', () {
    Map<String, dynamic> withFlags({
      String? city,
      String? cityType,
      bool? hasMetro,
      bool? hasTrain,
    }) =>
        {
          ..._outletJson(city: city),
          'city_type': ?cityType,
          'has_metro': ?hasMetro,
          'has_train': ?hasTrain,
        };

    test('null is NOT false — an absent flag falls back to the map', () {
      // The regression this guards: flatten null to false and every city loses
      // Train the moment the app meets a pre-029 backend.
      final o = Outlet.fromJson(_outletJson(city: 'Chennai'));
      expect(o.hasMetro, isNull);
      expect(o.hasTrain, isNull);
      expect(CityTransport.trainFor(o), isTrue);
      expect(CityTransport.metroFor(o), isTrue);
    });

    test('an explicit false from the server WINS over the map', () {
      final o = Outlet.fromJson(
          withFlags(city: 'Chennai', cityType: 'tier_1', hasMetro: false, hasTrain: false));
      expect(CityTransport.metroFor(o), isFalse,
          reason: 'the admin said no; the built-in map must not override it');
      expect(CityTransport.trainFor(o), isFalse);
    });

    test('an explicit true lights up a city the map never knew', () {
      // The whole feature: Madurai gets a metro, an admin flips the radio, and
      // an already-installed app offers it. No release.
      final o = Outlet.fromJson(
          withFlags(city: 'Madurai', cityType: 'metro', hasMetro: true, hasTrain: true));
      expect(CityTransport.metroFor(o), isTrue);
      expect(CityTransport.trainFor(o), isTrue);
    });

    test('Metro and Train are independent, not one "has rail" flag', () {
      // Madurai's real shape: a major junction, no metro.
      final o = Outlet.fromJson(
          withFlags(city: 'Madurai', cityType: 'tier_2', hasMetro: false, hasTrain: true));
      expect(CityTransport.metroFor(o), isFalse);
      expect(CityTransport.trainFor(o), isTrue);
    });

    test('the flags survive the cart\'s persistence round trip', () {
      // Checkout renders its chips from the RESTORED outlet, so dropping these
      // from toJson would make Metro vanish on a cold start with a saved cart.
      final o = Outlet.fromJson(
          withFlags(city: 'Chennai', cityType: 'metro', hasMetro: true, hasTrain: true));
      final back = Outlet.fromJson(o.toJson());
      expect(back.cityType, 'metro');
      expect(back.hasMetro, isTrue);
      expect(back.hasTrain, isTrue);
    });
  });

  group('the Metro chip', () {
    testWidgets('a metro city offers Metro alongside Train', (tester) async {
      await tester.pumpWidget(
          _checkout(Outlet.fromJson(_outletJson(city: 'Chennai'))));
      await tester.pumpAndSettle();

      expect(find.text('Metro'), findsOneWidget);
      expect(find.text('Train'), findsOneWidget);
      for (final m in _always) {
        expect(find.text(m), findsOneWidget, reason: m);
      }
    });

    testWidgets('Bengaluru offers Metro — the reported gap', (tester) async {
      await tester.pumpWidget(
          _checkout(Outlet.fromJson(_outletJson(city: 'Bengaluru'))));
      await tester.pumpAndSettle();
      expect(find.text('Metro'), findsOneWidget);
    });

    testWidgets('a non-metro city offers neither', (tester) async {
      await tester.pumpWidget(
          _checkout(Outlet.fromJson(_outletJson(city: 'Madurai'))));
      await tester.pumpAndSettle();

      expect(find.text('Metro'), findsNothing);
      expect(find.text('Train'), findsNothing);
    });

    testWidgets('picking Metro asks for an arrival time, not a location',
        (tester) async {
      await tester.pumpWidget(
          _checkout(Outlet.fromJson(_outletJson(city: 'Chennai'))));
      await tester.pumpAndSettle();

      await tester.ensureVisible(find.text('Metro'));
      await tester.pump();
      await tester.tap(find.text('Metro'));
      await tester.pumpAndSettle();

      // The declared-arrival branch, and the copy names the METRO — telling a
      // metro rider about their "train" is a small wrongness that costs trust.
      expect(find.byKey(const Key('arrival_field')), findsOneWidget);
      expect(find.text('When does your metro arrive?'), findsOneWidget);
      expect(find.text('When does your train arrive?'), findsNothing);
      // And no origin picker: Leg A is a stated time, so GPS would be
      // collected and then ignored.
      expect(find.byKey(const Key('checkout_use_gps')), findsNothing);
    });

    testWidgets('switching to Train restores the train wording',
        (tester) async {
      await tester.pumpWidget(
          _checkout(Outlet.fromJson(_outletJson(city: 'Chennai'))));
      await tester.pumpAndSettle();

      await tester.ensureVisible(find.text('Metro'));
      await tester.pump();
      await tester.tap(find.text('Metro'));
      await tester.pumpAndSettle();
      expect(find.text('When does your metro arrive?'), findsOneWidget);

      // ensureVisible again: selecting Metro swapped the origin card for the
      // arrival picker, which reflows the page under the chip row.
      await tester.ensureVisible(find.text('Train'));
      await tester.pump();
      await tester.tap(find.text('Train'));
      await tester.pumpAndSettle();
      expect(find.text('When does your train arrive?'), findsOneWidget);
      expect(find.text('When does your metro arrive?'), findsNothing);
    });
  });

  group('the city field round-trips', () {
    test('city parses from the API shape', () {
      final o = Outlet.fromJson(_outletJson(city: 'Kochi'));
      expect(o.city, 'Kochi');
    });

    test('city survives the cart-persistence round trip', () {
      // CartState persists an outlet snapshot through toJson/fromJson. If city
      // were dropped there, a restored cart would lose Train on reopen.
      final original = Outlet.fromJson(_outletJson(city: 'Bengaluru'));
      final restored = Outlet.fromJson(original.toJson());
      expect(restored.city, 'Bengaluru');
      expect(CityTransport.hasTrainAccess(restored.city), isTrue);
    });

    test('a response with no city leaves it null rather than guessing', () {
      // Deliberately NOT derived from `address`: for outlets predating
      // migration 012 the address IS the bare city, so a split would be wrong.
      final o = Outlet.fromJson(_outletJson());
      expect(o.city, isNull);
    });
  });
}
