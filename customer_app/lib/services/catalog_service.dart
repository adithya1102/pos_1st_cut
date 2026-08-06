import '../models/menu.dart';
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

  Future<List<Outlet>> fetchOutlets({double? lat, double? lng, String? city}) async {
    final query = <String, dynamic>{};
    if (lat != null && lng != null) {
      query['lat'] = lat;
      query['lng'] = lng;
    }
    // Actually filters server-side. Previously the chosen area only changed a
    // subtitle string and every city returned the identical outlet list.
    if (city != null && city.trim().isNotEmpty) {
      query['city'] = city.trim();
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
