// Order + payment models returned by the orders endpoints.

class PaymentIntent {
  const PaymentIntent({
    required this.gateway,
    required this.gatewayOrderId,
    required this.amount,
    required this.currency,
    required this.keyId,
    this.paymentSessionId,
    this.checkoutUrl,
  });

  final String gateway;
  final String gatewayOrderId;
  final double amount;
  final String currency;
  final String keyId;

  /// The token Cashfree's checkout opens on. Null for the Razorpay-shaped
  /// stub, which has no equivalent — so the app decides which flow to run from
  /// this being present, not from a build-time constant.
  final String? paymentSessionId;

  /// YOUPI's hosted checkout page. Null for Cashfree and the stub.
  ///
  /// The app opens this rather than building a `upi://pay` intent itself. That
  /// page performs the select-method and payment-done transitions the gateway
  /// requires before an observed bank credit can be attributed to the session;
  /// a raw intent would skip them and the payment would never verify.
  final String? checkoutUrl;

  bool get isCashfree => gateway == 'cashfree' && (paymentSessionId?.isNotEmpty ?? false);

  bool get isYoupi => gateway == 'youpi' && (checkoutUrl?.isNotEmpty ?? false);

  /// True when some hosted flow must be opened before the order can be paid,
  /// whichever gateway is configured. Call sites branch on this instead of
  /// naming a gateway, so a third one needs no new condition here.
  bool get needsHostedCheckout => isCashfree || isYoupi;

  factory PaymentIntent.fromJson(Map<String, dynamic> json) {
    final session = json['payment_session_id'] as String?;
    final checkout = json['checkout_url'] as String?;
    return PaymentIntent(
      gateway: (json['gateway'] ?? '') as String,
      gatewayOrderId: (json['gateway_order_id'] ?? '') as String,
      amount: (json['amount'] as num?)?.toDouble() ?? 0,
      currency: (json['currency'] ?? 'INR') as String,
      keyId: (json['key_id'] ?? '') as String,
      paymentSessionId: (session != null && session.isNotEmpty) ? session : null,
      checkoutUrl: (checkout != null && checkout.isNotEmpty) ? checkout : null,
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
    required this.unitPrice,
  });

  final String name;
  final int quantity;

  /// Price for ONE of this item, as snapshotted when the order was placed.
  ///
  /// The API's `price_snap` is per-unit — the server multiplies by quantity
  /// itself when it sums the order total (carevo_customer/service.py:476-477),
  /// so it is emitted unmultiplied. Storing the unit price and deriving the
  /// line below keeps that distinction visible instead of leaving a field
  /// named "total" holding a per-unit number.
  final double unitPrice;

  /// What this line costs — derived, never parsed.
  ///
  /// A getter rather than a field so it cannot disagree with [unitPrice] and
  /// [quantity]. Same shape [CartItem] already uses for the pre-order side.
  double get lineTotal => unitPrice * quantity;

  factory OrderItemLine.fromJson(Map<String, dynamic> json) {
    return OrderItemLine(
      // `name_snap` / `price_snap` are the names OrderItemOut actually
      // serialises (carevo_customer/schema.py:232-239). This used to try
      // `name`/`menu_item_name` and `line_total`/`total` — none of which the
      // backend has ever emitted, so every line rendered as "Item ₹0" while
      // the order total, read from the correct key, stayed right.
      //
      // The alternative-name chains are gone deliberately: they are what made
      // a field-name mismatch look like real data worth zero rupees instead of
      // failing loudly. A wrong key should now surface as 0/'Item' from ONE
      // named source, not be silently papered over by a second guess.
      //
      // `name_snap` is genuinely nullable (schema Optional[str], column
      // nullable=True), so its fallback covers a real server state, not a
      // spelling. `price_snap` is non-null in both schema and column; its
      // `?? 0` is defensive against a malformed response only — this app has
      // form for a single bad parse taking out a whole screen.
      name: (json['name_snap'] as String?) ?? 'Item',
      quantity: (json['quantity'] as num?)?.toInt() ?? 1,
      unitPrice: (json['price_snap'] as num?)?.toDouble() ?? 0,
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
    this.acceptanceState,
    this.acceptanceDeadlineAt,
    this.refundRequired = false,
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

  /// Manual acceptance (backend migration 032).
  ///
  /// NULL for every order at an outlet on automatic acceptance, which is every
  /// outlet until one opts in. Its PRESENCE — not any status value — is the
  /// signal that this restaurant has to confirm the order, because an awaiting
  /// order's [status] is `PAID`, exactly like an auto order's. Gating on null
  /// is therefore the only correct test, and [requiresConfirmation] is the one
  /// place that decision lives.
  ///
  /// AWAITING | ACCEPTED | REJECTED | EXPIRED.
  final String? acceptanceState;

  /// When the restaurant's window to confirm runs out. Exposed so the screen
  /// can count down rather than spin indefinitely — "waiting" with no visible
  /// end is the worst version of this screen.
  final String? acceptanceDeadlineAt;

  /// Money was taken and no food is coming.
  final bool refundRequired;

  /// True only for an outlet that requires manual confirmation.
  ///
  /// Every acceptance-aware branch in the UI hangs off this, so an auto-mode
  /// order can never take one: the field is null there and this is false.
  bool get requiresConfirmation =>
      acceptanceState != null && acceptanceState!.isNotEmpty;

  /// Paid, but nobody at the restaurant has confirmed it yet.
  bool get isAwaitingConfirmation =>
      acceptanceState?.toUpperCase() == 'AWAITING';

  /// The restaurant confirmed it. From here the screen is the ordinary one.
  bool get isConfirmed => acceptanceState?.toUpperCase() == 'ACCEPTED';

  /// Nobody answered in time. Distinct from a REJECTED order — the customer
  /// was not turned down, they were ignored — but the outcome for them is the
  /// same, so the copy does not labour the difference.
  bool get isConfirmationExpired =>
      acceptanceState?.toUpperCase() == 'EXPIRED';

  /// The pickup code exists but must NOT be shown yet.
  ///
  /// A code shown before confirmation is an invitation to walk to a restaurant
  /// that has not agreed to make the food, so it is withheld until ACCEPTED
  /// even though the server has already allocated it.
  bool get pickupCodeHidden => isAwaitingConfirmation;

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
      // Absent on an older backend and on every auto-mode order, which is why
      // these are read defensively rather than required.
      acceptanceState: json['acceptance_state']?.toString(),
      acceptanceDeadlineAt: json['acceptance_deadline_at']?.toString(),
      refundRequired: (json['refund_required'] as bool?) ?? false,
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
