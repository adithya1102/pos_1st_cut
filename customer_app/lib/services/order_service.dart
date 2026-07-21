import '../models/order.dart';
import 'api_client.dart';

/// Creates orders and polls their status.
class OrderService {
  OrderService(this._api);
  final ApiClient _api;

  Future<CreatedOrder> createOrder(Map<String, dynamic> payload) async {
    final res = await _api.post('/customer/orders', body: payload);
    return CreatedOrder.fromJson((res as Map).cast<String, dynamic>());
  }

  Future<OrderStatus> fetchStatus(String orderId) async {
    final res = await _api.get('/customer/orders/$orderId');
    return OrderStatus.fromJson((res as Map).cast<String, dynamic>());
  }
}
