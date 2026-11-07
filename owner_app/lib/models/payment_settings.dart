/// How this restaurant takes money, and what it is PERMITTED to take.
///
/// Mirrors the server's OwnerPaymentMethodsOut (backend migrations 035, 036).
///
/// THE DISTINCTION THAT DRIVES THE WHOLE SCREEN is [prepaid] versus
/// [cashfreeUnlocked]. The first is the owner's preference; the second is
/// CareVo's permission, and it is not the owner's to grant. A restaurant that
/// has just joined has permission withheld, and the Payment modes screen then
/// renders no Cashfree control AT ALL rather than a switch that flips back —
/// see [showCashfreeRow].
class PaymentSettings {
  const PaymentSettings({
    required this.prepaid,
    required this.payAtPickup,
    required this.upiManual,
    required this.cashfreeUnlocked,
    this.upiVpa,
    this.upiPayeeName,
    this.upiAttested = false,
    this.effectiveMethods = const [],
    this.cashfreeOnly = false,
    this.gatewayAvailable = true,
    this.gatewayUnavailableReason,
    this.payAtPickupAvailable = true,
    this.payAtPickupUnavailableReason,
    this.upiAvailable = true,
    this.upiUnavailableReason,
  });

  /// The owner WANTS to offer online payment.
  final bool prepaid;
  final bool payAtPickup;
  final bool upiManual;

  /// CareVo PERMITS online payment for this outlet.
  final bool cashfreeUnlocked;

  final String? upiVpa;
  final String? upiPayeeName;

  /// The owner has confirmed they sent themselves ₹1 through [upiVpa] and
  /// received it. Cleared server-side whenever the VPA changes, because the
  /// old proof was about the old string.
  final bool upiAttested;

  /// What a customer would actually be offered right now. NOT just the three
  /// flags — prepaid additionally needs the unlock and a live gateway — so
  /// this is what the screen uses to warn that nothing is on offer.
  final List<String> effectiveMethods;

  /// True when the platform-wide CASHFREE_ONLY switch is on. Pay-at-pickup
  /// and UPI are not a per-outlet choice while this is true — the server
  /// 403s a PATCH that tries to turn either on — so the screen hides those
  /// controls and shows a plain note rather than letting the owner tap a
  /// switch that is guaranteed to fail.
  final bool cashfreeOnly;

  /// Whether the owner could flip the gateway switch ON right now (Payment
  /// tab). Distinct from [prepaid]/[cashfreeUnlocked]: this is the single
  /// field the new three-card screen greys the switch on, with
  /// [gatewayUnavailableReason] behind it for the note. Defaults true so a
  /// backend that predates this field never greys a switch that works.
  final bool gatewayAvailable;
  final String? gatewayUnavailableReason;
  final bool payAtPickupAvailable;
  final String? payAtPickupUnavailableReason;
  final bool upiAvailable;
  final String? upiUnavailableReason;

  /// Whether to render the Cashfree row at all (AMENDMENT A3).
  ///
  /// False hides it completely: no greyed row, no explanatory text, no hint.
  /// A restaurant that has never been offered online payment should not be
  /// shown a control for it — a disabled switch invites a support question
  /// about something they cannot act on.
  bool get showCashfreeRow => cashfreeUnlocked;

  /// True when the restaurant can currently take no orders at all.
  bool get acceptsNothing => effectiveMethods.isEmpty;

  factory PaymentSettings.fromJson(Map<String, dynamic> json) {
    return PaymentSettings(
      prepaid: (json['prepaid'] as bool?) ?? false,
      payAtPickup: (json['pay_at_pickup'] as bool?) ?? false,
      upiManual: (json['upi_manual'] as bool?) ?? false,
      // Defaults TRUE when absent, matching an older backend where online
      // payment was unconditional — a missing field must not hide a control
      // that works.
      cashfreeUnlocked: (json['cashfree_unlocked'] as bool?) ?? true,
      upiVpa: (json['upi_vpa'] as String?)?.trim().isNotEmpty == true
          ? (json['upi_vpa'] as String).trim()
          : null,
      upiPayeeName:
          (json['upi_payee_name'] as String?)?.trim().isNotEmpty == true
              ? (json['upi_payee_name'] as String).trim()
              : null,
      upiAttested: (json['upi_attested'] as bool?) ?? false,
      effectiveMethods: ((json['effective_methods'] as List?) ?? const [])
          .map((e) => e.toString().toUpperCase())
          .toList(growable: false),
      // Absent on an older backend that predates CASHFREE_ONLY — defaults
      // false, matching "the switch does not exist yet" rather than hiding
      // controls a build talking to that backend can still use.
      cashfreeOnly: (json['cashfree_only'] as bool?) ?? false,
      gatewayAvailable: (json['gateway_available'] as bool?) ?? true,
      gatewayUnavailableReason: json['gateway_unavailable_reason'] as String?,
      payAtPickupAvailable:
          (json['pay_at_pickup_available'] as bool?) ?? true,
      payAtPickupUnavailableReason:
          json['pay_at_pickup_unavailable_reason'] as String?,
      upiAvailable: (json['upi_manual_available'] as bool?) ?? true,
      upiUnavailableReason: json['upi_manual_unavailable_reason'] as String?,
    );
  }

  PaymentSettings copyWith({
    bool? prepaid,
    bool? payAtPickup,
    bool? upiManual,
    String? upiVpa,
    String? upiPayeeName,
    bool? upiAttested,
  }) =>
      PaymentSettings(
        prepaid: prepaid ?? this.prepaid,
        payAtPickup: payAtPickup ?? this.payAtPickup,
        upiManual: upiManual ?? this.upiManual,
        cashfreeUnlocked: cashfreeUnlocked,
        upiVpa: upiVpa ?? this.upiVpa,
        upiPayeeName: upiPayeeName ?? this.upiPayeeName,
        upiAttested: upiAttested ?? this.upiAttested,
        effectiveMethods: effectiveMethods,
        cashfreeOnly: cashfreeOnly,
        gatewayAvailable: gatewayAvailable,
        gatewayUnavailableReason: gatewayUnavailableReason,
        payAtPickupAvailable: payAtPickupAvailable,
        payAtPickupUnavailableReason: payAtPickupUnavailableReason,
        upiAvailable: upiAvailable,
        upiUnavailableReason: upiUnavailableReason,
      );
}
