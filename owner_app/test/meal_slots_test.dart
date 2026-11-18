// Meal-time slots: the chip row, the confirm dialog, the editor, and the
// closed banner (backend migration 043).
//
// These drive the real HomeState / MealSlotService over a MockClient, like
// outlet_settings_test.dart does, so the JSON contract and the state layer are
// exercised together. The request log is the proof a tap actually reached
// /apply or /meal-slots, which a screen assertion alone would not show.
//
// THE THREE THAT MATTER MOST
// --------------------------
//  * An EMPTY slot's chip is disabled and reads "Set up". The server refuses
//    an empty apply with 422 SLOT_EMPTY rather than turning the whole menu
//    off, so a tappable empty chip could only ever produce an error.
//  * The SELECTED chip is computed from availability, never stored. A slot is
//    selected exactly when its dish set equals what is on right now.
//  * CANCEL sends nothing. The dialog names how many dishes go off, and that
//    number is the reason it exists — confirming must be the only path to a
//    menu-wide write.
import 'dart:convert';

import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:http/http.dart' as http;
import 'package:http/testing.dart';
import 'package:provider/provider.dart';
import 'package:shared_preferences/shared_preferences.dart';

import 'package:owner_app/models/meal_slot.dart';
import 'package:owner_app/screens/home_screen.dart';
import 'package:owner_app/screens/outlet_settings_screen.dart';
import 'package:owner_app/screens/slot_editor_screen.dart';
import 'package:owner_app/services/api_client.dart';
import 'package:owner_app/services/auth_service.dart';
import 'package:owner_app/services/meal_slot_service.dart';
import 'package:owner_app/services/menu_ocr_service.dart';
import 'package:owner_app/services/menu_service.dart';
import 'package:owner_app/services/offer_service.dart';
import 'package:owner_app/services/order_service.dart';
import 'package:owner_app/services/outlet_service.dart';
import 'package:owner_app/services/staff_push_service.dart';
import 'package:owner_app/state/auth_state.dart';
import 'package:owner_app/state/home_state.dart';
import 'package:owner_app/state/offers_state.dart';
import 'package:owner_app/state/orders_state.dart';

late List<String> requestLog;
late Map<String, dynamic> lastBody;

const _outletId = 'aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee';

/// Three dishes. `on` names which are currently available, which is what the
/// selected-chip computation reads.
List<Map<String, dynamic>> _dishes({Set<String> on = const {'d1', 'd2', 'd3'}}) {
  Map<String, dynamic> dish(String id, String name, {int? stock}) => {
        'id': id,
        'name': name,
        'is_available': on.contains(id),
        'is_active': true,
        'base_price': 80,
        'is_veg': true,
        'category_id': 'c1',
        'category_name': 'Mains',
        'stock_remaining': stock,
      };
  return [
    dish('d1', 'Idli'),
    dish('d2', 'Dosa'),
    dish('d3', 'Biryani'),
  ];
}

/// Four slots. Only the keys named in [withItems] carry dishes; the rest come
/// back saved-but-empty, exactly as the real GET does for a slot the owner has
/// never configured.
List<Map<String, dynamic>> _slots({
  Map<String, List<String>> withItems = const {},
  Map<String, List<String?>> times = const {},
}) {
  return [
    for (final key in MealSlot.keys)
      {
        'slot_key': key,
        'start_time': times[key]?[0],
        'end_time': times[key]?[1],
        'item_ids': withItems[key] ?? const <String>[],
      },
  ];
}

