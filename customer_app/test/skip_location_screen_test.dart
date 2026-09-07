// "Find restaurants near you" goes STRAIGHT to the outlet list.
//
// It used to push LocationScreen (Discover), which asked "where are you?" and
// then pushed OutletsScreen with the answer. Discover is now skipped: the same
// question is answered ON the outlet list, by asking for location on arrival
// and falling back to a city picker when that is refused.
//
// LocationScreen itself is deliberately UNTOUCHED and still builds — it is just
// no longer routed to. The last group here pins that, so "unrouted" cannot
// quietly become "broken".
//
// The load-bearing default is `autoLocate: false`. Opening this screen with no
// cities and no origin is a legitimate "show me everything", and it must not
// raise a permission dialog nobody asked for — only the Home CTA passes true.
import 'dart:convert';

import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:geolocator/geolocator.dart';
import 'package:http/http.dart' as http;
import 'package:http/testing.dart';
import 'package:provider/provider.dart';
import 'package:shared_preferences/shared_preferences.dart';

import 'package:customer_app/models/outlet.dart';
import 'package:customer_app/screens/home_screen.dart';
import 'package:customer_app/screens/location_screen.dart';
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

http.Response _json(Object body, {int status = 200}) =>
    http.Response(jsonEncode(body), status,
        headers: {'content-type': 'application/json'});

/// Every /customer/outlets request, as its query parameters. The request log is
/// the evidence for what was actually asked for — a UI assertion would only
/// show that a chip changed colour.
late List<Map<String, List<String>>> requests;

Map<String, dynamic> _outlet({
  required String id,
  required String name,
  required String city,
  double? distanceKm,
}) =>
    {
      'id': id,
      'name': name,
      'address': 'Somewhere, $city',
      'city': city,
      'is_open': true,
      'order_status': 'ACCEPTING',
      'distance_km': distanceKm,
      'latitude': 12.9,
      'longitude': 77.5,
      'offer_count': 0,
    };

/// Three outlets in three cities, deliberately NOT ordered by distance — the
/// nearest is in the middle, so a rule that took the first row would pass by
/// accident.
final _outlets = [
  _outlet(id: 'o1', name: 'Far Kitchen', city: 'Chennai', distanceKm: 41.2),
  _outlet(id: 'o2', name: 'Close Kitchen', city: 'Bengaluru', distanceKm: 2.4),
  _outlet(id: 'o3', name: 'Mid Kitchen', city: 'Mysuru', distanceKm: 18.9),
];

final _areas = [
  {'city': 'Bengaluru', 'outlet_count': 1},
  {'city': 'Chennai', 'outlet_count': 1},
  {'city': 'Mysuru', 'outlet_count': 1},
];

http.Client _backend({List<Map<String, dynamic>>? outlets}) =>
    MockClient((req) async {
      final path = req.url.path;
      if (path.endsWith('/customer/outlets')) {
        requests.add(req.url.queryParametersAll);
        return _json(outlets ?? _outlets);
      }
      if (path.endsWith('/customer/areas')) return _json(_areas);
      if (path.endsWith('/customer/orders')) return _json(const []);
      if (path.endsWith('/customer/me')) {
        return _json({'id': 'c1', 'name': 'Asha', 'phone_number': '+919'});
      }
      return _json(const []);
    });

/// The outlet screen, under a full provider tree.
Widget _host(
  Widget home, {
  LocationService? location,
  List<Map<String, dynamic>>? outlets,
}) {
  SharedPreferences.setMockInitialValues({'carevo_access_token': 'valid'});
  final api = ApiClient(client: _backend(outlets: outlets));
  return MultiProvider(
    providers: [
      Provider<ApiClient>.value(value: api),
      Provider<CatalogService>(create: (_) => CatalogService(api)),
      Provider<CustomerService>(create: (_) => CustomerService(api)),
      Provider<OrderService>(create: (_) => OrderService(api)),
      ChangeNotifierProvider<LocationService>.value(
          value: location ?? LocationService()),
      ChangeNotifierProvider<CartState>(create: (_) => CartState()),
      ChangeNotifierProvider<ThemeProvider>(create: (_) => ThemeProvider()),
      ChangeNotifierProvider<AuthState>(
        create: (_) => AuthState(
            api, StubOtpService(api), GoogleAuthService(api), PushService(api)),
      ),
    ],
    child: MaterialApp(theme: AppTheme.light(), home: home),
  );
}

double? _radiusOf(Map<String, List<String>> q) =>
    double.tryParse(q['radius_km']?.first ?? '');
List<String> _citiesOf(Map<String, List<String>> q) => q['city'] ?? const [];

