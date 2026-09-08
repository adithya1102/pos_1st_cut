/// A Restaurant Offer — a discount the restaurant funds itself (migration 016).
///
/// The wire format is the shared `promotions` row, so `scope` and `outletId`
/// come back on it. Neither is ever SENT: the backend fixes scope to
/// RESTAURANT_OFFER and the outlet to the caller's own. They exist here only to
/// read, never to choose.
class Offer {
  const Offer({
    required this.id,
    required this.label,
    required this.benefitText,
    required this.discountType,
    required this.discountValue,
    required this.isActive,
    required this.redemptionCount,
    this.code,
    this.maxDiscountAmount,
    this.minOrderValue,
    this.maxRedemptionsTotal,
    this.maxRedemptionsPerCustomer = 1,
    this.createdAt,
  });

  final String id;
  final String label;

  /// Server-rendered one-liner ("20% off up to ₹60"). The owner app shows this
  /// rather than composing its own, so the preview matches what the customer
  /// will actually read to the character.
  final String benefitText;

  /// 'PERCENT' or 'FLAT'.
  final String discountType;
  final double discountValue;
  final bool isActive;
  final int redemptionCount;

  /// Null when the offer is auto-surfaced on the outlet card with no code.
  final String? code;

  /// Required by the server for a percentage offer — see OfferEditScreen.
  final double? maxDiscountAmount;
  final double? minOrderValue;
  final int? maxRedemptionsTotal;
  final int maxRedemptionsPerCustomer;
  final String? createdAt;

  bool get isPercent => discountType == 'PERCENT';

  factory Offer.fromJson(Map<String, dynamic> json) => Offer(
        id: json['id']?.toString() ?? '',
        label: (json['label'] ?? '') as String,
        benefitText: (json['benefit_text'] ?? '') as String,
        discountType: (json['discount_type'] ?? 'FLAT') as String,
        discountValue: (json['discount_value'] as num?)?.toDouble() ?? 0,
        isActive: (json['is_active'] as bool?) ?? false,
        redemptionCount: (json['redemption_count'] as num?)?.toInt() ?? 0,
        code: json['code'] as String?,
        maxDiscountAmount: (json['max_discount_amount'] as num?)?.toDouble(),
        minOrderValue: (json['min_order_value'] as num?)?.toDouble(),
        maxRedemptionsTotal: (json['max_redemptions_total'] as num?)?.toInt(),
        maxRedemptionsPerCustomer:
            (json['max_redemptions_per_customer'] as num?)?.toInt() ?? 1,
        createdAt: json['created_at']?.toString(),
      );

  Offer copyWith({bool? isActive}) => Offer(
        id: id,
        label: label,
        benefitText: benefitText,
        discountType: discountType,
        discountValue: discountValue,
        isActive: isActive ?? this.isActive,
        redemptionCount: redemptionCount,
        code: code,
        maxDiscountAmount: maxDiscountAmount,
        minOrderValue: minOrderValue,
        maxRedemptionsTotal: maxRedemptionsTotal,
        maxRedemptionsPerCustomer: maxRedemptionsPerCustomer,
        createdAt: createdAt,
      );
}
