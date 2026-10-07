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
      // Follow the data: speed up to 5s while something is awaiting a
      // decision, drop back to 15s once nothing is. Done here rather than in
      // the UI so a screen cannot forget it.
      _retunePolling();
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

  /// How often the queue refreshes while an order is WAITING to be accepted.
  ///
  /// 5s rather than the usual 15. The acceptance deadline defaults to 180
  /// seconds, so a 15-second poll is up to a 15-second lie about how long is
  /// left — and, worse, up to 15 seconds of alarm after another device has
  /// already settled the order. The faster rate only applies while something
  /// is actually pending, so the steady-state request cost is unchanged.
  static const Duration pendingPollInterval = Duration(seconds: 5);

  /// Overridable for tests, same reason as [pollInterval].
  Duration get pendingPoll => pendingPollInterval;

  /// The order currently awaiting a human decision, if any.
  ///
  /// Plain state rather than a one-shot ValueNotifier like [newOrderAlert],
  /// and the difference matters: a new-order chime is an EVENT that happens
  /// once, whereas this is a CONDITION that persists until the server says
  /// otherwise. Modelling it as an event would mean a dismissed-and-rebuilt
  /// modal never came back for an order still waiting.
  ///
  /// Null at an auto outlet, always, because Order.isPending is false there.
  Order? get pendingOrder {
    for (final o in _orders) {
      if (o.isPending) return o;
    }
    return null;
  }

  /// True while any order needs deciding — what drives the alarm.
  bool get hasPendingOrder => pendingOrder != null;

  /// Tracks which cadence the timer is currently running at, so [load] can
  /// switch rates without restarting the timer on every single tick.
  Duration? _activeInterval;

  /// Begin foreground polling. Idempotent — calling it twice does not double
  /// the request rate.
  void startPolling() {
    _startTimer(hasPendingOrder ? pendingPoll : pollInterval);
  }

  void _startTimer(Duration every) {
    if (_activeInterval == every && _poll != null) return;
    _poll?.cancel();
    _activeInterval = every;
    _poll = Timer.periodic(every, (_) => load(silent: true));
  }

  /// Re-evaluate the poll rate after a load.
  ///
  /// Called from [load] rather than from the UI so the cadence follows the
  /// DATA. A screen that forgot to call this would silently keep polling every
  /// 15s through a 180-second deadline.
  void _retunePolling() {
    if (_poll == null) return; // not polling at all; nothing to retune
    _startTimer(hasPendingOrder ? pendingPoll : pollInterval);
  }

  /// Stop polling. Called when the app leaves the foreground: this alert is
  /// in-app only, so continuing to poll a screen nobody is looking at would
  /// spend battery and quota for nothing.
  void stopPolling() {
    _poll?.cancel();
    _poll = null;
    // Cleared, or a later startPolling() at the SAME cadence would match the
    // cached value, take the early return in _startTimer, and never recreate
    // the timer — polling would silently stay dead.
    _activeInterval = null;
  }

  /// Accept a pending order with a committed prep time (migration 032).
  ///
  /// Returns null on success, or a staff-facing message. A 409 is NOT an error
  /// to hide: it means another device got there first, or the deadline passed,
  /// and the person who just tapped needs to be told which — otherwise they
  /// will stand there expecting food to be made.
  Future<String?> acceptPending(String orderId, int prepMinutes) async {
    try {
      await _orderService.accept(orderId, prepMinutes: prepMinutes);
      await load();
      return null;
    } on ApiException catch (e) {
      await load(); // re-sync: whatever beat us is now the truth
      if (e.statusCode == 409) {
        return 'That order was already dealt with.';
      }
      return 'Could not accept the order. Check the connection and try again.';
    } catch (_) {
      return 'Could not accept the order. Check the connection and try again.';
    }
  }

  /// Tell the server this device has SEEN the alert, which stops the re-push
  /// ladder. Does not accept the order and does not stop its deadline.
  Future<void> acknowledgePending(String orderId) =>
      _orderService.acknowledgeAlert(orderId);

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