http.Client _backend({
  List<Map<String, dynamic>>? dishes,
  List<Map<String, dynamic>>? slots,
  bool manuallyClosed = false,
  int applyStatus = 200,
  Map<String, dynamic>? applyBody,
  int putStatus = 200,
  Map<String, dynamic>? putError,
}) {
  var currentDishes = dishes ?? _dishes();
  final currentSlots = slots ?? _slots();

  http.Response json(Object b, [int code = 200]) =>
      http.Response(jsonEncode(b), code,
          headers: {'content-type': 'application/json'});

  return MockClient((req) async {
    final path = req.url.path;
    final body = req.body.isEmpty
        ? <String, dynamic>{}
        : jsonDecode(req.body) as Map<String, dynamic>;
    requestLog.add('${req.method} $path');
    if (req.method != 'GET') lastBody = body;

    if (path.contains('/meal-slots/') && path.endsWith('/apply')) {
      if (applyStatus != 200) {
        return json(
            applyBody ??
                {
                  'detail': {
                    'error': 'SLOT_EMPTY',
                    'message': 'This meal time has no dishes yet.',
                  }
                },
            applyStatus);
      }
      // Reflect the switch, like the real endpoint: the slot's dishes on and
      // everything else off, so the reload after apply shows the new state.
      final key = path.split('/')[path.split('/').length - 2];
      final slot = currentSlots.firstWhere((s) => s['slot_key'] == key);
      final ids = (slot['item_ids'] as List).cast<String>().toSet();
      currentDishes = [
        for (final d in currentDishes)
          {...d, 'is_available': ids.contains(d['id'])},
      ];
      return json(applyBody ??
          {
            'slot_key': key,
            'turned_on': ids.length,
            'turned_off': 0,
            'skipped_out_of_stock': 0,
          });
    }
    if (req.method == 'PUT' && path.contains('/meal-slots/')) {
      if (putStatus != 200) {
        return json(
            putError ??
                {
                  'detail':
                      'Only the restaurant owner or a manager can change this.'
                },
            putStatus);
      }
      final key = path.split('/').last;
      final slot = currentSlots.firstWhere((s) => s['slot_key'] == key);
      slot['start_time'] = body['start_time'];
      slot['end_time'] = body['end_time'];
      slot['item_ids'] = (body['item_ids'] as List).cast<String>();
      return json(slot);
    }
    if (path.endsWith('/pos/meal-slots')) return json(currentSlots);
    if (path.endsWith('/pos/menu-items')) return json(currentDishes);
    if (path.endsWith('/pos/categories')) {
      return json([
        {'id': 'c1', 'name': 'Mains'}
      ]);
    }
    if (path.endsWith('/pos/orders') || path.endsWith('/pos/offers')) {
      return json(const <dynamic>[]);
    }
    if (path.endsWith('/pos/outlet')) {
      return json({
        'id': _outletId,
        'location_name': 'Anand Bhavan',
        'is_visible': true,
        'image_url': null,
        'opening_time': '09:00',
        'closing_time': '22:00',
        'is_manually_closed': manuallyClosed,
        'order_status': manuallyClosed ? 'closed' : 'open',
      });
    }
    return json({'detail': 'unexpected ${req.url}'}, 404);
  });
}

Widget _host(http.Client backend) {
  SharedPreferences.setMockInitialValues({'gusto_owner_access_token': 'staff'});
  final api = ApiClient(httpClient: backend);
  return MultiProvider(
    providers: [
      ChangeNotifierProvider(create: (_) => AuthState(AuthService(api))),
      ChangeNotifierProvider(
        create: (_) =>
            HomeState(OutletService(api), MenuService(api), MealSlotService(api)),
      ),
      ChangeNotifierProvider(create: (_) => OrdersState(OrderService(api))),
      ChangeNotifierProvider(create: (_) => OffersState(OfferService(api))),
      Provider(create: (_) => StaffPushService(OrderService(api))),
      Provider(create: (_) => MenuOcrService(api)),
      Provider<OutletService>.value(value: OutletService(api)),
    ],
    child: const MaterialApp(home: HomeScreen()),
  );
}

/// The chips live on the Menu tab, so every test lands there first.
Future<void> _openMenu(WidgetTester tester) async {
  await tester.tap(find.widgetWithText(NavigationDestination, 'Menu'));
  await tester.pumpAndSettle();
}

