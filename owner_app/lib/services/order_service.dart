import '../models/order.dart';
import 'api_client.dart';

/// Outcome of a pickup-code verification attempt, normalized for the UI so the
/// widget never has to interpret raw HTTP codes.
class PickupResult {
  /// True when the code was accepted.
  final bool verified;

  /// True when the order is locked out after too many failed attempts (HTTP 423).
  final bool locked;

  /// Remaining attempts before lockout (when the backend supplies it).
  final int? attemptsRemaining;

  /// Backend order status, if returned (e.g. "COMPLETED").
  final String? status;

  const PickupResult({
    required this.verified,
    required this.locked,
    this.attemptsRemaining,
    this.status,
  });
}

/// Allowed notification kinds.
enum NotifyType { readyNow, delayed10, itemUnavailable }

extension NotifyTypeWire on NotifyType {
  String get wire {
    switch (this) {
      case NotifyType.readyNow:
        return 'ready_now';
      case NotifyType.delayed10:
        return 'delayed_10';
      case NotifyType.itemUnavailable:
        return 'item_unavailable';
    }
  }
}

class OrderService {
  final ApiClient _client;

  OrderService(this._client);

  /// `GET /pos/orders` — newest first (backend order preserved).
  Future<List<Order>> getOrders() async {
    final data = await _client.get('/pos/orders');
    final list = (data as List<dynamic>?) ?? const [];
    return list.map((e) => Order.fromJson(e as Map<String, dynamic>)).toList();
  }

  /// `POST /pos/orders/verify-pickup`
  ///
  /// Surfaces HTTP 423 as [PickupResult.locked] rather than throwing, so the
  /// UI can show plain staff-readable text.
  Future<PickupResult> verifyPickup(String orderId, String pickupCode) async {
    try {
      final data = await _client.post(
        '/pos/orders/verify-pickup',
        body: {'order_id': orderId, 'pickup_code': pickupCode},
      );
      final map = (data as Map<String, dynamic>?) ?? const {};
      final locked = (map['locked'] as bool?) ?? false;
      return PickupResult(
        verified: (map['verified'] as bool?) ?? false,
        locked: locked,
        attemptsRemaining: map['attempts_remaining'] as int?,
        status: map['status'] as String?,
      );
    } on ApiException catch (e) {
      if (e.statusCode == 423) {
        // Lockout — normalize instead of leaking the raw code to the UI.
        return PickupResult(
          verified: false,
          locked: true,
          attemptsRemaining: e.body?['attempts_remaining'] as int?,
          status: e.body?['status'] as String?,
        );
      }
      rethrow;
    }
  }

  /// `POST /pos/orders/{id}/mark-paid` — manual UPI-intent confirmation.
  Future<void> markPaid(String orderId) async {
    await _client.post('/pos/orders/$orderId/mark-paid');
  }

  /// `POST /pos/orders/{id}/notify`
  ///
  /// For [NotifyType.itemUnavailable], [itemId] is REQUIRED and must be one of
  /// the order's line-item ids.
  Future<void> notify(
    String orderId,
    NotifyType type, {
    String? itemId,
  }) async {
    if (type == NotifyType.itemUnavailable && itemId == null) {
      throw ArgumentError('item_id is required for item_unavailable notify.');
    }
    await _client.post(
      '/pos/orders/$orderId/notify',
      body: {
        'type': type.wire,
        'item_id': ?itemId,
      },
    );
  }
}
