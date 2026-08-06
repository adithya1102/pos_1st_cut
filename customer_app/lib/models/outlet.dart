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

  factory Outlet.fromJson(Map<String, dynamic> json) {
    final dist = json['distance_km'];
    final upi = json['upi_id'] as String?;
    final img = json['image_url'] as String?;
    return Outlet(
      id: json['id']?.toString() ?? '',
      name: (json['name'] ?? '') as String,
      address: (json['address'] ?? '') as String,
      isOpen: (json['is_open'] ?? false) as bool,
      distanceKm: dist == null ? null : (dist as num).toDouble(),
      upiId: (upi != null && upi.isNotEmpty) ? upi : null,
      imageUrl: (img != null && img.isNotEmpty) ? img : null,
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
      };
}
