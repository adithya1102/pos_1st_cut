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
    /// [delta] is signed: positive scrolls DOWN the page, negative scrolls back
    /// UP. Both are needed now that the time control sits BELOW the toggle —
    /// choosing a slot leaves the viewport past the Order-now chip, so a test
    /// that then switches back has to travel upwards to reach it.
    Future<void> reveal(WidgetTester tester, Key key,
        {double delta = 240}) async {
      await tester.scrollUntilVisible(
        find.byKey(key),
        delta,
        scrollable: find.byType(Scrollable).first,
      );
      await tester.pumpAndSettle();
    }

    /// Turn scheduling on and take the slot the picker opens on.
    ///
    /// TWO taps, deliberately. "Pick a time" sets the order type; the card
    /// beneath it opens the picker. They used to be one tap, and that shortcut
    /// is exactly what made the chip a second time-entry element — two
    /// tappable things reaching the same sheet. Every test that needs a chosen
    /// slot goes through here so the two-step is asserted by all of them
    /// rather than described in one.
    Future<void> chooseSlot(WidgetTester tester) async {
      await reveal(tester, const Key('schedule_later'));
      await tester.tap(find.byKey(const Key('schedule_later')));
      await tester.pumpAndSettle();
      await reveal(tester, const Key('time_field'));
      await tester.tap(find.byKey(const Key('time_field')));
      await tester.pumpAndSettle();
      await tester.tap(find.byKey(const Key('arrival_confirm')));
      await tester.pumpAndSettle();
    }

    testWidgets('an open outlet offers the toggle, defaulting to Order now',
        (tester) async {
      await pump(tester, 'open');
      await reveal(tester, const Key('schedule_toggle'));
      expect(find.byKey(const Key('schedule_toggle')), findsOneWidget);
      expect(find.text('Order now'), findsOneWidget);
      expect(find.text('Pick a time'), findsOneWidget);
      // GPS mode + Order now — the one combination with NO time control at
      // all. The default state of the page, so this is also the assertion that
      // a stray time card can never be the first thing a customer meets.
      expect(find.byKey(const Key('time_field')), findsNothing);
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

    testWidgets('tapping Pick a time reveals the control but opens nothing',
        (tester) async {
      // REPLACES 'opens the picker on the same tap'. The same-tap shortcut was
      // removed with the consolidation: the chip sets the order type, and the
      // card is the single way into the sheet. The shortcut existed because
      // the pickup card used to sit far from the toggle; it now sits directly
      // beneath it, so the disconnect that justified it is gone.
      await pump(tester, 'open');
      await reveal(tester, const Key('schedule_later'));
      await tester.tap(find.byKey(const Key('schedule_later')));
      await tester.pumpAndSettle();

      expect(find.byKey(const Key('arrival_confirm')), findsNothing,
          reason: 'the chip must not open the sheet');
      await reveal(tester, const Key('time_field'));
      // GPS mode + Pick a time -> "Set pickup time".
      expect(find.text('Set pickup time'), findsOneWidget);
      expect(find.byKey(const Key('time_field')), findsOneWidget,
          reason: 'exactly one time control, never two');
    });

    testWidgets('the card is the only way into the picker', (tester) async {
      await pump(tester, 'open');
      await reveal(tester, const Key('schedule_later'));
      await tester.tap(find.byKey(const Key('schedule_later')));
      await tester.pumpAndSettle();
      await reveal(tester, const Key('time_field'));
      await tester.tap(find.byKey(const Key('time_field')));
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

      await chooseSlot(tester);

      await reveal(tester, const Key('time_field'));
      expect(find.byKey(const Key('time_field')), findsOneWidget);
      expect(find.byKey(const Key('checkout_closed_reason')), findsNothing);
      expect(find.textContaining('Pay ₹'), findsOneWidget);
    });

    testWidgets('switching back to Order now re-blocks it during closing_soon',
        (tester) async {
      await pump(tester, 'closing_soon');
      await chooseSlot(tester);
      expect(find.textContaining('Pay ₹'), findsOneWidget);

      await reveal(tester, const Key('schedule_asap'), delta: -240);
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
      await chooseSlot(tester);
      await reveal(tester, const Key('time_field'));
      // "Ready for …" is the scheduled prefix. Its presence proves the card
      // switched from label to value, and that it picked the pickup prefix
      // rather than the declared-arrival one ("Arriving …").
      expect(find.textContaining('Ready for'), findsOneWidget);
      expect(find.textContaining('Arriving'), findsNothing);
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
  // ONE time entry, not two — the (transport mode x order type) matrix
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
  //
  // All four combinations are now resolved by ONE function (_timeControl) into
  // ONE widget, so the matrix below is the specification of that function:
  //
  //   GPS      + Order now    -> no control at all
  //   GPS      + Pick a time  -> "Set pickup time"     -> requested_pickup_at
  //   Declared + Order now    -> "When do you arrive?"  -> declared_arrival_at
  //   Declared + Pick a time  -> "Select pickup time"  -> requested_pickup_at
  //                                                       + declared_arrival_at
  //
  // Each case asserts the LABEL and that there is exactly one control. The
  // field-set half is asserted separately, on the wire, in the group after
  // this one — the label alone would not catch a card that reads correctly and
  // writes the wrong DateTime.
  group('the four-case time-control matrix', () {
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

    /// Scroll the page back to the top.
    ///
    /// The checkout body is a lazily-built ListView, so a chip row left far
    /// enough above the viewport is DISPOSED — find.text('Train') would then
    /// match nothing and ensureVisible would throw "No element". Any test that
    /// scrolls down to the time control and then wants the chips again comes
    /// back up through here first.
    Future<void> toTop(WidgetTester tester) async {
      for (var i = 0; i < 2; i++) {
        await tester.drag(find.byType(Scrollable).first, const Offset(0, 2000));
        await tester.pump();
        await tester.pump(const Duration(milliseconds: 400));
      }
    }

    /// Turn scheduling on WITHOUT choosing a slot.
    ///
    /// Enough for a label assertion, and it keeps these tests off the picker
    /// sheet — the label is decided by (mode, order type) alone, so opening a
    /// sheet to read it would only add a way for the test to flake.
    Future<void> scheduleOn(WidgetTester tester) async {
      await reveal(tester, const Key('schedule_later'));
      await tester.tap(find.byKey(const Key('schedule_later')));
      await tester.pump();
      await tester.pump(const Duration(milliseconds: 400));
    }

    /// Every label the control can ever show. Asserting the expected one is
    /// present is half a test; asserting the other three are absent is what
    /// catches a card that renders twice under two different labels.
    void expectOnlyLabel(String? expected) {
      const all = [
        'Set pickup time',
        'Select pickup time',
        'When do you arrive?',
      ];
      for (final label in all) {
        expect(find.text(label), label == expected ? findsOneWidget : findsNothing,
            reason: 'label "$label"');
      }
      expect(find.byKey(const Key('time_field')),
          expected == null ? findsNothing : findsOneWidget);
    }

    // --- case 1: GPS + Order now -----------------------------------------
    testWidgets('GPS mode ordering now shows no time control at all',
        (tester) async {
      // Walk has a real origin and the clock says "now", so there is no
      // question left to ask. This is also the control case for the whole
      // matrix: without it, deleting the widget outright would pass the rest.
      await pump(tester);
      await tapMode(tester, 'Walk');
      // Scroll the toggle into view FIRST. The card would render immediately
      // below it, so this is what makes the absence real rather than an
      // artifact of a lazy ListView never building that stretch of page.
      await reveal(tester, const Key('schedule_toggle'));
      expectOnlyLabel(null);
    });

    // --- case 2: GPS + Pick a time ---------------------------------------
    testWidgets('GPS mode scheduling says "Set pickup time"', (tester) async {
      await pump(tester);
      await tapMode(tester, 'Walk');
      await scheduleOn(tester);
      await reveal(tester, const Key('time_field'));
      expectOnlyLabel('Set pickup time');
    });

    // --- case 3: declared arrival + Order now ----------------------------
    testWidgets('train ordering now asks "When do you arrive?"',
        (tester) async {
      // The arrival question survives the consolidation — it just arrives
      // through the shared control now. A fix that merely deleted the old
      // arrival card would fail here.
      await pump(tester);
      await tapMode(tester, 'Train');
      await reveal(tester, const Key('time_field'));
      expectOnlyLabel('When do you arrive?');
    });

    // --- case 4: declared arrival + Pick a time --------------------------
    testWidgets('train scheduling says "Select pickup time", and only once',
        (tester) async {
      // THE case this whole consolidation exists for. Before it, a train
      // passenger who also tapped "Pick a time" met two cards asking for two
      // times for one journey.
      await pump(tester);
      await tapMode(tester, 'Train');
      await scheduleOn(tester);
      await reveal(tester, const Key('time_field'));
      expectOnlyLabel('Select pickup time');
    });

    testWidgets('switching order type back and forth never leaves two cards',
        (tester) async {
      // The reversibility the old suite left as a known gap, reachable now
      // that one widget serves both states instead of two widgets swapping.
      await pump(tester);
      await tapMode(tester, 'Train');
      await reveal(tester, const Key('time_field'));
      expectOnlyLabel('When do you arrive?');

      await toTop(tester);
      await scheduleOn(tester);
      await reveal(tester, const Key('time_field'));
      expectOnlyLabel('Select pickup time');

      await toTop(tester);
      await reveal(tester, const Key('schedule_asap'));
      await tester.tap(find.byKey(const Key('schedule_asap')));
      await tester.pump();
      await tester.pump(const Duration(milliseconds: 400));
      await reveal(tester, const Key('time_field'));
      expectOnlyLabel('When do you arrive?');
    });

    testWidgets('switching mode under a chosen order type re-labels in place',
        (tester) async {
      // Same order type, different mode: the label must follow the mode, and
      // still only one card may exist.
      await pump(tester);
      await tapMode(tester, 'Walk');
      await scheduleOn(tester);
      await reveal(tester, const Key('time_field'));
      expectOnlyLabel('Set pickup time');

      await toTop(tester);
      await tapMode(tester, 'Train');
      await reveal(tester, const Key('time_field'));
      expectOnlyLabel('Select pickup time');
    });
  });

  // ======================================================================
  // What each of the four cases puts ON THE WIRE
  // ======================================================================
  //
  // The matrix above proves the right QUESTION is asked. These prove the
  // answer lands in the right FIELD — the half a label assertion cannot
  // reach, and the half that decides when the kitchen starts cooking.
  //
  // Driven through the real Pay button and read off a captured POST body,
  // not by calling toOrderPayload directly: the mapping under test belongs to
  // _payNow (which of _declaredArrival and _requestedPickup it forwards, and
  // under which mode), and calling the payload builder with hand-picked
  // arguments would assert the test's own idea of that mapping.
  group('the four cases on the wire', () {
    late Map<String, dynamic> sent;
    late bool posted;

    setUp(() {
      sent = {};
      posted = false;
    });

    MenuItem menuItem() => MenuItem.fromJson({
          'id': 'i1', 'name': 'Masala Dosa', 'base_price': 120.0,
          'is_veg': true, 'is_available': true, 'image_url': null,
          'prep_time_minutes': 0, 'tags': const <String>[],
          'customizations': const <dynamic>[],
        });

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
      final api = ApiClient(client: MockClient((req) async {
        // The pre-checkout availability gate. It must answer in the shape
        // OrderService expects — a bare list would throw inside
        // _ensureAvailable and the order POST would never be reached.
        if (req.url.path.endsWith('/customer/cart/check')) {
          return http.Response(jsonEncode({'unavailable': const []}), 200,
              headers: {'content-type': 'application/json'});
        }
        if (req.url.path.endsWith('/customer/orders')) {
          sent = (jsonDecode(req.body) as Map).cast<String, dynamic>();
          posted = true;
          // Refused DELIBERATELY. The payload is the whole subject here, and a
          // 400 stops the flow at _payNow's ApiException catch — no order
          // model to build, no payment sheet to open, no navigation to screens
          // this harness does not provide.
          return http.Response(jsonEncode({'detail': 'captured'}), 400,
              headers: {'content-type': 'application/json'});
        }
        return http.Response(jsonEncode(const []), 200,
            headers: {'content-type': 'application/json'});
      }));
      final cart = CartState()
        ..setOutlet(trainOutlet())
        ..addItem(menuItem(), quantity: 1);
      return MultiProvider(
        providers: [
          Provider<ApiClient>.value(value: api),
          Provider<OrderService>(create: (_) => OrderService(api)),
          Provider<CustomerService>(create: (_) => CustomerService(api)),
          Provider<CashfreeService>(create: (_) => CashfreeService()),
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

    /// Bounded pumps, never pumpAndSettle — selecting a mode starts location
    /// acquisition and its spinner animates forever in a test, so a settle
    /// would time out on a feature that is working.
    Future<void> settle(WidgetTester tester) async {
      await tester.pump();
      await tester.pump(const Duration(milliseconds: 400));
    }

    Future<void> pump(WidgetTester tester) async {
      tester.view.physicalSize = const Size(1170, 3400);
      tester.view.devicePixelRatio = 3.0;
      addTearDown(tester.view.reset);
      await tester.pumpWidget(host());
      await settle(tester);
    }

    Future<void> reveal(WidgetTester tester, Key key,
        {double delta = 240}) async {
      await tester.scrollUntilVisible(find.byKey(key), delta,
          scrollable: find.byType(Scrollable).first);
      await settle(tester);
    }

    Future<void> toTop(WidgetTester tester) async {
      for (var i = 0; i < 2; i++) {
        await tester.drag(find.byType(Scrollable).first, const Offset(0, 2000));
        await settle(tester);
      }
    }

    Future<void> tapMode(WidgetTester tester, String label) async {
      final target = find.text(label);
      await tester.ensureVisible(target);
      await tester.pump();
      await tester.tap(target);
      await settle(tester);
    }

    /// Answer the one time control with whatever the picker opens on.
    Future<void> answerTimeControl(WidgetTester tester) async {
      await reveal(tester, const Key('time_field'));
      await tester.tap(find.byKey(const Key('time_field')));
      await settle(tester);
      await tester.tap(find.byKey(const Key('arrival_confirm')));
      await settle(tester);
    }

    Future<void> scheduleOn(WidgetTester tester) async {
      await reveal(tester, const Key('schedule_later'));
      await tester.tap(find.byKey(const Key('schedule_later')));
      await settle(tester);
    }

    Future<void> pay(WidgetTester tester) async {
      await toTop(tester);
      await reveal(tester, const Key('checkout_pay'));
      await tester.tap(find.byKey(const Key('checkout_pay')));
      // Two network round trips before the POST lands: the availability
      // check, then create_order.
      for (var i = 0; i < 4; i++) {
        await settle(tester);
      }
      expect(posted, isTrue,
          reason: 'Pay must have reached POST /customer/orders');
    }

    // --- case 1: GPS + Order now -----------------------------------------
    testWidgets('GPS + Order now sends neither time field', (tester) async {
      await pump(tester);
      await tapMode(tester, 'Walk');
      await pay(tester);

      expect(sent.containsKey('requested_pickup_at'), isFalse);
      expect(sent.containsKey('declared_arrival_at'), isFalse,
          reason: 'nothing was asked, so nothing may be sent');
    });

    // --- case 2: GPS + Pick a time ---------------------------------------
    testWidgets('GPS + Pick a time sends ONLY requested_pickup_at',
        (tester) async {
      await pump(tester);
      await tapMode(tester, 'Walk');
      await scheduleOn(tester);
      await answerTimeControl(tester);
      await pay(tester);

      expect(sent['requested_pickup_at'], isNotNull);
      expect(sent.containsKey('declared_arrival_at'), isFalse,
          reason: 'a GPS mode has a real origin to estimate from — forwarding '
              'the slot as a declared arrival would flip predict_travel onto '
              'its customer_declared leg for a mode that does not need it');
    });

    // --- case 3: declared arrival + Order now ----------------------------
    testWidgets('train + Order now sends ONLY declared_arrival_at',
        (tester) async {
      await pump(tester);
      await tapMode(tester, 'Train');
      await answerTimeControl(tester);
      await pay(tester);

      expect(sent['declared_arrival_at'], isNotNull);
      expect(sent.containsKey('requested_pickup_at'), isFalse,
          reason: 'no slot was requested, so the order must not be held');
    });

    // --- case 4: declared arrival + Pick a time --------------------------
    testWidgets('train + Pick a time sends the slot as BOTH fields, equal',
        (tester) async {
      // THE merge, on the wire.
      //
      // Both fields, carrying the SAME instant — not requested_pickup_at
      // alone. The customer entered one time and it answers both questions:
      // the slot holds the order, and the same instant is the declared
      // arrival that keeps predict_travel on its `customer_declared` leg,
      // which is the only timing signal a train has (there is no GPS origin
      // to estimate from).
      //
      // Sending both is safe by construction, not by convention:
      // _estimated_arrival_at short-circuits on
      // `requested_pickup_at is not None` and returns it as "scheduled"
      // without ever reading declared_arrival_at, so the feasibility gate is
      // judged on the slot alone and the platform-to-door constant is never
      // added on top of it.
      await pump(tester);
      await tapMode(tester, 'Train');
      await scheduleOn(tester);
      await answerTimeControl(tester);
      await pay(tester);

      expect(sent['requested_pickup_at'], isNotNull);
      expect(sent['declared_arrival_at'], isNotNull);
      expect(sent['declared_arrival_at'], sent['requested_pickup_at'],
          reason: 'one entry, one instant — two fields that must not drift');
      // UTC on the wire, for the field that decides when the kitchen starts.
      expect((sent['requested_pickup_at'] as String).endsWith('Z'), isTrue);
    });

    testWidgets('switching back to Order now drops the stale slot',
        (tester) async {
      // _requestedPickup survives the toggle in state; what must not survive
      // is it reaching the wire and quietly holding an ASAP order.
      await pump(tester);
      await tapMode(tester, 'Train');
      await scheduleOn(tester);
      await answerTimeControl(tester);

      await toTop(tester);
      await reveal(tester, const Key('schedule_asap'));
      await tester.tap(find.byKey(const Key('schedule_asap')));
      await settle(tester);
      // Back in the declared-arrival case, which needs its own answer.
      await answerTimeControl(tester);
      await pay(tester);

      expect(sent.containsKey('requested_pickup_at'), isFalse,
          reason: 'an ASAP order must never carry a leftover slot');
      expect(sent['declared_arrival_at'], isNotNull);
    });
  });
}
