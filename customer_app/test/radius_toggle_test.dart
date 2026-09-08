// Near Me / Travel send a real server-side radius, and are mutually exclusive
// with a manually picked city.
//
// Before this the outlet list had no distance cap anywhere — server or client.
// distance_km was computed after the query purely to sort, so a Bengaluru
// origin returned a Kolkata outlet 1566km away, just at the bottom. These pin
// that the app now ASKS for a radius, and asks for the right one.
//
// The request log is the evidence. A UI assertion would show the chip turned
// blue; only the query string shows what was actually requested.
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

/// Every /customer/outlets request, as its query parameters.
late List<Map<String, List<String>>> requests;

http.Client _backend() => MockClient((req) async {
      if (req.url.path.endsWith('/customer/outlets')) {
        requests.add(req.url.queryParametersAll);
      }
      return http.Response('[]', 200,
          headers: {'content-type': 'application/json'});
    });

Widget _host({Set<String> cities = const {}}) {
  SharedPreferences.setMockInitialValues({'carevo_access_token': 't'});
  final api = ApiClient(client: _backend());
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
      // A real origin: a radius is only sent WITH coordinates, so a screen
      // without them could never demonstrate the parameter at all.
      home: OutletsScreen(lat: 12.9716, lng: 77.5946, cities: cities),
    ),
  );
}

String? _radiusOf(Map<String, List<String>> q) => q['radius_km']?.first;
List<String> _citiesOf(Map<String, List<String>> q) => q['city'] ?? const [];

Future<void> _tap(WidgetTester tester, Key key) async {
  await tester.ensureVisible(find.byKey(key));
  await tester.pump();
  await tester.tap(find.byKey(key));
  await tester.pumpAndSettle();
}

void main() {
  setUp(() => requests = []);

  group('what the app actually requests', () {
    testWidgets('Near Me is the default and asks for 65km', (tester) async {
      await tester.pumpWidget(_host());
      await tester.pumpAndSettle();

      expect(requests, isNotEmpty);
      expect(_radiusOf(requests.first), '65.0',
          reason: 'the first load should already be scoped to Near Me');
    });

    testWidgets('Travel asks for 300km', (tester) async {
      await tester.pumpWidget(_host());
      await tester.pumpAndSettle();
      await _tap(tester, const Key('radius_travel'));

      expect(_radiusOf(requests.last), '300.0');
    });

    testWidgets('switching back to Near Me returns to 65km', (tester) async {
      await tester.pumpWidget(_host());
      await tester.pumpAndSettle();
      await _tap(tester, const Key('radius_travel'));
      await _tap(tester, const Key('radius_near_me'));

      expect(_radiusOf(requests.last), '65.0');
    });

    testWidgets('the origin goes with it — a radius alone means nothing',
        (tester) async {
      await tester.pumpWidget(_host());
      await tester.pumpAndSettle();

      final q = requests.first;
      expect(q['lat']?.first, isNotNull);
      expect(q['lng']?.first, isNotNull);
    });
  });

  group('radius and city are mutually exclusive', () {
    testWidgets('arriving with cities starts in city mode, NOT Near Me',
        (tester) async {
      // Defaulting over an explicit choice would discard what the customer
      // just picked on the previous screen.
      await tester.pumpWidget(_host(cities: {'Chennai'}));
      await tester.pumpAndSettle();

      expect(_radiusOf(requests.first), isNull,
          reason: 'a picked city must not be silently overridden by a radius');
      expect(_citiesOf(requests.first), contains('Chennai'));
    });

    testWidgets('choosing a radius clears the city filter', (tester) async {
      await tester.pumpWidget(_host(cities: {'Chennai'}));
      await tester.pumpAndSettle();
      await _tap(tester, const Key('radius_near_me'));

      expect(_radiusOf(requests.last), '65.0');
      expect(_citiesOf(requests.last), isEmpty,
          reason: 'the city filter must not survive switching to a radius');
    });

    testWidgets('Travel also clears the city filter', (tester) async {
      await tester.pumpWidget(_host(cities: {'Kochi', 'Kolkata'}));
      await tester.pumpAndSettle();
      await _tap(tester, const Key('radius_travel'));

      expect(_radiusOf(requests.last), '300.0');
      expect(_citiesOf(requests.last), isEmpty);
    });
  });

  group('the control tells the truth about what is applied', () {
    testWidgets('both options are always offered', (tester) async {
      await tester.pumpWidget(_host());
      await tester.pumpAndSettle();

      expect(find.byKey(const Key('radius_near_me')), findsOneWidget);
      expect(find.byKey(const Key('radius_travel')), findsOneWidget);
    });

    testWidgets('the active radius is stated, not left to be inferred',
        (tester) async {
      await tester.pumpWidget(_host());
      await tester.pumpAndSettle();
      expect(find.text('within 65 km'), findsOneWidget);

      await _tap(tester, const Key('radius_travel'));
      expect(find.text('within 300 km'), findsOneWidget);
      expect(find.text('within 65 km'), findsNothing);
    });

    testWidgets('in city mode NEITHER option claims to be selected',
        (tester) async {
      // A control that always shows a selection would misrepresent the filter.
      await tester.pumpWidget(_host(cities: {'Chennai'}));
      await tester.pumpAndSettle();

      expect(find.textContaining('within'), findsNothing);
    });
  });
}