/// Unmounting stops the orders poll timer — a live timer at teardown fails.
Future<void> _close(WidgetTester tester) async {
  await tester.pumpWidget(const SizedBox.shrink());
  await tester.pumpAndSettle();
}

int _count(String entry) => requestLog.where((e) => e == entry).length;

const _apply = 'POST /api/v1/pos/meal-slots/morning/apply';

Finder _chip(String key) => find.byKey(Key('slot_chip_$key'));

bool _chipEnabled(WidgetTester tester, String key) =>
    tester.widget<InputChip>(_chip(key)).onPressed != null;

bool _chipSelected(WidgetTester tester, String key) =>
    tester.widget<InputChip>(_chip(key)).selected;

void main() {
  setUp(() {
    requestLog = [];
    lastBody = {};
  });

  group('the chip row', () {
    testWidgets('Timings sits on the Menu tab with all four meal times',
        (tester) async {
      await tester.pumpWidget(_host(_backend()));
      await tester.pumpAndSettle();
      await _openMenu(tester);

      expect(find.text('Timings'), findsOneWidget);
      for (final key in MealSlot.keys) {
        expect(_chip(key), findsOneWidget, reason: '$key chip must render');
      }
      expect(find.text('Morning'), findsOneWidget);
      expect(find.text('Afternoon'), findsOneWidget);
      expect(find.text('Evening'), findsOneWidget);
      expect(find.text('Night'), findsOneWidget);

      await _close(tester);
    });

    testWidgets('a chip shows its time range when one is set', (tester) async {
      await tester.pumpWidget(_host(_backend(
        slots: _slots(
          withItems: {'morning': ['d1']},
          times: {'morning': ['07:00', '11:00']},
        ),
      )));
      await tester.pumpAndSettle();
      await _openMenu(tester);

      expect(find.text('7:00 am - 11:00 am'), findsOneWidget);

      await _close(tester);
    });

    testWidgets('an empty slot is disabled and reads "Set up"', (tester) async {
      await tester.pumpWidget(_host(_backend(
        slots: _slots(withItems: {'morning': ['d1']}),
      )));
      await tester.pumpAndSettle();
      await _openMenu(tester);

      expect(_chipEnabled(tester, 'morning'), isTrue);
      expect(_chipEnabled(tester, 'night'), isFalse,
          reason: 'applying an empty slot is a 422, so it must not be tappable');
      expect(find.text('Set up'), findsNWidgets(3));

      await _close(tester);
    });

    testWidgets('tapping a disabled chip sends nothing', (tester) async {
      await tester.pumpWidget(_host(_backend()));
      await tester.pumpAndSettle();
      await _openMenu(tester);

      await tester.tap(_chip('night'));
      await tester.pumpAndSettle();

      expect(find.byKey(const Key('slot_confirm_dialog')), findsNothing);
      expect(requestLog.where((e) => e.contains('/apply')), isEmpty);

      await _close(tester);
    });
  });

  group('the selected chip is computed, not stored', () {
    testWidgets('the slot matching what is on now is selected', (tester) async {
      // d1+d2 are on, and that is exactly the morning slot.
      await tester.pumpWidget(_host(_backend(
        dishes: _dishes(on: {'d1', 'd2'}),
        slots: _slots(withItems: {
          'morning': ['d1', 'd2'],
          'night': ['d3'],
        }),
      )));
      await tester.pumpAndSettle();
      await _openMenu(tester);

      expect(_chipSelected(tester, 'morning'), isTrue);
      expect(_chipSelected(tester, 'night'), isFalse);

      await _close(tester);
    });

    testWidgets('no chip is selected when availability matches no slot',
        (tester) async {
      await tester.pumpWidget(_host(_backend(
        dishes: _dishes(on: {'d1', 'd3'}),
        slots: _slots(withItems: {
          'morning': ['d1', 'd2'],
          'night': ['d3'],
        }),
      )));
      await tester.pumpAndSettle();
      await _openMenu(tester);

      for (final key in MealSlot.keys) {
        expect(_chipSelected(tester, key), isFalse);
      }

      await _close(tester);
    });

    testWidgets('an empty slot is never selected, even with the menu all off',
        (tester) async {
      // Nothing is available. An empty slot's set also equals "nothing", and
      // lighting it up would both mislead and be unapplicable.
      await tester.pumpWidget(_host(_backend(
        dishes: _dishes(on: const {}),
        slots: _slots(withItems: {'morning': ['d1']}),
      )));
      await tester.pumpAndSettle();
      await _openMenu(tester);

      for (final key in MealSlot.keys) {
        expect(_chipSelected(tester, key), isFalse);
      }

      await _close(tester);
    });
  });

  group('applying a slot', () {
    testWidgets('the confirm dialog names both counts', (tester) async {
      // Morning holds 2 dishes; all 3 are on, so 1 other goes off.
      await tester.pumpWidget(_host(_backend(
        dishes: _dishes(on: {'d1', 'd2', 'd3'}),
        slots: _slots(withItems: {'morning': ['d1', 'd2']}),
      )));
      await tester.pumpAndSettle();
      await _openMenu(tester);

      await tester.tap(_chip('morning'));
      await tester.pumpAndSettle();

      expect(find.byKey(const Key('slot_confirm_dialog')), findsOneWidget);
      expect(
        find.text('Show only the 2 dishes in Morning? 1 other dish will be '
            'turned off.'),
        findsOneWidget,
      );
      expect(_count(_apply), 0, reason: 'nothing is sent until Switch is tapped');

      await _close(tester);
    });

    testWidgets('Cancel sends nothing', (tester) async {
      await tester.pumpWidget(_host(_backend(
        slots: _slots(withItems: {'morning': ['d1']}),
      )));
      await tester.pumpAndSettle();
      await _openMenu(tester);

      await tester.tap(_chip('morning'));
      await tester.pumpAndSettle();
      await tester.tap(find.text('Cancel'));
      await tester.pumpAndSettle();

      expect(_count(_apply), 0);
      expect(find.byKey(const Key('slot_confirm_dialog')), findsNothing);

      await _close(tester);
    });

    testWidgets('confirming calls apply, refreshes, and shows the counts',
        (tester) async {
      await tester.pumpWidget(_host(_backend(
        dishes: _dishes(on: {'d1', 'd2', 'd3'}),
        slots: _slots(withItems: {'morning': ['d1']}),
        applyBody: const {
          'slot_key': 'morning',
          'turned_on': 1,
          'turned_off': 2,
          'skipped_out_of_stock': 0,
        },
      )));
      await tester.pumpAndSettle();
      await _openMenu(tester);

      await tester.tap(_chip('morning'));
      await tester.pumpAndSettle();
      await tester.tap(find.byKey(const Key('slot_confirm_apply')));
      await tester.pumpAndSettle();

      expect(_count(_apply), 1, reason: 'Switch must hit the apply route');
      expect(find.byKey(const Key('slot_applied_snackbar')), findsOneWidget);
      expect(find.text('Morning: 1 on, 2 off'), findsOneWidget);
      // The dish list was reloaded, so the server's result is on screen
      // rather than what was requested.
      expect(_count('GET /api/v1/pos/menu-items'), greaterThan(1));

      await _close(tester);
    });

    testWidgets('a skipped out-of-stock dish is named in the snackbar',
        (tester) async {
      await tester.pumpWidget(_host(_backend(
        slots: _slots(withItems: {'morning': ['d1', 'd2']}),
        applyBody: const {
          'slot_key': 'morning',
          'turned_on': 1,
          'turned_off': 1,
          'skipped_out_of_stock': 1,
        },
      )));
      await tester.pumpAndSettle();
      await _openMenu(tester);

      await tester.tap(_chip('morning'));
      await tester.pumpAndSettle();
      await tester.tap(find.byKey(const Key('slot_confirm_apply')));
      await tester.pumpAndSettle();

      expect(
        find.text('Morning: 1 on, 1 off, 1 skipped (out of stock)'),
        findsOneWidget,
        reason: 'the owner must be told a dish they ticked did not come on',
      );

      await _close(tester);
    });

    testWidgets('a server refusal shows its own message', (tester) async {
      await tester.pumpWidget(_host(_backend(
        slots: _slots(withItems: {'morning': ['d1']}),
        applyStatus: 422,
      )));
      await tester.pumpAndSettle();
      await _openMenu(tester);

      await tester.tap(_chip('morning'));
      await tester.pumpAndSettle();
      await tester.tap(find.byKey(const Key('slot_confirm_apply')));
      await tester.pumpAndSettle();

      expect(find.text('This meal time has no dishes yet.'), findsOneWidget);

      await _close(tester);
    });
  });

  group('the slot editor', () {
    Future<void> openEditor(WidgetTester tester) async {
      await _openMenu(tester);
      await tester.tap(find.byTooltip('Edit Morning'));
      await tester.pumpAndSettle();
    }

    testWidgets('opens from the edit icon, even on an empty slot',
        (tester) async {
      await tester.pumpWidget(_host(_backend()));
      await tester.pumpAndSettle();
      await openEditor(tester);

      expect(find.byType(SlotEditorScreen), findsOneWidget);
      // An empty slot is precisely the one that needs opening.
      expect(find.text('Dishes (0 of 3)'), findsOneWidget);

      await _close(tester);
    });

    testWidgets('pre-ticks the slot it was opened for', (tester) async {
      await tester.pumpWidget(_host(_backend(
        slots: _slots(withItems: {'morning': ['d1', 'd2']}),
      )));
      await tester.pumpAndSettle();
      await openEditor(tester);

      expect(find.text('Dishes (2 of 3)'), findsOneWidget);
      expect(
        tester.widget<CheckboxListTile>(find.byKey(const Key('slot_dish_d1'))).value,
        isTrue,
      );
      expect(
        tester.widget<CheckboxListTile>(find.byKey(const Key('slot_dish_d3'))).value,
        isFalse,
      );

      await _close(tester);
    });

    testWidgets('Select all and Clear move every box', (tester) async {
      await tester.pumpWidget(_host(_backend()));
      await tester.pumpAndSettle();
      await openEditor(tester);

      await tester.tap(find.byKey(SlotEditorScreen.selectAllKey));
      await tester.pumpAndSettle();
      expect(find.text('Dishes (3 of 3)'), findsOneWidget);

      await tester.tap(find.byKey(SlotEditorScreen.clearKey));
      await tester.pumpAndSettle();
      expect(find.text('Dishes (0 of 3)'), findsOneWidget);

      await _close(tester);
    });

    testWidgets('Save PUTs the ticked ids', (tester) async {
      await tester.pumpWidget(_host(_backend()));
      await tester.pumpAndSettle();
      await openEditor(tester);

      await tester.tap(find.byKey(const Key('slot_dish_d2')));
      await tester.pumpAndSettle();
      await tester.tap(find.byKey(SlotEditorScreen.saveKey));
      await tester.pumpAndSettle();

      expect(_count('PUT /api/v1/pos/meal-slots/morning'), 1);
      expect(lastBody['item_ids'], ['d2']);
      expect(find.text('Meal time saved.'), findsOneWidget);

      await _close(tester);
    });

    testWidgets('dishes are grouped by category', (tester) async {
      await tester.pumpWidget(_host(_backend()));
      await tester.pumpAndSettle();
      await openEditor(tester);

      expect(find.text('Mains'), findsOneWidget);

      await _close(tester);
    });

    testWidgets('a 403 shows the server message and does not pop',
        (tester) async {
      // The app carries NO role field, so Save is shown to everyone and the
      // server is the authority. A waiter's save must say why.
      await tester.pumpWidget(_host(_backend(putStatus: 403)));
      await tester.pumpAndSettle();
      await openEditor(tester);

      await tester.tap(find.byKey(SlotEditorScreen.saveKey));
      await tester.pumpAndSettle();

      expect(
        find.text('Only the restaurant owner or a manager can change this.'),
        findsOneWidget,
      );
      expect(find.byType(SlotEditorScreen), findsOneWidget,
          reason: 'a refused save must keep the editor open');

      await _close(tester);
    });
  });

  group('the closed banner', () {
    testWidgets('appears on the Menu tab when manually closed', (tester) async {
      await tester.pumpWidget(_host(_backend(manuallyClosed: true)));
      await tester.pumpAndSettle();
      await _openMenu(tester);

      expect(find.text('You are closed — customers cannot order'),
          findsOneWidget);

      await _close(tester);
    });

    testWidgets('is absent while the outlet is open', (tester) async {
      await tester.pumpWidget(_host(_backend()));
      await tester.pumpAndSettle();
      await _openMenu(tester);

      expect(find.text('You are closed — customers cannot order'), findsNothing);

      await _close(tester);
    });

    testWidgets('tapping it opens Hours & availability', (tester) async {
      await tester.pumpWidget(_host(_backend(manuallyClosed: true)));
      await tester.pumpAndSettle();
      await _openMenu(tester);

      await tester.tap(find.byKey(const Key('menu_closed_banner')));
      await tester.pumpAndSettle();

      expect(find.byType(OutletSettingsScreen), findsOneWidget,
          reason: 'a banner with no route to the fix becomes noise');

      await _close(tester);
    });
  });

  group('MealSlot model', () {
    test('rangeLabel formats a 24h pair, and is null when either end is unset',
        () {
      expect(
        const MealSlot(slotKey: 'morning', startTime: '07:00', endTime: '11:30')
            .rangeLabel,
        '7:00 am - 11:30 am',
      );
      expect(
        const MealSlot(slotKey: 'night', startTime: '18:00', endTime: '00:30')
            .rangeLabel,
        '6:00 pm - 12:30 am',
      );
      expect(
        const MealSlot(slotKey: 'morning', startTime: '07:00').rangeLabel,
        isNull,
      );
      expect(const MealSlot(slotKey: 'morning').rangeLabel, isNull);
    });

    test('a malformed time leaves the range null rather than rendering junk',
        () {
      expect(
        const MealSlot(slotKey: 'morning', startTime: 'soon', endTime: '11:00')
            .rangeLabel,
        isNull,
      );
      expect(
        const MealSlot(slotKey: 'morning', startTime: '99:00', endTime: '11:00')
            .rangeLabel,
        isNull,
      );
    });

    test('fromJson reads an absent item_ids as no dishes', () {
      final slot = MealSlot.fromJson({'slot_key': 'morning'});
      expect(slot.itemIds, isEmpty);
      expect(slot.isEmpty, isTrue);
      expect(slot.startTime, isNull);
    });

    test('an empty-string time is treated as unset', () {
      final slot = MealSlot.fromJson(
          {'slot_key': 'morning', 'start_time': '  ', 'end_time': ''});
      expect(slot.startTime, isNull);
      expect(slot.endTime, isNull);
    });

    test('summary mentions the skip only when there was one', () {
      expect(
        const ApplySlotResult(turnedOn: 3, turnedOff: 2, skippedOutOfStock: 0)
            .summary,
        '3 on, 2 off',
      );
      expect(
        const ApplySlotResult(turnedOn: 3, turnedOff: 2, skippedOutOfStock: 1)
            .summary,
        '3 on, 2 off, 1 skipped (out of stock)',
      );
    });
  });
}
