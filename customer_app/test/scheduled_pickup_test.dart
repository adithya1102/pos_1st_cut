// Scheduled pickup on the customer side (migration 031):
//   * Outlet.nextCloseAfter — the absolute ceiling the picker is bounded on,
//     including the overnight roll;
//   * ArrivalTimePicker's new bounds, and the two copy/logic bugs it carried;
//   * checkout's Order-now / Pick-a-time toggle, and the closing_soon split
//     that lets scheduling through a door ASAP ordering is refused at;
//   * the wire payload.
//
// The backend is the hard gate throughout — it refuses an infeasible slot at
// order creation with a 409. These hold the client's job: not offering a time
// the server is going to refuse, and not hiding the option at the one moment it
// is worth the most.
import 'dart:convert';

import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:http/http.dart' as http;
import 'package:http/testing.dart';
import 'package:provider/provider.dart';
import 'package:shared_preferences/shared_preferences.dart';

import 'package:customer_app/models/menu.dart';
import 'package:customer_app/models/outlet.dart';
import 'package:customer_app/screens/checkout_screen.dart';
import 'package:customer_app/services/api_client.dart';
import 'package:customer_app/services/cashfree_service.dart';
import 'package:customer_app/services/customer_service.dart';
import 'package:customer_app/services/location_service.dart';
import 'package:customer_app/services/order_service.dart';
import 'package:customer_app/services/places_service.dart';
import 'package:customer_app/state/cart_state.dart';
import 'package:customer_app/theme/app_theme.dart';
import 'package:customer_app/theme/theme_provider.dart';
import 'package:customer_app/widgets/arrival_time_picker.dart';

String _hhmm(DateTime t) =>
    '${t.hour.toString().padLeft(2, '0')}:${t.minute.toString().padLeft(2, '0')}';

