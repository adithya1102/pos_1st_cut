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
    this.originalAmount = 0,
    this.discountAmount = 0,
    this.promotionLabel,
  });

  final String id;
  final String status;
  final double totalAmount;
  final PaymentIntent? payment;

  /// Price breakdown (migration 016). The SERVER's figures — the checkout
  /// screen previews a discount locally, but only these decide what was
  /// charged, so anything shown after the order exists reads from here.
  final double originalAmount;
  final double discountAmount;

  /// e.g. "20% off up to ₹60". Null when no promotion was applied.
  final String? promotionLabel;

  /// What the customer actually pays. Same value as [totalAmount]; named for
  /// the breakdown so a reader never has to remember they are the same.
  double get finalAmount => totalAmount;

  bool get hasDiscount => discountAmount > 0;

  factory CreatedOrder.fromJson(Map<String, dynamic> json) {
    final total = (json['total_amount'] as num?)?.toDouble() ?? 0;
    return CreatedOrder(
      id: json['id']?.toString() ?? '',
      status: (json['status'] ?? 'CREATED') as String,
      totalAmount: total,
      payment: json['payment'] is Map<String, dynamic>
          ? PaymentIntent.fromJson(json['payment'] as Map<String, dynamic>)
          : null,
      // Falls back to the total for any response predating the breakdown, so
      // "original" is never mistakenly reported as ₹0.
      originalAmount: (json['original_amount'] as num?)?.toDouble() ?? total,
      discountAmount: (json['discount_amount'] as num?)?.toDouble() ?? 0,
      promotionLabel: json['promotion_label'] as String?,
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

/// §16 shadow-mode wait range. Deliberately wide and always "approximate" —
/// never a precise ETA, σ, or departure window while the engine is unproven.
class WaitEstimate {
  const WaitEstimate({
    required this.lowMin,
    required this.highMin,
    required this.approximate,
  });

  final int lowMin;
  final int highMin;
  final bool approximate;

  factory WaitEstimate.fromJson(Map<String, dynamic> json) => WaitEstimate(
        lowMin: (json['low_min'] as num?)?.toInt() ?? 0,
        highMin: (json['high_min'] as num?)?.toInt() ?? 0,
        approximate: (json['approximate'] as bool?) ?? true,
      );

  String get label => lowMin == highMin ? '~$highMin min' : '$lowMin–$highMin min';
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
    this.waitEstimate,
    this.originalAmount = 0,
    this.discountAmount = 0,
  });

  final String id;
  final String status;
  final String paymentStatus;
  final String? pickupCode;
  final double totalAmount;

  /// Price breakdown, reconstructed server-side from the stored discount so a
  /// past order can still show what it saved.
  final double originalAmount;
  final double discountAmount;
  final List<OrderItemLine> items;

  bool get hasDiscount => discountAmount > 0;
  final String? createdAt;
  final String? updatedAt;
  final WaitEstimate? waitEstimate;

  factory OrderStatus.fromJson(Map<String, dynamic> json) {
    final total = (json['total_amount'] as num?)?.toDouble() ?? 0;
    return OrderStatus(
      id: json['id']?.toString() ?? '',
      status: (json['status'] ?? 'CREATED') as String,
      paymentStatus: (json['payment_status'] ?? 'PENDING') as String,
      pickupCode: json['pickup_code']?.toString(),
      totalAmount: total,
      originalAmount: (json['original_amount'] as num?)?.toDouble() ?? total,
      discountAmount: (json['discount_amount'] as num?)?.toDouble() ?? 0,
      items: ((json['items'] as List<dynamic>?) ?? [])
          .whereType<Map<String, dynamic>>()
          .map(OrderItemLine.fromJson)
          .toList(),
      createdAt: json['created_at']?.toString(),
      updatedAt: json['updated_at']?.toString(),
      waitEstimate: json['wait_estimate'] is Map<String, dynamic>
          ? WaitEstimate.fromJson(json['wait_estimate'] as Map<String, dynamic>)
          : null,
    );
  }

  bool get isCompleted => const {'COMPLETED', 'PICKED_UP'}
      .contains(status.toUpperCase());

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
