import '../models/menu.dart';
import '../models/outlet.dart';
import 'api_client.dart';

/// Reads outlets and menus from the customer API.
class CatalogService {
  CatalogService(this._api);
  final ApiClient _api;

  /// Nearby outlets. Omit [lat]/[lng] for the manual fallback (all outlets).
  Future<List<Outlet>> fetchOutlets({double? lat, double? lng}) async {
    final query = <String, dynamic>{};
    if (lat != null && lng != null) {
      query['lat'] = lat;
      query['lng'] = lng;
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
