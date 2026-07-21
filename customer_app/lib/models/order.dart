// Order + payment models returned by the orders endpoints.

class PaymentIntent {
  const PaymentIntent({
    required this.gateway,
    required this.gatewayOrderId,
    required this.amount,
    required this.currency,
    required this.keyId,
  });

  final String gateway;
  final String gatewayOrderId;
  final double amount;
  final String currency;
  final String keyId;

  factory PaymentIntent.fromJson(Map<String, dynamic> json) {
    return PaymentIntent(
      gateway: (json['gateway'] ?? '') as String,
      gatewayOrderId: (json['gateway_order_id'] ?? '') as String,
      amount: (json['amount'] as num?)?.toDouble() ?? 0,
      currency: (json['currency'] ?? 'INR') as String,
      keyId: (json['key_id'] ?? '') as String,
    );
  }
}

/// Response from creating an order.
class CreatedOrder {
  const CreatedOrder({
    required this.id,
    required this.status,
    required this.totalAmount,
    this.payment,
  });

  final String id;
  final String status;
  final double totalAmount;
  final PaymentIntent? payment;

  factory CreatedOrder.fromJson(Map<String, dynamic> json) {
    return CreatedOrder(
      id: json['id']?.toString() ?? '',
      status: (json['status'] ?? 'CREATED') as String,
      totalAmount: (json['total_amount'] as num?)?.toDouble() ?? 0,
      payment: json['payment'] is Map<String, dynamic>
          ? PaymentIntent.fromJson(json['payment'] as Map<String, dynamic>)
          : null,
    );
  }
}

class OrderItemLine {
  const OrderItemLine({
    required this.name,
    required this.quantity,
    required this.lineTotal,
  });

  final String name;
  final int quantity;
  final double lineTotal;

  factory OrderItemLine.fromJson(Map<String, dynamic> json) {
    return OrderItemLine(
      name: (json['name'] ?? json['menu_item_name'] ?? 'Item') as String,
      quantity: (json['quantity'] as num?)?.toInt() ?? 1,
      lineTotal: (json['line_total'] as num?)?.toDouble() ??
          (json['total'] as num?)?.toDouble() ??
          0,
    );
  }
}

/// The full order status returned by `GET /customer/orders/{id}`.
class OrderStatus {
  const OrderStatus({
    required this.id,
    required this.status,
    required this.paymentStatus,
    required this.pickupCode,
    required this.totalAmount,
    required this.items,
    this.createdAt,
    this.updatedAt,
  });

  final String id;
  final String status;
  final String paymentStatus;
  final String? pickupCode;
  final double totalAmount;
  final List<OrderItemLine> items;
  final String? createdAt;
  final String? updatedAt;

  factory OrderStatus.fromJson(Map<String, dynamic> json) {
    return OrderStatus(
      id: json['id']?.toString() ?? '',
      status: (json['status'] ?? 'CREATED') as String,
      paymentStatus: (json['payment_status'] ?? 'PENDING') as String,
      pickupCode: json['pickup_code']?.toString(),
      totalAmount: (json['total_amount'] as num?)?.toDouble() ?? 0,
      items: ((json['items'] as List<dynamic>?) ?? [])
          .whereType<Map<String, dynamic>>()
          .map(OrderItemLine.fromJson)
          .toList(),
      createdAt: json['created_at']?.toString(),
      updatedAt: json['updated_at']?.toString(),
    );
  }

  /// Maps the backend status string to a 0-based stepper index:
  /// 0 = Received, 1 = Preparing, 2 = Ready.
  int get stepIndex {
    switch (status.toUpperCase()) {
      case 'CREATED':
      case 'PAID':
      case 'RECEIVED':
      case 'CONFIRMED':
        return 0;
      case 'PREPARING':
      case 'IN_PROGRESS':
      case 'COOKING':
        return 1;
      case 'READY':
      case 'READY_FOR_PICKUP':
      case 'COMPLETED':
      case 'PICKED_UP':
        return 2;
      default:
        return 0;
    }
  }
}
