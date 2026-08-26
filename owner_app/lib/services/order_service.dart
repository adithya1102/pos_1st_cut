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

/// Outcome of a pickup-code lookup.
///
/// A miss is a normal result ([found] false), not an exception — "no live
/// order has that code" is something staff need told plainly, and it must not
/// look like the request failed.
class PickupLookup {
  final bool found;

  /// Set when [found]; the order to check against the bag.
  final Order? order;

  /// The order exists but is locked out after 3 failed attempts.
  final bool locked;

  const PickupLookup({required this.found, this.order, this.locked = false});

  const PickupLookup.miss() : found = false, order = null, locked = false;
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

  /// `POST /pos/orders/lookup-pickup` — find a live order by its pickup code.
  ///
  /// Read-only. The order is NOT completed by looking it up; that needs an
  /// explicit [verifyPickup] call behind the staff's confirm tap.
  ///
  /// The backend scopes the search to the caller's own outlet, so this cannot
  /// return another outlet's order whatever code is typed.
  Future<PickupLookup> lookupPickup(String pickupCode) async {
    final data = await _client.post(
      '/pos/orders/lookup-pickup',
      body: {'pickup_code': pickupCode.trim()},
    );
    final map = (data as Map<String, dynamic>?) ?? const {};
    if ((map['found'] as bool?) != true) return const PickupLookup.miss();
    final raw = map['order'] as Map<String, dynamic>?;
    if (raw == null) return const PickupLookup.miss();
    return PickupLookup(
      found: true,
      order: Order.fromJson(raw),
      locked: (map['locked'] as bool?) ?? false,
    );
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

  // REMOVED: markPaid / POST /pos/orders/{id}/mark-paid.
  //
  // Payment confirmation is webhook-driven now — the gateway tells the backend,
  // which runs the same cascade this button used to trigger. The endpoint no
  // longer exists server-side, so calling it would 404; with a real gateway
  // behind it, a staff-tappable "mark as paid" is a button that marks UNPAID
  // orders paid, which is why it is deleted rather than hidden.

  /// `POST /pos/orders/{id}/reject` — refuse a paid order.
  ///
  /// There is deliberately no matching accept: a paid order is accepted
  /// automatically. This is the only human gate and it is an opt-OUT.
  /// Returns the resulting status. 409 if the order is already READY.
  Future<String> reject(String orderId, {String? reason}) async {
    final data = await _client.post('/pos/orders/$orderId/reject',
        body: {if (reason != null && reason.trim().isNotEmpty) 'reason': reason.trim()});
    return ((data as Map?)?['status'] ?? 'CANCELLED').toString();
  }

  /// `POST /pos/orders/{id}/items/unavailable` — batch N/A.
  ///
  /// One call, several items; the server writes one event and fires one push
  /// PER ITEM so the customer is told which specific dish is off.
  Future<int> markItemsUnavailable(String orderId, List<String> itemIds) async {
    final data = await _client.post(
      '/pos/orders/$orderId/items/unavailable',
      body: {'item_ids': itemIds},
    );
    return (((data as Map?)?['marked'] as List?) ?? const []).length;
  }

  /// `POST /pos/push/register` — store this device's FCM token for staff pushes.
  Future<void> registerPushToken(String token) async {
    await _client.post('/pos/push/register', body: {'fcm_token': token});
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
