import 'dart:async';

import 'package:flutter/foundation.dart';

import '../models/order.dart';
import '../services/api_client.dart';
import '../services/order_service.dart';

/// A paid order that has just appeared in the feed, raised once so the UI can
/// announce it. Carries the order itself so the alert can NAME what arrived
/// rather than saying "something happened".
class NewOrderAlert {
  const NewOrderAlert({required this.order, this.alsoArrived = 0});

  /// The newest arrival — the one the banner is about.
  final Order order;

  /// How many OTHER new orders landed in the same refresh. A busy minute must
  /// not silently collapse into a single-order alert.
  final int alsoArrived;
}

/// Backs the Orders tab: the active queue plus pickup verification and notify
/// actions. Order rows are anchored by order_id (never a customer name).
class OrdersState extends ChangeNotifier {
  final OrderService _orderService;

  OrdersState(this._orderService, {this.pollInterval = defaultPollInterval});

  /// How often the queue refreshes itself while the app is in the foreground.
  ///
  /// 15s is a counter-speed compromise: fast enough that a new order is noticed
  /// while the customer is still walking away from the till, slow enough to be
  /// gentle on Render's free tier (4 requests/minute per signed-in device).
  static const Duration defaultPollInterval = Duration(seconds: 15);

  /// Overridable so a test can drive real elapsed time instead of waiting 15s.
  final Duration pollInterval;

  Timer? _poll;

  bool _loading = false;
  String? _error;
  List<Order> _orders = [];

  bool get loading => _loading;
  String? get error => _error;

  /// Newest first — backend already returns them in that order.
  List<Order> get orders => List.unmodifiable(_orders);

  /// Set when a paid order appears that this session has not announced before.
  ///
  /// A ValueNotifier rather than folding it into notifyListeners: an alert is a
  /// one-shot event, not a piece of state the queue rebuilds from. The UI
  /// consumes it with [consumeAlert] so a rebuild cannot re-fire the chime.
  final ValueNotifier<NewOrderAlert?> newOrderAlert =
      ValueNotifier<NewOrderAlert?>(null);

  /// Order ids already announced. Not pruned when a row ages out of the feed:
  /// re-alerting on an order that briefly disappeared and came back would be
  /// worse than holding a few hundred UUID strings for the life of a session.
  final Set<String> _announced = <String>{};

  /// False until the first successful load has been absorbed.
  ///
  /// The queue an owner already has when they sign in is not news. Without this
  /// baseline, opening the app would chime once per order sitting on the
  /// counter — which trains staff to ignore the sound that matters.
  bool _baselineTaken = false;

  /// Guards against a poll firing while the previous one is still in flight
  /// (very possible on a cold Render instance, where a request can outlive the
  /// interval).
  bool _inFlight = false;

  /// Refreshes the queue.
  ///
  /// [silent] suppresses the loading flag so a background poll cannot flash a
  /// spinner over a queue staff are reading. Arrival detection runs either way.
  Future<void> load({bool silent = false}) async {
    // A background poll yields to a request already in flight: on a cold Render
    // instance one call can outlive the interval, and stacking them would turn
    // a single slow response into a backlog of them. A staff-initiated load is
    // never skipped — it is the answer to a tap, and the actions that end in
    // `await load()` rely on it actually running.
    if (silent && _inFlight) return;
    _inFlight = true;
    _error = null;
    if (!silent) {
      _loading = true;
      notifyListeners();
    }
    try {
      _orders = await _orderService.getOrders();
      _noteArrivals();
    } catch (_) {
      _error = 'Could not load orders. Pull to retry.';
    } finally {
      _inFlight = false;
      _loading = false;
      notifyListeners();
    }
  }

