import '../models/offer.dart';
import 'api_client.dart';

/// `/pos/offers` — the restaurant's own offers (migration 016).
///
/// Note the absence of an outlet id in every signature. The endpoint resolves
/// it from the staff JWT (`_require_outlet`), the same way `/pos/menu-items`
/// does, so this app cannot address another restaurant's offers even by mistake.
class OfferService {
  final ApiClient _client;

  OfferService(this._client);

  Future<List<Offer>> list() async {
    final data = await _client.get('/pos/offers');
    final list = (data as List<dynamic>?) ?? const [];
    return list
        .map((e) => Offer.fromJson(e as Map<String, dynamic>))
        .toList();
  }

  /// `POST /pos/offers`.
  ///
  /// [maxDiscountAmount] is mandatory when [discountType] is 'PERCENT'. The
  /// form enforces it, and so does the server (and so does a CHECK constraint)
  /// — a percentage with no ceiling is how a single large order eats a week of
  /// margin.
  Future<Offer> create({
    required String discountType,
    required double discountValue,
    double? maxDiscountAmount,
    double? minOrderValue,
    String? code,
    int? maxRedemptionsTotal,
    int maxRedemptionsPerCustomer = 1,
    bool isActive = false,
  }) async {
    final data = await _client.post('/pos/offers', body: {
      'discount_type': discountType,
      'discount_value': discountValue,
      if (maxDiscountAmount != null) 'max_discount_amount': maxDiscountAmount,
      if (minOrderValue != null) 'min_order_value': minOrderValue,
      if (code != null && code.isNotEmpty) 'code': code,
      if (maxRedemptionsTotal != null)
        'max_redemptions_total': maxRedemptionsTotal,
      'max_redemptions_per_customer': maxRedemptionsPerCustomer,
      'is_active': isActive,
    });
    return Offer.fromJson(data as Map<String, dynamic>);
  }

  /// `PATCH /pos/offers/{id}` — only the fields provided are written.
  ///
  /// Nulls are omitted rather than sent, so "not editing this" and "clear this"
  /// stay distinguishable; the form always resends the full set it manages.
  Future<Offer> update(
    String offerId, {
    String? discountType,
    double? discountValue,
    double? maxDiscountAmount,
    double? minOrderValue,
    String? code,
    int? maxRedemptionsTotal,
    int? maxRedemptionsPerCustomer,
    bool? isActive,
  }) async {
    final data = await _client.patch('/pos/offers/$offerId', body: {
      if (discountType != null) 'discount_type': discountType,
      if (discountValue != null) 'discount_value': discountValue,
      if (maxDiscountAmount != null) 'max_discount_amount': maxDiscountAmount,
      if (minOrderValue != null) 'min_order_value': minOrderValue,
      if (code != null) 'code': code,
      if (maxRedemptionsTotal != null)
        'max_redemptions_total': maxRedemptionsTotal,
      if (maxRedemptionsPerCustomer != null)
        'max_redemptions_per_customer': maxRedemptionsPerCustomer,
      if (isActive != null) 'is_active': isActive,
    });
    return Offer.fromJson(data as Map<String, dynamic>);
  }

  Future<Offer> setActive(String offerId, bool isActive) =>
      update(offerId, isActive: isActive);
}
