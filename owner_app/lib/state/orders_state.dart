import 'package:flutter/foundation.dart';

import '../models/order.dart';
import '../services/api_client.dart';
import '../services/order_service.dart';

/// Backs the Orders tab: the active queue plus pickup verification and notify
/// actions. Order rows are anchored by order_id (never a customer name).
class OrdersState extends ChangeNotifier {
  final OrderService _orderService;

  OrdersState(this._orderService);

  bool _loading = false;
  String? _error;
  List<Order> _orders = [];

  bool get loading => _loading;
  String? get error => _error;

  /// Newest first — backend already returns them in that order.
  List<Order> get orders => List.unmodifiable(_orders);

  Future<void> load() async {
    _loading = true;
    _error = null;
    notifyListeners();
    try {
      _orders = await _orderService.getOrders();
    } catch (_) {
      _error = 'Could not load orders. Pull to retry.';
    } finally {
      _loading = false;
      notifyListeners();
    }
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