void main() {
  late _FakeGeolocator fake;
  late LocationService service;

  setUp(() {
    requests = [];
    fake = _FakeGeolocator();
    GeolocatorPlatform.instance = fake;
    service = LocationService();
  });

  // =========================================================================
  // The route itself
  // =========================================================================
  group('"Find restaurants near you" destination', () {
    testWidgets('lands on OutletsScreen, never on LocationScreen',
        (tester) async {
      // Refused, so the screen cannot navigate onward by acquiring a location.
      // The destination is what is being asserted, not what it then does.
      fake.permission = LocationPermission.denied;
      fake.grantOnRequest = LocationPermission.denied;

      await tester.pumpWidget(_host(const HomeScreen(), location: service));
      await tester.pumpAndSettle();

      await tester.tap(find.byKey(const Key('home_find_restaurants')).first);
      await tester.pumpAndSettle();

      expect(find.byType(OutletsScreen), findsOneWidget);
      expect(find.byType(LocationScreen), findsNothing);
    });

    testWidgets('arrives with no cities and no origin', (tester) async {
      fake.permission = LocationPermission.denied;
      fake.grantOnRequest = LocationPermission.denied;

      await tester.pumpWidget(_host(const HomeScreen(), location: service));
      await tester.pumpAndSettle();
      await tester.tap(find.byKey(const Key('home_find_restaurants')).first);
      await tester.pumpAndSettle();

      final screen =
          tester.widget<OutletsScreen>(find.byType(OutletsScreen));
      expect(screen.cities, isEmpty);
      expect(screen.lat, isNull);
      expect(screen.lng, isNull);
      // ...and asks to go looking, which is the whole point of the new route.
      expect(screen.autoLocate, isTrue);

      // The first request carries neither — nothing has been resolved yet.
      expect(requests.first.containsKey('lat'), isFalse);
      expect(_citiesOf(requests.first), isEmpty);
    });
  });

  // =========================================================================
  // Nearest-city derivation — the rule, without a screen around it
  // =========================================================================
  group('OutletsScreen.nearestCity', () {
    List<Outlet> parse(List<Map<String, dynamic>> raw) =>
        raw.map(Outlet.fromJson).toList();

    test('picks the city of the CLOSEST outlet, not the first', () {
      expect(OutletsScreen.nearestCity(parse(_outlets)), 'Bengaluru');
    });

    test('skips outlets with no distance rather than treating them as zero',
        () {
      // Every outlet is distance-less whenever the request carried no origin;
      // sorting nulls first would "detect" whatever came back first.
      final mixed = [
        _outlet(id: 'a', name: 'No distance', city: 'Kolkata'),
        _outlet(id: 'b', name: 'Real', city: 'Bengaluru', distanceKm: 9.0),
      ];
      expect(OutletsScreen.nearestCity(parse(mixed)), 'Bengaluru');
    });

    test('skips outlets with a blank city', () {
      final blank = [
        _outlet(id: 'a', name: 'Nameless', city: '', distanceKm: 0.5),
        _outlet(id: 'b', name: 'Real', city: 'Chennai', distanceKm: 9.0),
      ];
      expect(OutletsScreen.nearestCity(parse(blank)), 'Chennai');
    });

    test('null when nothing qualifies — an empty list included', () {
      expect(OutletsScreen.nearestCity(const []), isNull);
      expect(
        OutletsScreen.nearestCity(
            parse([_outlet(id: 'a', name: 'x', city: 'Pune')])),
        isNull,
      );
    });
  });

  // =========================================================================
  // Granted — derive the city and pre-tick it
  // =========================================================================
  group('location granted', () {
    testWidgets('fetches by origin and names the detected city',
        (tester) async {
      fake.permission = LocationPermission.whileInUse;

      await tester.pumpWidget(
          _host(const OutletsScreen(autoLocate: true), location: service));
      await tester.pumpAndSettle();

      // The origin went with the request, under the default Near Me radius.
      final q = requests.last;
      expect(q['lat']?.first, isNotNull);
      expect(_radiusOf(q), 65.0);

      // Bengaluru is the CLOSEST outlet's city (2.4km), not the first row.
      expect(find.text('Near Bengaluru'), findsOneWidget);
    });

    testWidgets('the detected city is PRE-TICKED in the popup', (tester) async {
      fake.permission = LocationPermission.whileInUse;

      await tester.pumpWidget(
          _host(const OutletsScreen(autoLocate: true), location: service));
      await tester.pumpAndSettle();

      // No popup on the granted path — the location question is answered.
      expect(find.byKey(const Key('city_picker_sheet')), findsNothing);

      await tester.tap(find.byKey(const Key('location_chip')));
      await tester.pumpAndSettle();

      expect(find.byKey(const Key('city_picker_sheet')), findsOneWidget);
      // One tap to confirm, because the box is already ticked.
      expect(find.text('Show outlets in Bengaluru'), findsOneWidget);
    });

    testWidgets('detection does NOT itself filter by city', (tester) async {
      // The list stays the radius query that produced the detection. Sending a
      // city as well would narrow it to one city without being asked.
      fake.permission = LocationPermission.whileInUse;

      await tester.pumpWidget(
          _host(const OutletsScreen(autoLocate: true), location: service));
      await tester.pumpAndSettle();

      expect(_citiesOf(requests.last), isEmpty);
    });
  });

  // =========================================================================
  // Refused — the picker opens by itself
  // =========================================================================
  group('location refused opens the city picker', () {
    Future<void> pumpRefusal(WidgetTester tester) async {
      await tester.pumpWidget(
          _host(const OutletsScreen(autoLocate: true), location: service));
      await tester.pumpAndSettle();
    }

    testWidgets('denied', (tester) async {
      fake.permission = LocationPermission.denied;
      fake.grantOnRequest = LocationPermission.denied;
      await pumpRefusal(tester);
      expect(find.byKey(const Key('city_picker_sheet')), findsOneWidget);
    });

    testWidgets('deniedForever — after the settings dialog', (tester) async {
      fake.permission = LocationPermission.deniedForever;
      await pumpRefusal(tester);

      // The dialog explains the refusal but cannot resolve it, so the picker
      // still follows: the customer came here to find restaurants.
      await tester.tap(find.text('Not now'));
      await tester.pumpAndSettle();

      expect(find.byKey(const Key('city_picker_sheet')), findsOneWidget);
    });

    testWidgets('serviceDisabled', (tester) async {
      fake.serviceEnabled = false;
      await pumpRefusal(tester);
      expect(find.byKey(const Key('city_picker_sheet')), findsOneWidget);
    });

    testWidgets('error', (tester) async {
      fake.throwOnCheck = true;
      await pumpRefusal(tester);
      expect(find.byKey(const Key('city_picker_sheet')), findsOneWidget);
    });

    testWidgets('the picker lists the cities from /customer/areas',
        (tester) async {
      fake.permission = LocationPermission.denied;
      fake.grantOnRequest = LocationPermission.denied;
      await pumpRefusal(tester);

      for (final city in ['Bengaluru', 'Chennai', 'Mysuru']) {
        expect(find.byKey(Key('city_row_$city')), findsOneWidget);
      }
      // Nothing ticked: there was no detection to seed it with.
      expect(find.text('Pick at least one city'), findsOneWidget);
    });
  });

  // =========================================================================
  // Exclusivity — cities REPLACE a radius
  // =========================================================================
  group('choosing cities clears the radius', () {
    testWidgets('the request swaps radius_km for city', (tester) async {
      fake.permission = LocationPermission.whileInUse;

      await tester.pumpWidget(
          _host(const OutletsScreen(autoLocate: true), location: service));
      await tester.pumpAndSettle();

      // Near Me is in effect after a grant.
      expect(_radiusOf(requests.last), 65.0);

      await tester.tap(find.byKey(const Key('location_chip')));
      await tester.pumpAndSettle();
      await tester.tap(find.byKey(const Key('city_row_Chennai')));
      await tester.pumpAndSettle();
      await tester.tap(find.byKey(const Key('city_picker_apply')));
      await tester.pumpAndSettle();

      final q = requests.last;
      expect(_citiesOf(q), containsAll(['Bengaluru', 'Chennai']));
      expect(_radiusOf(q), isNull,
          reason: 'a city filter must replace the radius, not stack with it');
      // The origin SURVIVES: it is not a filter, and dropping it would lose
      // distance_km and silently break the Nearest sort.
      expect(q['lat']?.first, isNotNull);
    });

    testWidgets('neither radius chip stays selected', (tester) async {
      fake.permission = LocationPermission.whileInUse;

      await tester.pumpWidget(
          _host(const OutletsScreen(autoLocate: true), location: service));
      await tester.pumpAndSettle();

      await tester.tap(find.byKey(const Key('location_chip')));
      await tester.pumpAndSettle();
      await tester.tap(find.byKey(const Key('city_picker_apply')));
      await tester.pumpAndSettle();

      // The label now states the city filter, not the radius it replaced.
      expect(find.text('In Bengaluru'), findsOneWidget);
      expect(find.text('Near Bengaluru'), findsNothing);
    });

    testWidgets('and a radius chip clears the cities right back', (tester) async {
      // The existing half of the exclusivity, re-pinned from this new entry
      // point: enforcing it on one side only would let the losing control keep
      // claiming a filter that is no longer applied.
      fake.permission = LocationPermission.whileInUse;

      await tester.pumpWidget(
          _host(const OutletsScreen(autoLocate: true), location: service));
      await tester.pumpAndSettle();

      await tester.tap(find.byKey(const Key('location_chip')));
      await tester.pumpAndSettle();
      await tester.tap(find.byKey(const Key('city_picker_apply')));
      await tester.pumpAndSettle();
      expect(_citiesOf(requests.last), isNotEmpty);

      await tester.tap(find.byKey(const Key('radius_travel')));
      await tester.pumpAndSettle();

      expect(_citiesOf(requests.last), isEmpty);
      expect(_radiusOf(requests.last), 300.0);
    });
  });

  // =========================================================================
  // The default that protects every other caller
  // =========================================================================
  group('autoLocate defaults to false', () {
    testWidgets('a bare OutletsScreen asks for nothing', (tester) async {
      fake.permission = LocationPermission.denied;
      fake.grantOnRequest = LocationPermission.whileInUse;

      await tester.pumpWidget(_host(const OutletsScreen(), location: service));
      await tester.pumpAndSettle();

      expect(fake.requestCount, 0,
          reason: 'opening the list is not a request for location');
      expect(find.byKey(const Key('city_picker_sheet')), findsNothing);
      expect(find.text('All restaurants'), findsOneWidget);
    });

    testWidgets('the picker is still reachable by tapping the chip',
        (tester) async {
      await tester.pumpWidget(_host(const OutletsScreen(), location: service));
      await tester.pumpAndSettle();

      await tester.tap(find.byKey(const Key('location_chip')));
      await tester.pumpAndSettle();

      expect(find.byKey(const Key('city_picker_sheet')), findsOneWidget);
    });

    testWidgets('arriving WITH cities does not trigger the location ask',
        (tester) async {
      fake.permission = LocationPermission.denied;

      await tester.pumpWidget(_host(
        const OutletsScreen(cities: {'Chennai'}, autoLocate: true),
        location: service,
      ));
      await tester.pumpAndSettle();

      expect(fake.requestCount, 0,
          reason: 'the location question is already answered');
      expect(find.byKey(const Key('city_picker_sheet')), findsNothing);
      expect(find.text('In Chennai'), findsOneWidget);
    });
  });

  // =========================================================================
  // Unrouted, NOT deleted
  // =========================================================================
  group('LocationScreen survives unrouted', () {
    testWidgets('still builds, and still navigates to the outlet list',
        (tester) async {
      await tester.pumpWidget(_host(const LocationScreen(), location: service));
      await tester.pumpAndSettle();

      expect(find.text('Discover'), findsOneWidget);
      expect(find.byKey(const Key('city_row_Bengaluru')), findsOneWidget);

      await tester.tap(find.byKey(const Key('city_row_Bengaluru')));
      await tester.pumpAndSettle();
      await tester.tap(find.byKey(const Key('show_outlets_cta')));
      await tester.pumpAndSettle();

      expect(find.byType(OutletsScreen), findsOneWidget);
      expect(_citiesOf(requests.last), ['Bengaluru']);
    });

    testWidgets('what it pushes does NOT auto-locate', (tester) async {
      // It supplies the cities itself, so the arrival flow has nothing to ask.
      fake.permission = LocationPermission.denied;

      await tester.pumpWidget(_host(const LocationScreen(), location: service));
      await tester.pumpAndSettle();
      await tester.tap(find.byKey(const Key('city_row_Chennai')));
      await tester.pumpAndSettle();
      await tester.tap(find.byKey(const Key('show_outlets_cta')));
      await tester.pumpAndSettle();

      expect(fake.requestCount, 0);
      expect(find.byKey(const Key('city_picker_sheet')), findsNothing);
    });
  });
}

