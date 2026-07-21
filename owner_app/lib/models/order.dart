/// A line item within an order. Deliberately carries NO customer data.
class OrderLineItem {
  final int id;
  final String name;
  final int quantity;

  const OrderLineItem({
    required this.id,
    required this.name,
    required this.quantity,
  });

  factory OrderLineItem.fromJson(Map<String, dynamic> json) {
    return OrderLineItem(
      id: json['id'] as int,
      name: (json['name'] as String?) ?? '',
      quantity: (json['quantity'] as int?) ?? 0,
    );
  }
}

/// An active order in the queue.
///
/// There is intentionally NO customer name/phone field anywhere in this model
/// or the app — orders are anchored purely by [orderId].
class Order {
  final String orderId;
  final String status;
  final bool isLocked;
  final double totalAmount;
  final String createdAt;
  final List<OrderLineItem> items;

  const Order({
    required this.orderId,
    required this.status,
    required this.isLocked,
    required this.totalAmount,
    required this.createdAt,
    required this.items,
  });

  factory Order.fromJson(Map<String, dynamic> json) {
    final rawItems = (json['items'] as List<dynamic>?) ?? const [];
    return Order(
      orderId: json['order_id'].toString(),
      status: (json['status'] as String?) ?? '',
      isLocked: (json['is_locked'] as bool?) ?? false,
      totalAmount: _toDouble(json['total_amount']),
      createdAt: (json['created_at'] as String?) ?? '',
      items: rawItems
          .map((e) => OrderLineItem.fromJson(e as Map<String, dynamic>))
          .toList(),
    );
  }

  /// Short, human-scannable form of the order id for the queue row.
  String get shortId {
    if (orderId.length <= 8) return orderId;
    return orderId.substring(orderId.length - 6);
  }

  static double _toDouble(dynamic value) {
    if (value is num) return value.toDouble();
    if (value is String) return double.tryParse(value) ?? 0.0;
    return 0.0;
  }
}
