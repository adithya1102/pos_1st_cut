import '../models/menu.dart';
import '../models/offer.dart';
import '../models/outlet.dart';
import 'api_client.dart';

/// Reads outlets and menus from the customer API.
class CatalogService {
  CatalogService(this._api);
  final ApiClient _api;

  /// Nearby outlets. Omit [lat]/[lng] for the manual fallback (all outlets).
  /// One selectable location, derived from outlets that actually exist.
  /// Never a hardcoded list — a city with no orderable outlet is not returned.
  Future<List<AreaOption>> fetchAreas() async {
    final res = await _api.get('/customer/areas');
    return ((res as List?) ?? const [])
        .whereType<Map<String, dynamic>>()
        .map(AreaOption.fromJson)
        .toList();
  }

  /// [cities] is a SET, not a single value: the city picker is multi-select, so
  /// this sends `?city=A&city=B` and the API returns the union. A one-element
  /// set behaves exactly as the old single-city call did.
  Future<List<Outlet>> fetchOutlets({
    double? lat,
    double? lng,
    Set<String> cities = const {},
  }) async {
    final query = <String, dynamic>{};
    if (lat != null && lng != null) {
      query['lat'] = lat;
      query['lng'] = lng;
    }
    // Actually filters server-side. Previously the chosen area only changed a
    // subtitle string and every city returned the identical outlet list.
    //
    // A List value here becomes a repeated query parameter — see ApiClient._uri.
    // An EMPTY set sends nothing at all, which the API reads as "no city
    // filter"; the Discover CTA is disabled in that state so it is not
    // normally reachable.
    final cleaned =
        cities.map((c) => c.trim()).where((c) => c.isNotEmpty).toList();
    if (cleaned.isNotEmpty) {
      query['city'] = cleaned;
    }
    final res = await _api.get('/customer/outlets', query: query);
    final list = (res as List<dynamic>? ?? []);
    return list
        .whereType<Map<String, dynamic>>()
        .map(Outlet.fromJson)
        .toList();
  }

  Future<MenuResponse> fetchMenu(String outletId) async {
    final res = await _api.get('/customer/menu/$outletId');
    return MenuResponse.fromJson((res as Map).cast<String, dynamic>());
  }

  /// Every offer usable at this restaurant, as one list.
  ///
  /// CareVo campaigns (platform-wide and ones aimed at this restaurant) and the
  /// restaurant's own offers arrive already merged and already filtered to the
  /// active, unexhausted ones — the app does not decide what is claimable.
  Future<List<Offer>> fetchOffers(String outletId) async {
    final res = await _api.get('/customer/offers', query: {'outlet_id': outletId});
    return ((res as List?) ?? const [])
        .whereType<Map<String, dynamic>>()
        .map(Offer.fromJson)
        .toList();
  }
}

/// A city offered by the location picker, with how many outlets it has.
class AreaOption {
  const AreaOption({required this.city, required this.outletCount});

  final String city;
  final int outletCount;

  /// "3 restaurants" / "1 restaurant" — shown under the city name so the
  /// customer knows what they are choosing into.
  String get subtitle =>
      outletCount == 1 ? '1 restaurant' : '$outletCount restaurants';

  factory AreaOption.fromJson(Map<String, dynamic> json) => AreaOption(
        city: json['city']?.toString() ?? '',
        outletCount:
            int.tryParse(json['outlet_count']?.toString() ?? '') ?? 0,
      );
}