/// A scripted geolocator, so permission transitions can be driven exactly.
class _FakeGeolocator extends GeolocatorPlatform {
  LocationPermission permission = LocationPermission.denied;

  /// What a prompt returns.
  LocationPermission grantOnRequest = LocationPermission.whileInUse;

  bool serviceEnabled = true;

  /// Drives the `error` outcome — a platform read that simply fails.
  bool throwOnCheck = false;

  /// How many times the OS dialog was actually raised.
  int requestCount = 0;

  @override
  Future<bool> isLocationServiceEnabled() async => serviceEnabled;

  @override
  Future<LocationPermission> checkPermission() async {
    if (throwOnCheck) throw Exception('platform channel unavailable');
    return permission;
  }

  @override
  Future<LocationPermission> requestPermission() async {
    requestCount++;
    permission = grantOnRequest;
    return permission;
  }

  @override
  Future<Position> getCurrentPosition({LocationSettings? locationSettings}) async =>
      Position(
        latitude: 12.9716,
        longitude: 77.5946,
        timestamp: DateTime.fromMillisecondsSinceEpoch(0),
        accuracy: 10,
        altitude: 0,
        altitudeAccuracy: 0,
        heading: 0,
        headingAccuracy: 0,
        speed: 0,
        speedAccuracy: 0,
      );
}
