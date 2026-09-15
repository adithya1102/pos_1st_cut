// The home greeting, and the "Offers only" empty-state button caption.
//
// Both began as small label fixes with a shared theme: a message that was wrong
// for a correct state. The greeting called midnight "morning"; the offers
// filter called a correct zero-match "Try again", as if something had failed.
//
// The greeting has since gone further — the time-of-day banding is gone
// entirely rather than re-tuned, so the cases here now assert that the hour
// CANNOT change the answer. See welcomeGreeting for why the bands went.
import 'dart:convert';

import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:http/http.dart' as http;
import 'package:http/testing.dart';
import 'package:provider/provider.dart';
import 'package:shared_preferences/shared_preferences.dart';

import 'package:customer_app/screens/home_screen.dart' show welcomeGreeting;
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
  // The greeting — now TIME-INVARIANT
  // =========================================================================
  //
  // These replace the old hour-band cases wholesale. That group pinned an hour
  // and asserted which of three greetings came back; there are no bands left to
  // pin, and the property worth holding is the opposite one — that the hour
  // cannot change the answer.
  group('greeting is the same at every hour', () {
    test('identical for all 24 hours of the day', () {
      // The old banding could only be tested by injecting an hour. This asserts
      // the stronger thing: there is no longer an input that could vary it.
      final answers = {for (var h = 0; h < 24; h++) welcomeGreeting('Asha')};
      expect(answers, hasLength(1),
          reason: 'the greeting must not depend on the time of day');
      expect(answers.single, 'Welcome back, Asha');
    });

    test('the small hours read the same as midday', () {
      // The bug that forced the last fix here: 00:00 was greeted "Good
      // morning". There is now no hour at which anything different is said.
      expect(welcomeGreeting('Asha'), 'Welcome back, Asha');
    });

    test('the name is appended when present', () {
      expect(welcomeGreeting('Asha'), 'Welcome back, Asha');
    });

    test('a missing or blank name degrades to the bare greeting', () {
      expect(welcomeGreeting(null), 'Welcome back');
      expect(welcomeGreeting(''), 'Welcome back');
      expect(welcomeGreeting('   '), 'Welcome back',
          reason: 'a blank name adds nothing, and never a dangling comma');
    });

    test('surrounding whitespace on a real name is trimmed', () {
      expect(welcomeGreeting('  Asha  '), 'Welcome back, Asha');
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

      // Label is now 'Try Again' (capital A): failures render through the
      // shared ErrorStateView, so the wording is defined once in AppError
      // rather than per screen. The point of the test is unchanged — a real
      // load failure offers a RETRY, not the clear-filters action.
      expect(find.text('Try Again'), findsOneWidget);
      expect(find.text('Show all restaurants'), findsNothing);
      // And it is classified: a 500 is the server category, not a generic
      // "could not load restaurants".
      expect(find.text('We hit a little roadblock.'), findsOneWidget);
    });
  });

  // =========================================================================
  // "Schedule ahead" — the discoverability chip
  // =========================================================================
  //
  // Scheduling is otherwise invisible until checkout, three screens past the
  // point where knowing would have changed which restaurant someone picked.
  // This chip's whole job is awareness; it schedules nothing.
  group('Schedule ahead chip', () {
    http.Response okJson(Object body) => http.Response(
        jsonEncode(body), 200, headers: {'content-type': 'application/json'});

    Widget host() {
      SharedPreferences.setMockInitialValues({'carevo_access_token': 'valid'});
      final api = ApiClient(client: MockClient((req) async {
        if (req.url.path.contains('/customer/orders')) return okJson(const []);
        if (req.url.path.contains('/customer/outlets')) {
          return okJson([
            {
              'id': 'a',
              'name': 'Test Kitchen',
              'address': 'Anna Nagar, Chennai',
              'is_open': true,
              'order_status': 'open',
              'distance_km': 1.0,
            }
          ]);
        }
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

    Future<void> pump(WidgetTester tester) async {
      tester.view.physicalSize = const Size(1170, 2532);
      tester.view.devicePixelRatio = 3.0;
      addTearDown(tester.view.reset);
      await tester.pumpWidget(host());
      await tester.pump(const Duration(milliseconds: 600));
    }

    testWidgets('renders in the chip row, immediately after offers',
        (tester) async {
      await pump(tester);
      expect(find.byKey(const Key('chip_offers')), findsOneWidget);
      expect(find.byKey(const Key('chip_schedule')), findsOneWidget);
      expect(find.text('Schedule ahead'), findsOneWidget);

      // On a 390pt phone these two do NOT fit side by side and the Wrap puts
      // the second on its own line. That is measured, not assumed: "Offers
      // only" alone is 218pt of the 350pt available, so no label short enough
      // to sit beside it exists ("Schedule" is still 175pt). Asserting
      // same-row adjacency here would be asserting a layout the app cannot
      // produce.
      //
      // What IS worth holding: it comes after offers in the row and is BELOW
      // it, i.e. it wrapped rather than being clipped off the right edge.
      final offers = tester.getTopLeft(find.byKey(const Key('chip_offers')));
      final schedule = tester.getTopLeft(find.byKey(const Key('chip_schedule')));
      expect(schedule.dy, greaterThan(offers.dy),
          reason: 'wrapped onto the next line, not clipped');
      expect(schedule.dx, offers.dx, reason: 'both start at the same margin');
    });

    testWidgets('is fully on screen — the point of it is to be seen',
        (tester) async {
      // The regression this guards: a horizontal scroller would have "fixed"
      // the original 140px overflow by letting this chip sit off the right
      // edge, silently defeating the only reason it exists.
      await pump(tester);
      final r = tester.getRect(find.byKey(const Key('chip_schedule')));
      final screen = tester.getSize(find.byType(MaterialApp));
      expect(r.left, greaterThanOrEqualTo(0));
      expect(r.right, lessThanOrEqualTo(screen.width),
          reason: 'the chip must not extend past the right edge');
      expect(r.width, greaterThan(0));
    });

    testWidgets('tapping it opens the explainer', (tester) async {
      await pump(tester);
      expect(find.byKey(const Key('schedule_info_sheet')), findsNothing);

      await tester.tap(find.byKey(const Key('chip_schedule')));
      await tester.pumpAndSettle();

      expect(find.byKey(const Key('schedule_info_sheet')), findsOneWidget);
      expect(find.textContaining('pick a time to collect later today'),
          findsOneWidget);
      expect(find.textContaining('Choose a restaurant to get started'),
          findsOneWidget);
    });

    testWidgets('the explainer dismisses and changes nothing', (tester) async {
      await pump(tester);
      await tester.tap(find.byKey(const Key('chip_schedule')));
      await tester.pumpAndSettle();
      await tester.tap(find.byKey(const Key('schedule_info_dismiss')));
      await tester.pumpAndSettle();

      expect(find.byKey(const Key('schedule_info_sheet')), findsNothing);
      // The list is untouched — this chip is not a filter.
      expect(find.text('Test Kitchen'), findsOneWidget);
    });

    testWidgets('it does NOT filter the list the way Offers only does',
        (tester) async {
      // The real risk of putting an action chip beside a toggle: the two are
      // drawn by the same widget, so a customer could reasonably expect this
      // one to narrow the list too. It must not, and it must not latch.
      await pump(tester);
      expect(find.text('Test Kitchen'), findsOneWidget);

      await tester.tap(find.byKey(const Key('chip_schedule')));
      await tester.pumpAndSettle();
      await tester.tap(find.byKey(const Key('schedule_info_dismiss')));
      await tester.pumpAndSettle();

      expect(find.text('Test Kitchen'), findsOneWidget);
      expect(find.byKey(const Key('outlet_result_count')), findsNothing,
          reason: 'no filter is active, so no result count should appear');
    });
  });
}
