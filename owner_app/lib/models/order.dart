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

  /// Manual acceptance (backend migration 032).
  ///
  /// NULL for every order at an outlet on automatic acceptance, which is every
  /// outlet until a SUPER_ADMIN opts one in. Its PRESENCE — not any status
  /// value — is what marks an order as needing a human, because an awaiting
  /// order's [status] is `PAID`, identical to an auto order's. [isPending] is
  /// the single place that decision lives.
  ///
  /// AWAITING | ACCEPTED | REJECTED | EXPIRED.
  final String? acceptanceState;

  /// When the window to accept runs out. Drives the countdown on the modal —
  /// an alarm with no visible deadline tells staff nothing about urgency.
  final String? acceptanceDeadlineAt;

  const Order({
    required this.orderId,
    required this.status,
    required this.paymentStatus,
    required this.isLocked,
    required this.totalAmount,
    required this.createdAt,
    required this.items,
    this.pickupVerifiedAt,
    this.acceptanceState,
    this.acceptanceDeadlineAt,
  });

  /// True once staff have confirmed payment (manual UPI-intent tick).
  bool get isPaid => paymentStatus.toUpperCase() == 'PAID';

  /// Waiting for a human to accept or reject it. THE gate for the alert.
  ///
  /// False at an auto outlet because [acceptanceState] is null there, so the
  /// modal and the alarm are unreachable until one opts in.
  bool get isPending => acceptanceState?.toUpperCase() == 'AWAITING';

  /// Seconds until the deadline, floored at zero. Null when not pending or
  /// the timestamp is absent/unparseable — the modal then shows no countdown
  /// rather than a fabricated one.
  int? get secondsToDeadline {
    final raw = acceptanceDeadlineAt;
    if (raw == null || raw.isEmpty) return null;
    final at = DateTime.tryParse(raw);
    if (at == null) return null;
    final s = at.toUtc().difference(DateTime.now().toUtc()).inSeconds;
    return s < 0 ? 0 : s;
  }

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
      // Absent on an auto outlet and on an older backend. Read defensively so
      // either reads as "no confirmation needed", which is the safe default —
      // it leaves the order on the ordinary queue rather than alarming.
      acceptanceState: json['acceptance_state']?.toString(),
      acceptanceDeadlineAt: json['acceptance_deadline_at']?.toString(),
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
