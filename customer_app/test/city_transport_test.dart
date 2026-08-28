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
