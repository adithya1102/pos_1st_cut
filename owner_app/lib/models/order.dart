/// A line item within an order. Deliberately carries NO customer data.
class OrderLineItem {
  final String id;
  final String name;
  final int quantity;

  const OrderLineItem({
    required this.id,
    required this.name,
    required this.quantity,
  });

  factory OrderLineItem.fromJson(Map<String, dynamic> json) {
    return OrderLineItem(
      // API returns a UUID string; parsing this as int threw and broke the
      // whole Orders tab ("Could not load orders").
      id: json['id']?.toString() ?? '',
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
  final String paymentStatus;
  final bool isLocked;
  final double totalAmount;
  final String createdAt;

  /// When staff confirmed the pickup code, if they have.
  ///
  /// The server keeps a verified order in this feed for 30 minutes after this
  /// moment and then stops returning it (CarevoService.COMPLETED_GRACE), so the
  /// app never runs its own removal timer — a timer would reset on every
  /// relaunch and resurrect rows that had already aged out.
  final String? pickupVerifiedAt;

  final List<OrderLineItem> items;

  const Order({
    required this.orderId,
    required this.status,
    required this.paymentStatus,
    required this.isLocked,
    required this.totalAmount,
    required this.createdAt,
    required this.items,
    this.pickupVerifiedAt,
  });

  /// True once staff have confirmed payment (manual UPI-intent tick).
  bool get isPaid => paymentStatus.toUpperCase() == 'PAID';

  /// Collected, and inside its grace window — the only reason a COMPLETED
  /// order is in this feed at all.
  bool get isCollected => status.toUpperCase() == 'COMPLETED';

  /// Minutes since the pickup was verified, for the "collected Nm ago" label.
  /// Null when not yet verified or the timestamp is unparseable.
  int? get minutesSinceCollected {
    final raw = pickupVerifiedAt;
    if (raw == null || raw.isEmpty) return null;
    final at = DateTime.tryParse(raw);
    if (at == null) return null;
    final mins = DateTime.now().toUtc().difference(at.toUtc()).inMinutes;
    return mins < 0 ? 0 : mins;
  }

  factory Order.fromJson(Map<String, dynamic> json) {
    final rawItems = (json['items'] as List<dynamic>?) ?? const [];
    return Order(
      orderId: json['order_id'].toString(),
      status: (json['status'] as String?) ?? '',
      paymentStatus: (json['payment_status'] as String?) ?? '',
      isLocked: (json['is_locked'] as bool?) ?? false,
      totalAmount: _toDouble(json['total_amount']),
      createdAt: (json['created_at'] as String?) ?? '',
      pickupVerifiedAt: json['pickup_verified_at']?.toString(),
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
