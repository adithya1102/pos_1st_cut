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

  /// The SERVER's own sentence, when it sent one.
  ///
  /// Carries the 409 PAYMENT_NOT_RECORDED prose through to the UI instead of
  /// the generic "Could not verify right now. Try again." that used to replace
  /// it — retrying cannot fix an unpaid order, and the staff member needs
  /// telling to take the payment first.
  final String? message;

  const PickupResult({
    required this.verified,
    required this.locked,
    this.attemptsRemaining,
    this.status,
    this.message,
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
      // 409 PAYMENT_NOT_RECORDED: a pay-at-pickup or direct-UPI order whose
      // money has not been taken yet (backend migrations 034, 035).
      //
      // SURFACED, not swallowed. Before this, anything that was not a 423 was
      // rethrown and VerifyBox turned it into "Could not verify right now. Try
      // again." — which is both wrong and unactionable: retrying cannot help,
      // and the staff member is never told they have to take the payment
      // first. The server sends a sentence written for exactly this moment, so
      // it is carried through verbatim.
      if (e.statusCode == 409) {
        return PickupResult(
          verified: false,
          locked: false,
          status: e.body?['status'] as String?,
          message: _serverMessage(e),
        );
      }
      rethrow;
    }
  }

  /// The server's own prose for a structured error, or null.
  ///
  /// Delegates to ApiException.serverMessage so there is ONE definition of how
  /// a FastAPI `detail` is unwrapped, shared with the settings screen.
  static String? _serverMessage(ApiException e) => e.serverMessage;

  /// `POST /pos/orders/{id}/call` — record that staff rang the customer.
  ///
  /// Does not decide the order and does not extend its deadline. Counts up,
  /// because ringing twice because nobody answered is normal.
  Future<void> logCall(String orderId) async {
    await _client.post('/pos/orders/$orderId/call');
  }

  /// `POST /pos/orders/{id}/collect` — take the money and hand the food over.
  ///
  /// One transaction server-side: recording payment without closing the order
  /// leaves money against food on the counter, and closing without recording
  /// payment gives it away.
  ///
  /// A wrong code is a 200 with `collected: false`, not an exception — the app
  /// must tell "wrong code" from "the request failed".
  Future<PickupResult> collect(String orderId,
      {required String pickupCode, required String method}) async {
    try {
      final data = await _client.post(
        '/pos/orders/$orderId/collect',
        body: {'pickup_code': pickupCode, 'method': method},
      );
      final map = (data as Map<String, dynamic>?) ?? const {};
      return PickupResult(
        verified: (map['collected'] as bool?) ?? false,
        locked: (map['locked'] as bool?) ?? false,
        attemptsRemaining: map['attempts_remaining'] as int?,
        status: map['status'] as String?,
      );
    } on ApiException catch (e) {
      if (e.statusCode == 423) {
        return const PickupResult(verified: false, locked: true);
      }
      return PickupResult(
        verified: false,
        locked: false,
        message: _serverMessage(e),
      );
    }
  }

  /// `POST /pos/orders/{id}/no-show` — the customer never came.
  Future<void> noShow(String orderId) async {
    await _client.post('/pos/orders/$orderId/no-show');
  }

  // REMOVED: markPaid / POST /pos/orders/{id}/mark-paid.
  //
  // Payment confirmation is webhook-driven now — the gateway tells the backend,
  // which runs the same cascade this button used to trigger. The endpoint no
  // longer exists server-side, so calling it would 404; with a real gateway
  // behind it, a staff-tappable "mark as paid" is a button that marks UNPAID
  // orders paid, which is why it is deleted rather than hidden.

  /// `POST /pos/orders/{id}/accept` — take a pending order (migration 032).
  ///
  /// [prepMinutes] is the restaurant's OWN estimate and is required by the
  /// server; the customer-facing ETA still comes from the prediction engine,
  /// so this is recorded for comparison rather than shown to them.
  ///
  /// Throws ApiException(409) when the order is no longer AWAITING — someone
  /// else accepted it, rejected it, or the deadline passed. That is a NORMAL
  /// outcome on a counter with several devices, not an error to hide: the
  /// caller should tell the staff member what happened to it, which is why the
  /// server returns the state that won.
  Future<String> accept(String orderId, {required int prepMinutes}) async {
    final data = await _client.post(
      '/pos/orders/$orderId/accept',
      body: {'prep_minutes': prepMinutes},
    );
    return ((data as Map?)?['acceptance_state'] ?? 'ACCEPTED').toString();
  }

  /// `POST /pos/orders/{id}/alert-ack` — "I have seen this".
  ///
  /// Stops the server re-pushing the alert. Does NOT accept the order and does
  /// NOT stop the deadline — acknowledging must not become a way to park
  /// orders while the customer waits.
  ///
  /// Best-effort and never throws into the caller: this is a courtesy to the
  /// push ladder, and failing it must not block the modal from opening.
  Future<void> acknowledgeAlert(String orderId) async {
    try {
      await _client.post('/pos/orders/$orderId/alert-ack');
    } catch (_) {
      // Swallowed deliberately — see above.
    }
  }

  /// `POST /pos/devices/test-push` — send a real push to THIS device.
  ///
  /// Returns the transport status ('sent' | 'skipped' | 'failed') and its
  /// detail, because 'skipped — no fcm_token' and 'skipped — push disabled'
  /// have different fixes and a boolean cannot tell them apart.
  Future<({String status, String? detail})> sendTestPush() async {
    final data = await _client.post('/pos/devices/test-push');
    final map = (data as Map?) ?? const {};
    return (
      status: (map['status'] ?? 'unknown').toString(),
      detail: map['detail']?.toString(),
    );
  }

  /// `POST /pos/orders/{id}/reject` — refuse a paid order.
  ///
  /// There is deliberately no matching accept: a paid order is accepted
  /// automatically. This is the only human gate and it is an opt-OUT.
  /// Returns the resulting status. 409 if the order is already READY.
  /// [upiOutcome] is direct-UPI only (backend migration 035) and decides who
  /// is owed what:
  ///
  ///   'not_received' — the money is not in the restaurant's UPI app. The
  ///       customer claimed a payment that did not happen: their strike,
  ///       nothing owed.
  ///   'cannot_make'  — the money IS there and the kitchen cannot cook it. The
  ///       restaurant owes it back, UPI to UPI.
  ///
  /// Ignored by the server for any other mode and for an unclaimed order.
  Future<String> reject(String orderId,
      {String? reason, bool unreachable = false, String? upiOutcome}) async {
    final data = await _client.post('/pos/orders/$orderId/reject', body: {
      if (reason != null && reason.trim().isNotEmpty) 'reason': reason.trim(),
      if (unreachable) 'unreachable': true,
      if (upiOutcome != null) 'upi_outcome': upiOutcome,
    });
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