  /// Raise an alert for paid orders seen for the first time this session.
  void _noteArrivals() {
    // Only paid, still-live orders count. An unpaid order is not yet the
    // outlet's problem, and a collected one is on its way out of the feed.
    final arrivals = _orders.where((o) => o.isPaid && !o.isCollected).toList();

    if (!_baselineTaken) {
      _baselineTaken = true;
      _announced.addAll(arrivals.map((o) => o.orderId));
      return;
    }

    final fresh =
        arrivals.where((o) => !_announced.contains(o.orderId)).toList();
    if (fresh.isEmpty) return;
    _announced.addAll(fresh.map((o) => o.orderId));

    // The feed is newest-first, so the head of the list is the one to name.
    newOrderAlert.value =
        NewOrderAlert(order: fresh.first, alsoArrived: fresh.length - 1);
  }

  /// Clears a delivered alert so it cannot fire twice.
  void consumeAlert() => newOrderAlert.value = null;

  /// Begin foreground polling. Idempotent — calling it twice does not double
  /// the request rate.
  void startPolling() {
    _poll?.cancel();
    _poll = Timer.periodic(pollInterval, (_) => load(silent: true));
  }

  /// Stop polling. Called when the app leaves the foreground: this alert is
  /// in-app only, so continuing to poll a screen nobody is looking at would
  /// spend battery and quota for nothing.
  void stopPolling() {
    _poll?.cancel();
    _poll = null;
  }

  /// Wipes the queue and the alert baseline.
  ///
  /// Called on logout. OrdersState is a singleton that outlives a session, so
  /// without this the next outlet signing in on the same device would inherit
  /// the previous one's rows — and, because those ids are already announced,
  /// would be alerted about the wrong orders and silent about its own.
  void reset() {
    stopPolling();
    _orders = [];
    _announced.clear();
    _baselineTaken = false;
    _error = null;
    newOrderAlert.value = null;
    notifyListeners();
  }

  @override
  void dispose() {
    stopPolling();
    newOrderAlert.dispose();
    super.dispose();
  }

  Future<PickupResult> verifyPickup(String orderId, String code) {
    return _orderService.verifyPickup(orderId, code);
  }

  /// Find a live order at this outlet by the code the customer showed.
  ///
  /// Read-only — nothing is completed here. Confirming is a separate
  /// [verifyPickup] call, so a code that matches still cannot close an order
  /// without staff tapping confirm.
  Future<PickupLookup> lookupPickup(String code) {
    return _orderService.lookupPickup(code);
  }

  /// Confirm a looked-up pickup, then refresh the queue so the row moves to
  /// its collected state without staff pulling to refresh.
  Future<PickupResult> confirmPickup(String orderId, String code) async {
    final result = await _orderService.verifyPickup(orderId, code);
    if (result.verified) await load();
    return result;
  }

  /// Refuse a paid order. Returns null on success, or a staff-facing message.
  ///
  /// Replaces markPaid, which is gone: payment is confirmed by the gateway
  /// webhook now, so there is nothing for staff to confirm — only something to
  /// refuse. 409 means the order is already READY and can no longer be pulled.
  Future<String?> reject(String orderId, {String? reason}) async {
    try {
      await _orderService.reject(orderId, reason: reason);
      await load();
      return null;
    } on ApiException catch (e) {
      if (e.statusCode == 409) return e.message;
      return 'Could not reject this order.';
    } catch (_) {
      return 'Could not reach the server. Check your connection.';
    }
  }

  /// Mark one or more line items unavailable in a single action.
  /// Returns null on success, or a staff-facing message.
  Future<String?> markItemsUnavailable(String orderId, List<String> itemIds) async {
    if (itemIds.isEmpty) return null;
    try {
      await _orderService.markItemsUnavailable(orderId, itemIds);
      await load();
      return null;
    } on ApiException catch (e) {
      return e.message;
    } catch (_) {
      return 'Could not reach the server. Check your connection.';
    }
  }

  Future<void> notify(String orderId, NotifyType type, {String? itemId}) {
    return _orderService.notify(orderId, type, itemId: itemId);
  }
}
