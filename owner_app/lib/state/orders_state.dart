import 'package:flutter/foundation.dart';

import '../models/order.dart';
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

  Future<void> notify(String orderId, NotifyType type, {int? itemId}) {
    return _orderService.notify(orderId, type, itemId: itemId);
  }
}