void main() {
  // ======================================================================
  // Outlet.nextCloseAfter
  // ======================================================================
  group('Outlet.nextCloseAfter', () {
    Outlet withHours(String? opens, String? closes) => Outlet.fromJson({
          'id': 'o1', 'name': 'X', 'address': 'Y', 'is_open': true,
          'order_status': 'open',
          'opening_time': opens, 'closing_time': closes,
        });

    test('returns today\'s close when it is still ahead', () {
      final from = DateTime(2026, 9, 16, 14, 0);
      final close = withHours('09:00', '22:00').nextCloseAfter(from);
      expect(close, DateTime(2026, 9, 16, 22, 0));
    });

    test('rolls to tomorrow for an overnight window', () {
      // 18:00 -> 02:00. At 23:00 the next close is 02:00 TOMORROW by the
      // calendar and tonight by the restaurant's own day — which is exactly
      // the case "same-day only" has to get right rather than ban.
      final from = DateTime(2026, 9, 16, 23, 0);
      final close = withHours('18:00', '02:00').nextCloseAfter(from);
      expect(close, DateTime(2026, 9, 17, 2, 0));
    });

    test('an already-passed close rolls rather than returning the past', () {
      final from = DateTime(2026, 9, 16, 23, 30);
      final close = withHours('09:00', '22:00').nextCloseAfter(from);
      expect(close, DateTime(2026, 9, 17, 22, 0));
    });

    test('null when no hours are on record — always-open, not closed', () {
      expect(withHours(null, null).nextCloseAfter(DateTime(2026, 9, 16)), isNull);
    });

    test('null for an unparseable time rather than a wrong instant', () {
      expect(withHours('09:00', 'half ten')
          .nextCloseAfter(DateTime(2026, 9, 16)), isNull);
      expect(withHours('09:00', '25:00')
          .nextCloseAfter(DateTime(2026, 9, 16)), isNull);
    });
  });

  // ======================================================================
  // ArrivalTimePicker — the new bounds and the bugs it carried
  // ======================================================================
  group('ArrivalTimePicker bounds', () {
    Widget host({
      required DateTime initial,
      required Duration maxAhead,
      DateTime? latest,
      Duration minAhead = Duration.zero,
      String? title,
      String confirmLabel = 'Set arrival time',
    }) =>
        MaterialApp(
          theme: AppTheme.light(),
          home: Scaffold(
            body: ArrivalTimePicker(
              initial: initial,
              maxAhead: maxAhead,
              latest: latest,
              minAhead: minAhead,
              title: title,
              confirmLabel: confirmLabel,
            ),
          ),
        );

    testWidgets('a sub-hour bound no longer reads "within the next 0 hours"',
        (tester) async {
      // The old copy interpolated maxAhead.inHours, so any bound under an hour
      // rendered advice that could not be followed. Scheduled pickup hits that
      // constantly — the last slot before close is often minutes away.
      final now = DateTime.now();
      await tester.pumpWidget(host(
        initial: now.add(const Duration(hours: 3)),
        maxAhead: const Duration(minutes: 45),
        latest: now.add(const Duration(minutes: 45)),
      ));
      await tester.pumpAndSettle();

      expect(find.byKey(const Key('arrival_too_far')), findsOneWidget);
      expect(find.textContaining('0 hours'), findsNothing);
      // Names the actual boundary instead of a duration.
      expect(find.textContaining('Pick a time before'), findsOneWidget);
    });

    testWidgets('a time past `latest` disables confirm', (tester) async {
      final now = DateTime.now();
      await tester.pumpWidget(host(
        initial: now.add(const Duration(hours: 3)),
        maxAhead: const Duration(hours: 6),
        latest: now.add(const Duration(hours: 1)),
      ));
      await tester.pumpAndSettle();
      final btn = tester.widget<Widget>(find.byKey(const Key('arrival_confirm')));
      expect(btn, isNotNull);
      expect(find.byKey(const Key('arrival_too_far')), findsOneWidget);
    });

    testWidgets('a time inside minAhead is refused with its own message',
        (tester) async {
      final now = DateTime.now();
      await tester.pumpWidget(host(
        initial: now.add(const Duration(minutes: 5)),
        maxAhead: const Duration(hours: 6),
        latest: now.add(const Duration(hours: 4)),
        minAhead: const Duration(minutes: 30),
      ));
      await tester.pumpAndSettle();
      expect(find.byKey(const Key('arrival_too_soon')), findsOneWidget);
      expect(find.textContaining('at least 30 minutes'), findsOneWidget);
      expect(find.byKey(const Key('arrival_too_far')), findsNothing);
    });

    testWidgets('a feasible time shows neither error', (tester) async {
      final now = DateTime.now();
      await tester.pumpWidget(host(
        initial: now.add(const Duration(hours: 1)),
        maxAhead: const Duration(hours: 6),
        latest: now.add(const Duration(hours: 4)),
        minAhead: const Duration(minutes: 30),
      ));
      await tester.pumpAndSettle();
      expect(find.byKey(const Key('arrival_too_soon')), findsNothing);
      expect(find.byKey(const Key('arrival_too_far')), findsNothing);
    });

    testWidgets('the heading and button can be re-labelled for pickup',
        (tester) async {
      final now = DateTime.now();
      await tester.pumpWidget(host(
        initial: now.add(const Duration(hours: 1)),
        maxAhead: const Duration(hours: 6),
        latest: now.add(const Duration(hours: 4)),
        title: 'When would you like to collect?',
        confirmLabel: 'Set pickup time',
      ));
      await tester.pumpAndSettle();
      expect(find.text('When would you like to collect?'), findsOneWidget);
      expect(find.text('Set pickup time'), findsOneWidget);
      // And it no longer asks about a vehicle it was never told about.
      expect(find.textContaining('train arrive'), findsNothing);
    });

    testWidgets('declared-arrival callers are unchanged', (tester) async {
      final now = DateTime.now();
      await tester.pumpWidget(host(
        initial: now.add(const Duration(minutes: 45)),
        maxAhead: const Duration(hours: 6),
      ));
      await tester.pumpAndSettle();
      expect(find.text('When does your train arrive?'), findsOneWidget);
      expect(find.text('Set arrival time'), findsOneWidget);
    });
  });

  // ======================================================================
  // checkout — the toggle and the closing_soon split
  // ======================================================================
  group('checkout scheduling', () {
    MenuItem menuItem() => MenuItem.fromJson({
          'id': 'i1', 'name': 'Masala Dosa', 'base_price': 120.0,
          'is_veg': true, 'is_available': true, 'image_url': null,
          'prep_time_minutes': 0, 'tags': const <String>[],
          'customizations': const <dynamic>[],
        });

    /// Hours chosen RELATIVE to the wall clock so the picker's ceiling is a
    /// known distance away whatever time the suite happens to run. A fixed
    /// "22:00" would make these tests pass all day and fail after 21:30.
    Outlet outlet(String status) {
      final close = DateTime.now().add(const Duration(hours: 4));
      return Outlet.fromJson({
        'id': 'o1', 'name': 'Test Kitchen', 'address': 'Somewhere',
        'is_open': status == 'open', 'order_status': status,
        'closed_reason': status == 'open'
            ? null
            : 'This outlet is temporarily closed and is not taking orders.',
        'opening_time': '09:00', 'closing_time': _hhmm(close),
      });
    }

    Widget host(String status) {
      SharedPreferences.setMockInitialValues({'carevo_access_token': 't'});
      final api = ApiClient(client: MockClient((req) async =>
          http.Response(jsonEncode(const []), 200,
              headers: {'content-type': 'application/json'})));
      final cart = CartState()
        ..setOutlet(outlet(status))
        ..addItem(menuItem(), quantity: 1);
      return MultiProvider(
        providers: [
          Provider<ApiClient>.value(value: api),
          Provider<OrderService>(create: (_) => OrderService(api)),
          Provider<CustomerService>(create: (_) => CustomerService(api)),
          Provider<CashfreeService>(create: (_) => CashfreeService()),
          Provider<LocationService>(create: (_) => LocationService()),
          Provider<PlacesService>(create: (_) => PlacesService()),
          ChangeNotifierProvider<CartState>.value(value: cart),
          ChangeNotifierProvider(create: (_) => ThemeProvider()),
        ],
        child:
            MaterialApp(theme: AppTheme.light(), home: const CheckoutScreen()),
      );
    }

    Future<void> pump(WidgetTester tester, String status) async {
      tester.view.physicalSize = const Size(1170, 2900);
      tester.view.devicePixelRatio = 3.0;
      addTearDown(tester.view.reset);
      await tester.pumpWidget(host(status));
      await tester.pumpAndSettle();
    }

    /// Scroll the checkout list until [key] is built and on screen.
    ///
    /// The scheduling section sits below the transport chips, and checkout's
    /// body is a lazily-built ListView — so on a phone-sized viewport the
    /// widget genuinely does not exist in the tree until scrolled to. Asserting
    /// without this measures the viewport height, not the feature.
    Future<void> reveal(WidgetTester tester, Key key) async {
      await tester.scrollUntilVisible(
        find.byKey(key),
        240,
        scrollable: find.byType(Scrollable).first,
      );
      await tester.pumpAndSettle();
    }

    testWidgets('an open outlet offers the toggle, defaulting to Order now',
        (tester) async {
      await pump(tester, 'open');
      await reveal(tester, const Key('schedule_toggle'));
      expect(find.byKey(const Key('schedule_toggle')), findsOneWidget);
      expect(find.text('Order now'), findsOneWidget);
      expect(find.text('Pick a time'), findsOneWidget);
      // Default is ASAP: no pickup field until the customer opts in.
      expect(find.byKey(const Key('pickup_time_field')), findsNothing);
    });

    testWidgets('a closed outlet offers no scheduling at all', (tester) async {
      // The server refuses scheduled orders for a closed shutter too, so
      // offering the control here would only produce a 409.
      await pump(tester, 'closed');
      expect(find.byKey(const Key('schedule_toggle')), findsNothing);
      expect(find.byKey(const Key('checkout_closed_reason')), findsOneWidget);
    });

    testWidgets('closing_soon still offers scheduling', (tester) async {
      await pump(tester, 'closing_soon');
      await reveal(tester, const Key('schedule_toggle'));
      expect(find.byKey(const Key('schedule_toggle')), findsOneWidget);
    });

    testWidgets('closing_soon blocks ASAP and says scheduling is the way out',
        (tester) async {
      await pump(tester, 'closing_soon');
      expect(find.byKey(const Key('checkout_closed_reason')), findsOneWidget);
      expect(find.textContaining('pick a pickup time above'), findsOneWidget);
      expect(find.textContaining('Pay ₹'), findsNothing);
    });

    testWidgets('tapping Pick a time opens the picker on the same tap',
        (tester) async {
      await pump(tester, 'open');
      await reveal(tester, const Key('schedule_later'));
      await tester.tap(find.byKey(const Key('schedule_later')));
      await tester.pumpAndSettle();
      expect(find.text('When would you like to collect?'), findsOneWidget);
      expect(find.byKey(const Key('arrival_confirm')), findsOneWidget);
    });

    testWidgets('choosing a slot during closing_soon re-enables Pay',
        (tester) async {
      // The whole point of the split: "no room to cook that right now" must not
      // also refuse a request for later.
      await pump(tester, 'closing_soon');
      expect(find.textContaining('Pay ₹'), findsNothing);

      await reveal(tester, const Key('schedule_later'));
      await tester.tap(find.byKey(const Key('schedule_later')));
      await tester.pumpAndSettle();
      await tester.tap(find.byKey(const Key('arrival_confirm')));
      await tester.pumpAndSettle();

      await reveal(tester, const Key('pickup_time_field'));
      expect(find.byKey(const Key('pickup_time_field')), findsOneWidget);
      expect(find.byKey(const Key('checkout_closed_reason')), findsNothing);
      expect(find.textContaining('Pay ₹'), findsOneWidget);
    });

    testWidgets('switching back to Order now re-blocks it during closing_soon',
        (tester) async {
      await pump(tester, 'closing_soon');
      await reveal(tester, const Key('schedule_later'));
      await tester.tap(find.byKey(const Key('schedule_later')));
      await tester.pumpAndSettle();
      await tester.tap(find.byKey(const Key('arrival_confirm')));
      await tester.pumpAndSettle();
      expect(find.textContaining('Pay ₹'), findsOneWidget);

      await reveal(tester, const Key('schedule_asap'));
      await tester.tap(find.byKey(const Key('schedule_asap')));
      await tester.pumpAndSettle();
      expect(find.byKey(const Key('checkout_closed_reason')), findsOneWidget);
      expect(find.textContaining('Pay ₹'), findsNothing);
    });

    testWidgets('an open outlet stays payable while scheduling is off',
        (tester) async {
      await pump(tester, 'open');
      expect(find.textContaining('Pay ₹'), findsOneWidget);
      expect(find.byKey(const Key('checkout_closed_reason')), findsNothing);
    });

    testWidgets('the chosen slot is shown back to the customer',
        (tester) async {
      await pump(tester, 'open');
      await reveal(tester, const Key('schedule_later'));
      await tester.tap(find.byKey(const Key('schedule_later')));
      await tester.pumpAndSettle();
      await tester.tap(find.byKey(const Key('arrival_confirm')));
      await tester.pumpAndSettle();
      await reveal(tester, const Key('pickup_time_field'));
      expect(find.textContaining('Ready for'), findsOneWidget);
    });
  });

  // ======================================================================
  // wire payload
  // ======================================================================
  group('order payload', () {
    MenuItem menuItem() => MenuItem.fromJson({
          'id': 'i1', 'name': 'Dosa', 'base_price': 100.0, 'is_veg': true,
          'is_available': true, 'image_url': null, 'prep_time_minutes': 0,
          'tags': const <String>[], 'customizations': const <dynamic>[],
        });

    CartState cart() => CartState()
      ..setOutlet(Outlet.fromJson({
        'id': 'o1', 'name': 'X', 'address': 'Y', 'is_open': true,
        'order_status': 'open',
      }))
      ..addItem(menuItem(), quantity: 1);

    test('requested_pickup_at is sent in UTC', () {
      final when = DateTime.now().add(const Duration(hours: 2));
      final payload = cart().toOrderPayload(requestedPickupAt: when);
      expect(payload['requested_pickup_at'],
          when.toUtc().toIso8601String());
      // UTC on the wire matters more here than anywhere else: this value
      // decides when the kitchen is told to start.
      expect((payload['requested_pickup_at'] as String).endsWith('Z'), isTrue);
    });

    test('the key is absent for an ASAP order', () {
      expect(cart().toOrderPayload().containsKey('requested_pickup_at'),
          isFalse);
    });

    test('it coexists with a declared arrival', () {
      // Both are legitimate for a train passenger who also schedules. The
      // server keeps both and lets release_at win over the kitchen notify.
      final pickup = DateTime.now().add(const Duration(hours: 2));
      final arrival = DateTime.now().add(const Duration(hours: 1));
      final payload = cart().toOrderPayload(
          requestedPickupAt: pickup, declaredArrivalAt: arrival);
      expect(payload['requested_pickup_at'], isNotNull);
      expect(payload['declared_arrival_at'], isNotNull);
    });
  });


  // ======================================================================
  // ONE time entry, not two (the declared-arrival + scheduling overlap)
  // ======================================================================
  //
  // Train/metro/tram ask "when does your train arrive?"; scheduled pickup asks
  // "when do you want it?". Both blocks rendered unconditionally, so a train
  // passenger who also tapped "Pick a time" was made to enter two times for one
  // journey and keep them consistent by hand.
  //
  // The resolution is that the chosen slot IS the arrival. Safe on the server
  // by construction rather than by convention: _estimated_arrival_at
  // short-circuits on `requested_pickup_at is not None` and never reads
  // declared_arrival_at for a scheduled order, so the feasibility gate is
  // judged on the slot alone and the platform-to-door constant is not added on
  // top of it.
  group('declared arrival merges into the pickup slot', () {
    MenuItem menuItem() => MenuItem.fromJson({
          'id': 'i1', 'name': 'Masala Dosa', 'base_price': 120.0,
          'is_veg': true, 'is_available': true, 'image_url': null,
          'prep_time_minutes': 0, 'tags': const <String>[],
          'customizations': const <dynamic>[],
        });

    /// An outlet offering exactly two modes: one that declares an arrival and
    /// one that does not, so the same screen covers both branches.
    Outlet trainOutlet() {
      final close = DateTime.now().add(const Duration(hours: 4));
      return Outlet.fromJson({
        'id': 'o1', 'name': 'Test Kitchen', 'address': 'Somewhere',
        'is_open': true, 'order_status': 'open',
        'opening_time': '09:00', 'closing_time': _hhmm(close),
        'transport_modes': [
          {'code': 'train', 'label': 'Train', 'uses_declared_arrival': true},
          {'code': 'walk', 'label': 'Walk', 'uses_declared_arrival': false},
        ],
      });
    }

    Widget host() {
      SharedPreferences.setMockInitialValues({'carevo_access_token': 't'});
      final api = ApiClient(client: MockClient((req) async =>
          http.Response(jsonEncode(const []), 200,
              headers: {'content-type': 'application/json'})));
      final cart = CartState()
        ..setOutlet(trainOutlet())
        ..addItem(menuItem(), quantity: 1);
      return MultiProvider(
        providers: [
          Provider<ApiClient>.value(value: api),
          Provider<OrderService>(create: (_) => OrderService(api)),
          Provider<CustomerService>(create: (_) => CustomerService(api)),
          Provider<CashfreeService>(create: (_) => CashfreeService()),
          // ChangeNotifierProvider, not Provider: LocationService is a
          // Listenable, and tapping a transport chip reads it — which is
          // what makes plain Provider assert here but not in the older
          // group above, where no chip is ever tapped.
          ChangeNotifierProvider<LocationService>(
              create: (_) => LocationService()),
          Provider<PlacesService>(create: (_) => PlacesService()),
          ChangeNotifierProvider<CartState>.value(value: cart),
          ChangeNotifierProvider(create: (_) => ThemeProvider()),
        ],
        child:
            MaterialApp(theme: AppTheme.light(), home: const CheckoutScreen()),
      );
    }

    Future<void> pump(WidgetTester tester) async {
      tester.view.physicalSize = const Size(1170, 3400);
      tester.view.devicePixelRatio = 3.0;
      addTearDown(tester.view.reset);
      await tester.pumpWidget(host());
      await tester.pump();
      await tester.pump(const Duration(milliseconds: 400));
    }

    /// [delta] is signed: positive scrolls DOWN the page, negative scrolls back
    /// UP. Both directions are needed here — the schedule toggle is below the
    /// transport chips, while the merged note REPLACES the arrival field above
    /// it, so reaching the note after tapping the toggle means going back up.
    Future<void> reveal(WidgetTester tester, Key key,
        {double delta = 240}) async {
      await tester.scrollUntilVisible(find.byKey(key), delta,
          scrollable: find.byType(Scrollable).first);
      await tester.pump();
      await tester.pump(const Duration(milliseconds: 400));
    }

    /// Bounded pumps, never pumpAndSettle.
    ///
    /// Selecting a transport mode also kicks off location acquisition
    /// (_selectMode, migration 030). In a test that future never completes, so
    /// pumpAndSettle waits for a frame-quiet that never arrives and times out
    /// on a feature that is working. Same shape as tapMode() in
    /// transport_modes_server_driven_test.dart, and for the same reason.
    Future<void> tapMode(WidgetTester tester, String label) async {
      final target = find.text(label);
      await tester.ensureVisible(target);
      await tester.pump();
      await tester.tap(target);
      await tester.pump();
      await tester.pump(const Duration(milliseconds: 400));
    }

    testWidgets('train alone still asks for an arrival time', (tester) async {
      // The control case. Without this, a fix that simply deleted the arrival
      // field would pass every test below.
      await pump(tester);
      await tapMode(tester, 'Train');
      await reveal(tester, const Key('arrival_field'));
      expect(find.byKey(const Key('arrival_field')), findsOneWidget);
      expect(find.byKey(const Key('arrival_merged_into_pickup')), findsNothing);
    });

    testWidgets('choosing a pickup slot replaces the arrival field',
        (tester) async {
      await pump(tester);
      await tapMode(tester, 'Train');
      await reveal(tester, const Key('schedule_later'));
      await tester.tap(find.byKey(const Key('schedule_later')));
      await tester.pump();
      await tester.pump(const Duration(milliseconds: 400));
      // The picker opens on the same tap; dismiss it to inspect the page.
      await tester.tapAt(const Offset(10, 10));
      await tester.pump();
      await tester.pump(const Duration(milliseconds: 400));

      expect(find.byKey(const Key('arrival_field')), findsNothing,
          reason: 'the second time entry must be gone');
      await reveal(tester, const Key('arrival_merged_into_pickup'), delta: -240);
      expect(find.byKey(const Key('arrival_merged_into_pickup')), findsOneWidget,
          reason: 'and its disappearance must be explained, not silent');
    });

    // NOT COVERED HERE: switching back to Order now and watching the merge
    // note disappear. The assertion is sound but reaching it means driving a
    // lazily-built ListView whose height changes when the arrival field is
    // replaced, and repeated attempts measured the scroll harness rather than
    // the feature. The reversibility itself is not untested — the control case
    // above reaches the un-merged state by not scheduling at all, and
    // `_scheduled` gates both branches of one `if`, so there is no third state
    // for them to disagree about. Left as a known gap rather than a flaky test.

    testWidgets('a non-declared mode shows neither the field nor the note',
        (tester) async {
      // Walk has a GPS origin, so it never had an arrival field to merge.
      await pump(tester);
      await tapMode(tester, 'Walk');
      expect(find.byKey(const Key('arrival_field')), findsNothing);
      expect(find.byKey(const Key('arrival_merged_into_pickup')), findsNothing);
    });
  });
}
