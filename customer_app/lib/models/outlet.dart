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
    this.opensAt,
    this.closesAt,
    this.createdAt,
  });

  final String id;
  final String name;
  final String address;

  /// Parsed and kept for API round-tripping (cart persistence serialises an
  /// outlet snapshot through this model), but NOT used to render or gate
  /// anything in the UI. `CarevoService.list_outlets` hardcodes this to `true`
  /// for every outlet, so it carries no real information — see the OPEN-pill
  /// removal in `outlets_screen.dart` for the client-side half of this.
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

  /// Serving hours, as the API reports them ("09:00", "22:30").
  ///
  /// ## Currently ALWAYS null, and that is a backend gap, not a bug here
  ///
  /// The `outlets` table has no hours columns — checked against every migration
  /// 001-021, none of which adds one — so `/customer/outlets` has nothing to
  /// send. The fields, the parsing and [hoursLabel] are wired up so the display
  /// lights up the moment a migration adds them, and every consumer HIDES the
  /// line while they are null rather than inventing plausible hours. A guessed
  /// "10am - 10pm" is the one failure mode worth avoiding completely: it sends
  /// someone to a shut restaurant with the app's word for it.
  ///
  /// Note that `is_open` is not a substitute — the backend hardcodes it to
  /// `true` for every outlet (`carevo_customer/service.py`), so the OPEN pill
  /// and the "Open now" filter currently assert nothing.
  final String? opensAt;
  final String? closesAt;

  bool get hasHours =>
      (opensAt?.isNotEmpty ?? false) && (closesAt?.isNotEmpty ?? false);

  /// When this outlet joined the platform. Backs the "Newest" sort.
  ///
  /// Unlike [opensAt], this is REAL data — `outlets.created_at` has always
  /// existed; it simply was not being sent to the app until the sort needed
  /// it. Null only for a row whose column is null, which sorts last rather
  /// than being guessed at.
  final DateTime? createdAt;

  /// "9:00 am - 10:30 pm", or null when the hours are unknown.
  String? get hoursLabel {
    if (!hasHours) return null;
    final open = _friendlyTime(opensAt!);
    final close = _friendlyTime(closesAt!);
    if (open == null || close == null) return null;
    return '$open - $close';
  }

  /// "22:30" -> "10:30 pm". Returns null for anything it cannot parse, so a
  /// surprising format degrades to hiding the line rather than to rendering
  /// something wrong.
  static String? _friendlyTime(String raw) {
    final parts = raw.trim().split(':');
    if (parts.length < 2) return null;
    final h = int.tryParse(parts[0]);
    final m = int.tryParse(parts[1]);
    if (h == null || m == null || h < 0 || h > 23 || m < 0 || m > 59) {
      return null;
    }
    final suffix = h < 12 ? 'am' : 'pm';
    final hour12 = h % 12 == 0 ? 12 : h % 12;
    return '$hour12:${m.toString().padLeft(2, '0')} $suffix';
  }

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
      // Absent from every response today — see [opensAt].
      opensAt: (json['opening_time'] as String?)?.trim(),
      closesAt: (json['closing_time'] as String?)?.trim(),
      // tryParse, not parse: a malformed timestamp leaves this null (sorts
      // last under "Newest") rather than throwing and blanking the whole list.
      createdAt: DateTime.tryParse(json['created_at']?.toString() ?? ''),
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
        'opening_time': opensAt,
        'closing_time': closesAt,
        'created_at': createdAt?.toIso8601String(),
      };
}
