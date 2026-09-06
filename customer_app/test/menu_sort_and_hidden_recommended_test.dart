// The three sorts that have real data, and the one option that is now hidden.
//
// Scope came out of a data audit: of everything proposed, only Nearest, Best
// Offer and menu-item price have a backing signal today. "Highest Rated" has
// none — no rating column or table exists anywhere in the schema, for outlets
// OR dishes — and "Fastest Pickup" has an empty rollup table it cannot fill
// while kitchen events are inferred rather than tapped. Neither is built here,
// and the tests below pin that they are not silently faked.
import 'package:flutter_test/flutter_test.dart';

import 'package:customer_app/models/menu.dart';
import 'package:customer_app/models/outlet.dart';
import 'package:customer_app/models/outlet_sort.dart';
import 'package:customer_app/screens/menu_screen.dart';

MenuItem _item(String name, double price, {bool veg = true}) =>
    MenuItem.fromJson({
      'id': name,
      'name': name,
      'base_price': price,
      'is_veg': veg,
      'is_available': true,
    });

Outlet _outlet({int offers = 0, double? km, DateTime? created}) =>
    Outlet.fromJson({
      'id': 'o${offers}_${km}_$created',
      'location_name': 'Outlet',
      'name': 'Outlet',
      'offer_count': offers,
      'distance_km': ?km,
      'created_at': ?created?.toIso8601String(),
    });

void main() {
  group('menu price sort (in-restaurant)', () {
    final items = [
      _item('Dosa', 120),
      _item('Idli', 60),
      _item('Biryani', 240),
      _item('Chai', 20),
    ];

    test('low to high', () {
      expect(
        MenuSort.priceLowHigh.apply(items).map((i) => i.name),
        ['Chai', 'Idli', 'Dosa', 'Biryani'],
      );
    });

    test('high to low', () {
      expect(
        MenuSort.priceHighLow.apply(items).map((i) => i.name),
        ['Biryani', 'Dosa', 'Idli', 'Chai'],
      );
    });

    test('featured keeps the menu\'s own order', () {
      // The restaurant's chosen presentation order is a real signal and the
      // default. It must survive untouched.
      expect(
        MenuSort.featured.apply(items).map((i) => i.name),
        ['Dosa', 'Idli', 'Biryani', 'Chai'],
      );
    });

    test('never mutates the input, so Featured can always be returned to', () {
      final original = List<MenuItem>.of(items);
      MenuSort.priceHighLow.apply(items);
      MenuSort.priceLowHigh.apply(items);
      expect(items.map((i) => i.name), original.map((i) => i.name),
          reason: 'sorting in place would destroy the menu order permanently');
    });

    test('equal prices do not throw or drop rows', () {
      final tied = [_item('A', 100), _item('B', 100), _item('C', 50)];
      final out = MenuSort.priceLowHigh.apply(tied);
      expect(out.first.name, 'C');
      expect(out.length, 3);
    });

    test('an empty menu sorts to empty rather than throwing', () {
      expect(MenuSort.priceLowHigh.apply(const []), isEmpty);
    });

    test('there is NO rating sort — nothing in the schema backs one', () {
      // Guards the audit's conclusion against a well-meaning future addition:
      // menu_items has no rating column, so any such option would have to
      // invent an order.
      expect(MenuSort.values.map((s) => s.name),
          ['featured', 'priceLowHigh', 'priceHighLow']);
      expect(
        MenuSort.values.any((s) => s.label.toLowerCase().contains('rat')),
        isFalse,
      );
    });
  });

  group('Recommended is hidden from the restaurant-list sort sheet', () {
    test('it is hidden, and it is the ONLY hidden option', () {
      expect(OutletSort.recommended.hidden, isTrue);
      expect(OutletSort.values.where((s) => s.hidden), [OutletSort.recommended]);
    });

    test('visible excludes it but keeps the other blocked options', () {
      expect(OutletSort.visible, isNot(contains(OutletSort.recommended)));
      // The rest still show as "Coming soon" — hiding Recommended is a
      // deliberate exception, not a change of policy.
      expect(OutletSort.visible, contains(OutletSort.highestRated));
      expect(OutletSort.visible, contains(OutletSort.fastestPickup));
    });

    test('comingSoon no longer offers it', () {
      expect(OutletSort.comingSoon, isNot(contains(OutletSort.recommended)));
    });

    test('the value is KEPT, with its reason, rather than deleted', () {
      // Deleting the constant would lose the record of why it does not exist
      // and would break anything that had persisted the name.
      expect(OutletSort.values, contains(OutletSort.recommended));
      expect(OutletSort.recommended.blockedBy, isNotNull);
      expect(OutletSort.recommended.available, isFalse);
    });
  });

  group('the restaurant-list sorts that have real data', () {
    test('Nearest orders by distance, unknown distance LAST', () {
      final near = _outlet(km: 1.2);
      final far = _outlet(km: 9.9);
      final unknown = _outlet();
      final out = OutletSort.nearest.apply([far, unknown, near]);
      expect(out.first.distanceKm, 1.2);
      expect(out.last.distanceKm, isNull,
          reason: 'claiming an outlet with no distance is closest is a lie');
    });

    test('Best Offers orders by offer_count, most first', () {
      final none = _outlet(offers: 0);
      final some = _outlet(offers: 3);
      final one = _outlet(offers: 1);
      expect(
        OutletSort.bestOffers.apply([none, some, one]).map((o) => o.offerCount),
        [3, 1, 0],
      );
    });

    test('exactly three options are selectable, and they are the three with '
        'backing data', () {
      expect(OutletSort.enabled.map((s) => s.name),
          ['nearest', 'newest', 'bestOffers']);
    });

    test('a blocked option leaves the order untouched rather than faking one',
        () {
      // If a disabled option ever reached apply(), it must not invent an order.
      final a = _outlet(offers: 1);
      final b = _outlet(offers: 2);
      expect(OutletSort.highestRated.apply([a, b]).map((o) => o.offerCount),
          [1, 2]);
      expect(OutletSort.fastestPickup.apply([a, b]).map((o) => o.offerCount),
          [1, 2]);
    });
  });
}
