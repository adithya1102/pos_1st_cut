/// One offer the customer can use at a restaurant (migration 016).
///
/// Two products arrive through this single model, and that is deliberate: a
/// CareVo Campaign and a restaurant's own offer look identical from the
/// customer's side — money off their order. [scope] exists only so the sheet
/// can badge who is behind it, never to filter or rank.
class Offer {
  const Offer({
    required this.id,
    required this.label,
    required this.benefitText,
    required this.scope,
    required this.discountType,
    required this.discountValue,
    this.code,
    this.maxDiscountAmount,
    this.minOrderValue,
    this.creatorName,
  });

  final String id;
  final String label;

  /// Server-rendered one-liner ("20% off up to ₹60"). Rendered as-is so the
  /// outlet chip, this sheet and the owner's own preview cannot disagree.
  final String benefitText;

  /// 'CAREVO_CAMPAIGN' or 'RESTAURANT_OFFER'.
  final String scope;
  final String discountType;
  final double discountValue;
  final String? code;
  final double? maxDiscountAmount;
  final double? minOrderValue;
  final String? creatorName;

  bool get isCareVo => scope == 'CAREVO_CAMPAIGN';

  factory Offer.fromJson(Map<String, dynamic> json) => Offer(
        id: json['id']?.toString() ?? '',
        label: (json['label'] ?? '') as String,
        benefitText: (json['benefit_text'] ?? '') as String,
        scope: (json['scope'] ?? 'RESTAURANT_OFFER') as String,
        discountType: (json['discount_type'] ?? 'FLAT') as String,
        discountValue: (json['discount_value'] as num?)?.toDouble() ?? 0,
        code: json['code'] as String?,
        maxDiscountAmount: (json['max_discount_amount'] as num?)?.toDouble(),
        minOrderValue: (json['min_order_value'] as num?)?.toDouble(),
        creatorName: json['creator_name'] as String?,
      );

  /// What this offer would take off a basket of [subtotal], or null when the
  /// basket does not qualify yet.
  ///
  /// A LOCAL PREVIEW ONLY, for showing "you'd save ₹60" before checkout. The
  /// server recomputes and is the authority — this never decides what is
  /// charged, so a drift here costs a slightly wrong preview, not wrong money.
  double? previewSaving(double subtotal) {
    if (minOrderValue != null && subtotal < minOrderValue!) return null;
    var amount = discountType == 'PERCENT'
        ? subtotal * (discountValue / 100.0)
        : discountValue;
    if (discountType == 'PERCENT' && maxDiscountAmount != null) {
      amount = amount < maxDiscountAmount! ? amount : maxDiscountAmount!;
    }
    return amount < subtotal ? amount : subtotal;
  }
}
