// Order + payment models returned by the orders endpoints.

class PaymentIntent {
  const PaymentIntent({
    required this.gateway,
    required this.gatewayOrderId,
    required this.amount,
    required this.currency,
    required this.keyId,
    this.paymentSessionId,
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

  bool get isCashfree => gateway == 'cashfree' && (paymentSessionId?.isNotEmpty ?? false);

  factory PaymentIntent.fromJson(Map<String, dynamic> json) {
    final session = json['payment_session_id'] as String?;
    return PaymentIntent(
      gateway: (json['gateway'] ?? '') as String,
      gatewayOrderId: (json['gateway_order_id'] ?? '') as String,
      amount: (json['amount'] as num?)?.toDouble() ?? 0,
      currency: (json['currency'] ?? 'INR') as String,
      keyId: (json['key_id'] ?? '') as String,
      paymentSessionId: (session != null && session.isNotEmpty) ? session : null,
    );
  }
}

/// How the restaurant will be paid for one order.
///
/// Mirrors the server's `payment_mode`. Kept as a small enum rather than bare
/// strings so a screen cannot silently mis-spell one, with [fromWire] mapping
/// anything unrecognised to [prepaid] — the only safe default, because it is
/// the mode that routes through the existing, fully-built Cashfree flow.
enum PaymentMode {
  prepaid('PREPAID'),
  payAtPickup('PAY_AT_PICKUP'),
  upiManual('UPI_MANUAL');

  const PaymentMode(this.wire);
  final String wire;

  static PaymentMode fromWire(String? raw) {
    final w = (raw ?? '').trim().toUpperCase();
    for (final m in PaymentMode.values) {
      if (m.wire == w) return m;
    }
    return PaymentMode.prepaid;
  }

  /// True when the money does not move through the gateway, so there is no
  /// payment session and nothing for the Cashfree sheet to open.
  bool get isNonGateway => this != PaymentMode.prepaid;
}

/// What the app needs to build a `upi://pay?...` intent (backend migration 035).
///
/// Comes from the server because the VPA and payee belong to the RESTAURANT and
/// the app has no other way to learn them, and because [note] has to match what
/// the restaurant will see in its own UPI app beside the amount.
class UpiPaymentInfo {
  const UpiPaymentInfo({
    required this.vpa,
    required this.payeeName,
    required this.amount,
    required this.note,
  });

  final String vpa;
  final String payeeName;
  final double amount;

  /// The short order number, for the UPI `tn=` field. NOT the pickup code —
  /// that must never travel through a payment app or land on a statement.
  final String note;

  /// Amount as the UPI spec wants it: two decimals, no symbol or separators.
  String get amountParam => amount.toStringAsFixed(2);

  /// The intent URI the phone's UPI app chooser opens on.
  ///
  /// Built here rather than at the call site so there is one definition of the
  /// parameter set, and every component is percent-encoded — a payee name with
  /// an ampersand would otherwise truncate the query and send the payment with
  /// the wrong details.
  ///
  /// The query is assembled with [Uri.encodeComponent] rather than handed to
  /// `Uri(queryParameters:)` ON PURPOSE. That constructor encodes
  /// form-style, turning a space into `+` — which is a LITERAL plus under
  /// RFC 3986 and only a space by the form-encoding convention. UPI apps
  /// disagree about which reading to take, so "Dosa & Co" could reach the
  /// payer's screen as "Dosa+&+Co". `%20` is unambiguous everywhere.
  ///
  /// It matters least for `pn`, which is display-only, and most for `tn`: that
  /// is the reference the restaurant matches the payment against.
  Uri get intentUri {
    final q = <String, String>{
      'pa': vpa,
      'pn': payeeName,
      'am': amountParam,
      'cu': 'INR',
      'tn': note,
    }
        .entries
        .map((e) =>
            '${Uri.encodeComponent(e.key)}=${Uri.encodeComponent(e.value)}')
        .join('&');
    return Uri.parse('upi://pay?$q');
  }

  static UpiPaymentInfo? fromJson(dynamic raw) {
    if (raw is! Map) return null;
    final json = raw.cast<String, dynamic>();
    final vpa = (json['vpa'] ?? '').toString().trim();
    // No VPA means no intent can be built. Returning null rather than a
    // half-filled object is what stops a screen offering a Pay button that
    // would send money nowhere.
    if (vpa.isEmpty) return null;
    return UpiPaymentInfo(
      vpa: vpa,
      payeeName: (json['payee_name'] ?? '').toString(),
      amount: (json['amount'] as num?)?.toDouble() ?? 0,
      note: (json['note'] ?? '').toString(),
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
    this.paymentMode = PaymentMode.prepaid,
    this.amountDueAtPickup = 0,
    this.upiPayment,
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

  /// How this order will be paid. Read from the server rather than inferred
  /// from [payment] being null, so there is one source of truth for the
  /// branch checkout takes next.
  final PaymentMode paymentMode;

  /// What to hand over at the counter. 0 unless this is a pay-at-pickup order.
  final double amountDueAtPickup;

  /// Present only for a direct-UPI order. Null for every other mode.
  final UpiPaymentInfo? upiPayment;

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
      // Defaults to PREPAID for any response predating these fields, which is
      // what keeps an older backend working with this build.
      paymentMode: PaymentMode.fromWire(json['payment_mode'] as String?),
      amountDueAtPickup:
          (json['amount_due_at_pickup'] as num?)?.toDouble() ?? 0,
      upiPayment: UpiPaymentInfo.fromJson(json['upi_payment']),
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
    this.paymentMode = PaymentMode.prepaid,
    this.amountDueAtPickup = 0,
    this.callState,
    this.paymentClaimedAt,
    this.manualRefundDue = false,
    this.manualRefundReason,
    this.upiPayment,
    this.departed = false,
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

  // --- Pay at pickup / direct UPI (backend migrations 034, 035) ------------

  /// How this order is paid. PREPAID for every order an older backend returns.
  final PaymentMode paymentMode;

  /// What to hand over at the counter. 0 once paid, and 0 for every other mode.
  final double amountDueAtPickup;

  /// PENDING | CALLED | UNREACHABLE for a pay-at-pickup order, else null. Lets
  /// the screen say "they are about to call you" instead of spinning.
  final String? callState;

  /// Set once the customer has tapped "I've paid" on a direct-UPI order.
  ///
  /// Its PRESENCE is what moves the pay screen from "pay now" to "waiting for
  /// the restaurant", which is why it is read from the server rather than held
  /// in app state — the distinction has to survive the app being killed.
  final String? paymentClaimedAt;

  /// The RESTAURANT owes this money back directly, UPI to UPI.
  ///
  /// Distinct from [refundRequired], which is a gateway reversal CareVo can
  /// arrange. CareVo was never in the path of a direct-UPI payment, so the
  /// copy driven by this must say the restaurant will refund — promising
  /// otherwise would be promising something nobody can send.
  final bool manualRefundDue;

  /// WHY the restaurant owes the money, which decides what the customer is
  /// told — and the two cases need genuinely different sentences.
  ///
  ///   'acceptance_expired_after_payment_claim' — nobody at the restaurant
  ///       ever looked. The customer said they paid and the deadline passed,
  ///       so NOBODY KNOWS whether the money actually left their account. The
  ///       honest copy is conditional ("if your money left your account") and
  ///       points them at the restaurant, because the restaurant is the only
  ///       party who can see whether it arrived.
  ///
  ///   anything else (today: 'cannot_make') — the restaurant confirmed the
  ///       money and then could not cook. Here the payment IS established, so
  ///       a flat promise of a refund is accurate.
  ///
  /// Promising a refund in the first case would be asserting a payment nobody
  /// has verified; being vague in the second would be withholding a promise
  /// that is owed.
  final String? manualRefundReason;

  /// The expiry case: the claim was never checked, so the payment is unproven.
  bool get refundUnconfirmedByRestaurant =>
      manualRefundDue &&
      manualRefundReason == 'acceptance_expired_after_payment_claim';

  /// Present only while a direct-UPI order is still unpaid, so the pay screen
  /// can be rebuilt after a restart. Absent once the restaurant accepts.
  final UpiPaymentInfo? upiPayment;

  /// True once the server has recorded a CUSTOMER_DEPARTED event for this
  /// order (backend OrderOut.departed). This is the AUTHORITATIVE source for
  /// "has the customer set off" — unlike a client-only flag, it survives an
  /// app restart because it is read fresh from the server on every poll,
  /// not reconstructed from local storage.
  final bool departed;

  /// True once the order has been accepted and there is nothing left for a
  /// human at the restaurant to decide — which is every order at an outlet
  /// with no manual-acceptance step (acceptanceState is null there, so there
  /// is no "awaiting" phase to wait out), and an ACCEPTED order at an outlet
  /// that does have one. False while AWAITING, REJECTED or EXPIRED.
  bool get isAcceptedByRestaurant => !requiresConfirmation || isConfirmed;

  /// A direct-UPI order the customer has not yet said they paid for.
  bool get awaitingUpiPayment =>
      paymentMode == PaymentMode.upiManual &&
      paymentClaimedAt == null &&
      paymentStatus.toUpperCase() != 'PAID';

  /// Paid as far as the customer is concerned, but the restaurant has not yet
  /// confirmed the money arrived.
  bool get awaitingUpiConfirmation =>
      paymentMode == PaymentMode.upiManual &&
      paymentClaimedAt != null &&
      paymentStatus.toUpperCase() != 'PAID';

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
      // All absent on an older backend and on every prepaid order, so each is
      // read defensively with the prepaid answer as its default.
      paymentMode: PaymentMode.fromWire(json['payment_mode'] as String?),
      amountDueAtPickup:
          (json['amount_due_at_pickup'] as num?)?.toDouble() ?? 0,
      callState: json['call_state']?.toString(),
      paymentClaimedAt: json['payment_claimed_at']?.toString(),
      manualRefundDue: (json['manual_refund_due'] as bool?) ?? false,
      manualRefundReason: json['manual_refund_reason']?.toString(),
      upiPayment: UpiPaymentInfo.fromJson(json['upi_payment']),
      // Absent on an older backend, which is read as "not departed" — the
      // same conservative default every other additive field here uses.
      departed: (json['departed'] as bool?) ?? false,
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
