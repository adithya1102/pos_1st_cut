// Task 3 — the time-of-day greeting.
// Task 4 — the "Offers only" empty-state button caption.
//
// Both are small label fixes with a shared theme: a message that was wrong for
// a correct state. The greeting called midnight "morning"; the offers filter
// called a correct zero-match "Try again", as if something had failed.
import 'dart:convert';

import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:http/http.dart' as http;
import 'package:http/testing.dart';
import 'package:provider/provider.dart';
import 'package:shared_preferences/shared_preferences.dart';

import 'package:customer_app/screens/home_screen.dart' show greetingFor;
import 'package:customer_app/screens/outlets_screen.dart';
import 'package:customer_app/services/api_client.dart';
import 'package:customer_app/services/catalog_service.dart';
import 'package:customer_app/services/customer_service.dart';
import 'package:customer_app/services/location_service.dart';
import 'package:customer_app/state/cart_state.dart';
import 'package:customer_app/theme/app_theme.dart';
import 'package:customer_app/theme/theme_provider.dart';

void main() {
  // =========================================================================
  // Task 3 — greeting bands (pure, so the hour is pinned rather than "now")
  // =========================================================================
  group('greeting matches the local hour', () {
    test('midnight and the small hours are NOT "Good morning"', () {
      // The reported bug: opening the app at 00:00 said "Good morning".
      for (final h in [0, 1, 2, 3, 4]) {
        expect(greetingFor(h, null), 'Good evening',
            reason: 'hour $h is late night, not morning');
      }
    });

    test('morning is 05:00–11:59', () {
      expect(greetingFor(5, null), 'Good morning');
      expect(greetingFor(9, null), 'Good morning');
      expect(greetingFor(11, null), 'Good morning');
    });

    test('afternoon is 12:00–16:59', () {
      expect(greetingFor(12, null), 'Good afternoon');
      expect(greetingFor(16, null), 'Good afternoon');
    });

    test('evening is 17:00 onward', () {
      expect(greetingFor(17, null), 'Good evening');
      expect(greetingFor(21, null), 'Good evening');
      expect(greetingFor(23, null), 'Good evening');
    });

    test('the name is appended when present', () {
      expect(greetingFor(9, 'Asha'), 'Good morning, Asha');
      expect(greetingFor(0, '  '), 'Good evening',
          reason: 'a blank name adds nothing');
    });
  });

  // =========================================================================
  // Task 4 — offers-filter empty state button
  // =========================================================================
  group('offers-only zero matches offers "Show all", not "Try again"', () {
    http.Response okJson(Object body) => http.Response(
        jsonEncode(body), 200, headers: {'content-type': 'application/json'});

    Map<String, dynamic> outletJson({int offerCount = 0, String? offerText}) => {
          'id': 'a',
          'name': 'Test Kitchen',
          'address': 'Anna Nagar, Chennai',
          'is_open': true,
          'distance_km': 1.0,
          'offer_count': offerCount,
          'offer_text': offerText,
        };

    Widget host(List<Map<String, dynamic>> outlets) {
      SharedPreferences.setMockInitialValues({'carevo_access_token': 'valid'});
      final api = ApiClient(client: MockClient((req) async {
        if (req.url.path.contains('/customer/orders')) return okJson(const []);
        if (req.url.path.contains('/customer/outlets')) return okJson(outlets);
        return okJson(const []);
      }));
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

    testWidgets('the empty-state button reads "Show all restaurants"',
        (tester) async {
      tester.view.physicalSize = const Size(1170, 2532);
      tester.view.devicePixelRatio = 3.0;
      addTearDown(tester.view.reset);

      // One restaurant, and it has NO offer — so "Offers only" matches zero.
      await tester.pumpWidget(host([outletJson(offerCount: 0)]));
      await tester.pump(const Duration(milliseconds: 600));
      expect(find.text('Test Kitchen'), findsOneWidget);

      await tester.tap(find.byKey(const Key('chip_offers')));
      await tester.pump(const Duration(milliseconds: 300));

      // The filter WORKED and returned nothing — nothing failed.
      expect(find.text('No restaurants match those filters.'), findsOneWidget);
      expect(find.text('Show all restaurants'), findsOneWidget);
      expect(find.text('Try again'), findsNothing,
          reason: 'nothing failed, so "Try again" is the wrong caption');
    });

    testWidgets('tapping it clears the filter and shows the restaurants again',
        (tester) async {
      tester.view.physicalSize = const Size(1170, 2532);
      tester.view.devicePixelRatio = 3.0;
      addTearDown(tester.view.reset);

      await tester.pumpWidget(host([outletJson(offerCount: 0)]));
      await tester.pump(const Duration(milliseconds: 600));
      await tester.tap(find.byKey(const Key('chip_offers')));
      await tester.pump(const Duration(milliseconds: 300));
      expect(find.text('Test Kitchen'), findsNothing);

      await tester.tap(find.text('Show all restaurants'));
      await tester.pump(const Duration(milliseconds: 300));

      // Same underlying action as before — the restaurant is back.
      expect(find.text('Test Kitchen'), findsOneWidget);
      expect(find.text('No restaurants match those filters.'), findsNothing);
    });

    testWidgets('a genuine load failure still says "Try again"', (tester) async {
      // The rename must be scoped to the empty-filter case: a real error is
      // still a retry.
      tester.view.physicalSize = const Size(1170, 2532);
      tester.view.devicePixelRatio = 3.0;
      addTearDown(tester.view.reset);

      SharedPreferences.setMockInitialValues({'carevo_access_token': 'valid'});
      final api = ApiClient(client: MockClient((req) async {
        if (req.url.path.contains('/customer/orders')) {
          return http.Response(jsonEncode(const []), 200,
              headers: {'content-type': 'application/json'});
        }
        // Outlets fail to load.
        return http.Response(jsonEncode({'detail': 'boom'}), 500,
            headers: {'content-type': 'application/json'});
      }));
      await tester.pumpWidget(MultiProvider(
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
      ));
      await tester.pump(const Duration(milliseconds: 600));

      expect(find.text('Try again'), findsOneWidget);
      expect(find.text('Show all restaurants'), findsNothing);
    });
  });
}
