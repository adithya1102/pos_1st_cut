import '../models/order.dart';
import 'api_client.dart';

/// Creates orders, polls their status, and records the PE Step 3 customer
/// travel events (depart / location pings / arrival / wait feedback).
class OrderService {
  OrderService(this._api);
  final ApiClient _api;

  Future<CreatedOrder> createOrder(Map<String, dynamic> payload) async {
    final res = await _api.post('/customer/orders', body: payload);
    return CreatedOrder.fromJson((res as Map).cast<String, dynamic>());
  }

  /// Pre-checkout availability gate. Returns the display names of cart items
  /// that are no longer orderable, empty when everything is fine.
  ///
  /// Called BEFORE payment. `POST /orders` re-checks server-side regardless —
  /// this exists so the customer finds out while they can still fix it, not
  /// after committing.
  Future<List<String>> checkCartAvailability({
    required String outletId,
    required List<String> menuItemIds,
  }) async {
    final res = await _api.post('/customer/cart/check', body: {
      'outlet_id': outletId,
      'menu_item_ids': menuItemIds,
    });
    final map = (res as Map).cast<String, dynamic>();
    return ((map['unavailable'] as List?) ?? const [])
        .whereType<Map>()
        .map((u) => u['menu_item_id']?.toString() ?? '')
        .where((id) => id.isNotEmpty)
        .toList();
  }

  Future<OrderStatus> fetchStatus(String orderId) async {
    final res = await _api.get('/customer/orders/$orderId');
    return OrderStatus.fromJson((res as Map).cast<String, dynamic>());
  }

  /// FR-C3 — customer tapped "I'm leaving". Coordinates are best-effort.
  Future<void> depart(String orderId, {double? lat, double? lng}) async {
    await _api.post('/customer/orders/$orderId/depart',
        body: {'lat': lat, 'lng': lng});
  }

  /// FR-C4 — periodic location ping while en route. The backend throttles
  /// (≥90s or ≥300m) and infers the 150m arrival geofence server-side.
  Future<void> sendLocation(
    String orderId, {
    required double lat,
    required double lng,
    double? accuracyM,
    double? speedMps,
  }) async {
    await _api.post('/customer/orders/$orderId/location', body: {
      'lat': lat,
      'lng': lng,
      'accuracy_m': accuracyM,
      'speed_mps': speedMps,
    });
  }

  /// FR-C4 / FR-C6 — explicit "I've arrived" tap (fallback when location is
  /// unavailable so the geofence can't fire).
  Future<void> arrived(String orderId, {double? accuracyM}) async {
    await _api.post('/customer/orders/$orderId/arrived',
        body: {'accuracy_m': accuracyM, 'source': 'tap'});
  }

  /// FR-C5 — one-tap perceived-wait bucket after pickup.
  Future<void> sendWaitFeedback(String orderId, String bucket) async {
    await _api.post('/customer/orders/$orderId/feedback',
        body: {'bucket': bucket});
  }
}
