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
    this.locality,
    this.phoneNumber,
    this.latitude,
    this.longitude,
  });

  final String id;
  final String name;
  final String address;
  final bool isOpen;
  final double? distanceKm;
  final String? upiId;

  /// Area within the city (migration 012). Null for outlets that predate it —
  /// [displayName] then falls back to the bare name.
  final String? locality;

  /// Outlet contact number (migration 009). Null for MOST outlets — 5 of the 6
  /// customer-visible ones in prod have none — so the call action is hidden
  /// rather than rendered as a button that cannot dial.
  final String? phoneNumber;

  /// True only when there is actually a number to call.
  bool get canCall => phoneNumber != null && phoneNumber!.trim().isNotEmpty;

  /// Outlet coordinates, used only to hand off to Google Maps. Null when the
  /// outlet never captured a pin; the Maps button hides rather than linking
  /// nowhere. NOT used for distance — that stays server-computed in
  /// [distanceKm] from the customer's GPS origin.
  final double? latitude;
  final double? longitude;

  /// "{Restaurant Name} · {Locality}", or just the name when there is no
  /// locality on record. One definition, so the list and the confirm screen
  /// can never drift apart.
  String get displayName =>
      (locality != null && locality!.isNotEmpty) ? '$name · $locality' : name;

  /// True only when Maps can actually be opened for this outlet.
  bool get hasCoordinates => latitude != null && longitude != null;

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
    final loc = json['locality'] as String?;
    final phone = json['phone_number'] as String?;
    final lat = json['latitude'];
    final lng = json['longitude'];
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
      locality: (loc != null && loc.isNotEmpty) ? loc : null,
      phoneNumber: (phone != null && phone.trim().isNotEmpty) ? phone.trim() : null,
      // `num?` then toDouble(): the column is Postgres `numeric`, so a value
      // that happens to be whole arrives as an int and a bare `as double`
      // cast would throw.
      latitude: (lat as num?)?.toDouble(),
      longitude: (lng as num?)?.toDouble(),
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
        'locality': locality,
        'phone_number': phoneNumber,
        'latitude': latitude,
        'longitude': longitude,
      };
}
