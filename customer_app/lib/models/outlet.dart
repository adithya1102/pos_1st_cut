/// A nearby restaurant/outlet available for self pickup.
class Outlet {
  const Outlet({
    required this.id,
    required this.name,
    required this.address,
    required this.isOpen,
    this.distanceKm,
    this.upiId,
    this.imageUrl,
    this.offerCount = 0,
    this.offerText,
  });

  final String id;
  final String name;
  final String address;
  final bool isOpen;
  final double? distanceKm;
  final String? upiId;

  /// Storefront photo (migration 011). Null for outlets that never set one —
  /// the card falls back to the generic restaurant glyph.
  final String? imageUrl;

  /// Offer summary (migration 016), returned inline by /customer/outlets so the
  /// discovery list needs no second request. Counts this restaurant's own
  /// offers plus every CareVo campaign that reaches it; [offerText] is the
  /// headline one. 0 / null means the card renders as it always did.
  final int offerCount;
  final String? offerText;

  bool get hasOffers => offerCount > 0 && (offerText?.isNotEmpty ?? false);

  factory Outlet.fromJson(Map<String, dynamic> json) {
    final dist = json['distance_km'];
    final upi = json['upi_id'] as String?;
    final img = json['image_url'] as String?;
    final offer = json['offer_text'] as String?;
    return Outlet(
      id: json['id']?.toString() ?? '',
      name: (json['name'] ?? '') as String,
      address: (json['address'] ?? '') as String,
      isOpen: (json['is_open'] ?? false) as bool,
      distanceKm: dist == null ? null : (dist as num).toDouble(),
      upiId: (upi != null && upi.isNotEmpty) ? upi : null,
      imageUrl: (img != null && img.isNotEmpty) ? img : null,
      offerCount: (json['offer_count'] as num?)?.toInt() ?? 0,
      offerText: (offer != null && offer.isNotEmpty) ? offer : null,
    );
  }

  /// Round-trips through [Outlet.fromJson], so the persisted cart's outlet
  /// restores with the same shape the API returns.
  Map<String, dynamic> toJson() => {
        'id': id,
        'name': name,
        'address': address,
        'is_open': isOpen,
        'distance_km': distanceKm,
        'upi_id': upiId,
        'image_url': imageUrl,
        'offer_count': offerCount,
        'offer_text': offerText,
      };
}
