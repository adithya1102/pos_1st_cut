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
    this.paymentMode = 'PREPAID',
    this.contactFirstName,
    this.contactPhone,
    this.contactVisible = false,
    this.callState,
    this.callAttempts = 0,
    this.collectedPaymentMethod,
    this.paymentClaimedAt,
    this.manualRefundDue = false,
    this.manualRefundReason,
  });

  // --- Pay at pickup / direct UPI (backend migrations 034, 035) ------------
  //
  // THIS MODEL USED TO CARRY NO CUSTOMER DATA AT ALL, and that was a stated
  // invariant: orders were anchored purely by [orderId]. It now holds a first
  // name and a phone — for these two payment modes ONLY, because somebody has
  // to ring the customer to confirm a pay-at-pickup order, and has to be able
  // to chase a UPI payment that did not arrive.
  //
  // The invariant is NARROWED, not abandoned: every field below is null or
  // false for a PREPAID order, which is still every order at every outlet
  // until an owner turns one of the new methods on.

  /// PREPAID | PAY_AT_PICKUP | UPI_MANUAL.
  final String paymentMode;

  /// FIRST NAME ONLY — a surname has no use at a counter.
  final String? contactFirstName;

  /// Suppressed by the server once the visibility window closes, and nulled
  /// for good by its redaction sweep. Absent for a prepaid order.
  final String? contactPhone;

  /// Whether the server is still returning the contact, so the card can say
  /// "no longer available" rather than render an empty space that looks broken.
  final bool contactVisible;

  /// PENDING | CALLED | UNREACHABLE for pay-at-pickup; null otherwise.
  final String? callState;
  final int callAttempts;

  /// cash | upi, once money has been taken.
  final String? collectedPaymentMethod;

  /// Direct UPI: when the CUSTOMER said they had paid.
  ///
  /// Not a payment. The restaurant confirms by looking at its own UPI app, and
  /// that confirmation is the Accept tap — which is why the card's copy says
  /// "Customer says paid" rather than "Paid".
  final String? paymentClaimedAt;

  /// The RESTAURANT owes this customer money back, directly.
  ///
  /// CareVo was never in the path of a direct-UPI payment and cannot reverse
  /// it, so the banner this drives tells the owner to refund it themselves.
  final bool manualRefundDue;
  final String? manualRefundReason;

  bool get isPayAtPickup => paymentMode == 'PAY_AT_PICKUP';
  bool get isUpiManual => paymentMode == 'UPI_MANUAL';
  bool get isPrepaid => paymentMode == 'PREPAID';

  /// A pay-at-pickup order nobody has rung yet.
  bool get needsCall => isPayAtPickup && callState != 'CALLED';

  /// A direct-UPI order whose customer says they have paid, awaiting a human
  /// to check the UPI app.
  bool get upiAwaitingCheck =>
      isUpiManual && paymentClaimedAt != null && !isPaid;

  /// What is still owed. 0 once the money is recorded.
  double get amountDue => isPaid ? 0 : totalAmount;

  /// A `tel:` URI for the call button, or null when there is no number to dial.
  Uri? get telUri {
    final p = contactPhone?.trim();
    if (p == null || p.isEmpty) return null;
    // Strip spaces and dashes only. The leading + is kept — it is part of the
    // number, and dialers handle it.
    return Uri(scheme: 'tel', path: p.replaceAll(RegExp(r'[\s-]'), ''));
  }

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
      // 034/035. All absent on an older backend and on every prepaid order, so
      // each is read defensively with the prepaid answer as its default.
      paymentMode:
          (json['payment_mode'] as String?)?.trim().toUpperCase() ?? 'PREPAID',
      contactFirstName: json['contact_first_name']?.toString(),
      contactPhone: json['contact_phone']?.toString(),
      contactVisible: (json['contact_visible'] as bool?) ?? false,
      callState: json['call_state']?.toString(),
      callAttempts: (json['call_attempts'] as num?)?.toInt() ?? 0,
      collectedPaymentMethod: json['collected_payment_method']?.toString(),
      paymentClaimedAt: json['payment_claimed_at']?.toString(),
      manualRefundDue: (json['manual_refund_due'] as bool?) ?? false,
      manualRefundReason: json['manual_refund_reason']?.toString(),
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

  /// [createdAt] as a local DateTime, or null when absent/unparseable.
  ///
  /// Local, not UTC: this is read off a tablet on a counter in one restaurant,
  /// and a kitchen comparing "placed at" against the clock on the wall must not
  /// be handed a UTC time that is 5.5 hours out.
  DateTime? get placedAt {
    if (createdAt.isEmpty) return null;
    return DateTime.tryParse(createdAt)?.toLocal();
  }

  /// "14:32", or null when [placedAt] is unavailable.
  ///
  /// Hand-formatted rather than via intl, which this app does not depend on —
  /// adding a package for two digits and a colon is not worth the pubspec
  /// churn. 24-hour because every outlet is in India and the kitchen printer
  /// already uses it.
  String? get placedLabel {
    final at = placedAt;
    if (at == null) return null;
    final h = at.hour.toString().padLeft(2, '0');
    final m = at.minute.toString().padLeft(2, '0');
    return '$h:$m';
  }

  /// Minutes this order has been waiting since it was placed, or null when the
  /// timestamp is unusable. Floored at zero so clock skew cannot render "-3m".
  int? get minutesSincePlaced {
    final at = placedAt;
    if (at == null) return null;
    final mins = DateTime.now().difference(at).inMinutes;
    return mins < 0 ? 0 : mins;
  }

  static double _toDouble(dynamic value) {
    if (value is num) return value.toDouble();
    if (value is String) return double.tryParse(value) ?? 0.0;
    return 0.0;
  }
}
