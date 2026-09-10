/// One travel mode the server says this outlet's city offers (migration 030).
///
/// `usesDeclaredArrival` is the load-bearing field. It tells the app to swap
/// origin resolution for a time picker WITHOUT the app needing to know the mode
/// by name — which is what lets a mode added server-side behave correctly in a
/// build that predates it.
class OutletTransportMode {
  const OutletTransportMode({
    required this.code,
    required this.label,
    required this.usesDeclaredArrival,
  });

  final String code;
  final String label;
  final bool usesDeclaredArrival;

  /// Tolerant of a malformed entry: anything without a usable `code` is
  /// dropped by [parseList] rather than rendering a blank chip.
  static OutletTransportMode? tryParse(Object? raw) {
    if (raw is! Map) return null;
    final code = (raw['code'] as String?)?.trim() ?? '';
    if (code.isEmpty) return null;
    return OutletTransportMode(
      code: code,
      label: (raw['label'] as String?)?.trim() ?? code,
      usesDeclaredArrival: raw['uses_declared_arrival'] == true,
    );
  }

  static List<OutletTransportMode>? parseList(Object? raw) {
    if (raw is! List) return null;
    final out = <OutletTransportMode>[];
    for (final e in raw) {
      final m = tryParse(e);
      if (m != null) out.add(m);
    }
    // An EMPTY list from the server is a real answer ("this city offers
    // nothing"), not a missing one — so it is kept, not collapsed to null.
    // Only an absent/!List key means "the server did not say".
    return out;
  }

  Map<String, dynamic> toJson() => {
        'code': code,
        'label': label,
        'uses_declared_arrival': usesDeclaredArrival,
      };
}

/// A nearby restaurant/outlet available for self pickup.
class Outlet {
  const Outlet({
    required this.id,
    required this.name,
    required this.address,
    required this.isOpen,
    this.orderStatus = 'open',
    this.closedReason,
    this.distanceKm,
    this.upiId,
    this.imageUrl,
    this.offerCount = 0,
    this.offerText,
    this.locality,
    this.city,
    this.cityType,
    this.hasMetro,
    this.hasTrain,
    this.transportModes,
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

  /// True only when the outlet is accepting new orders right now. Real as of
  /// migration 024 — the backend used to hardcode it `true`, and now computes
  /// it from hours + the manual-closed toggle. Prefer [isAcceptingOrders] /
  /// [orderStatus] in the UI: is_open collapses "closing soon" into false, and
  /// the three-state [orderStatus] is what distinguishes the two closed reasons.
  final bool isOpen;

  /// Three-state operating status the backend computes (migration 024):
  /// 'open' | 'closing_soon' | 'closed'. Single source of truth — the same
  /// function that gates order creation server-side produces this, so the
  /// label and the block cannot disagree.
  final String orderStatus;

  /// Why the outlet is not taking orders, when [orderStatus] is not 'open'.
  /// Null while open. Shown verbatim beside the disabled order action.
  final String? closedReason;

  /// True when a customer may place an order now.
  bool get isAcceptingOrders => orderStatus == 'open';

  /// Short label for the status badge.
  String get statusLabel => switch (orderStatus) {
        'closing_soon' => 'Closing soon',
        'closed' => 'Closed',
        _ => 'Open',
      };
  final double? distanceKm;
  final String? upiId;

  /// Area within the city (migration 012). Null for outlets that predate it —
  /// [displayName] then falls back to the bare name.
  final String? locality;

  /// The outlet's city, as its own value rather than the tail of [address].
  ///
  /// [address] is "{locality}, {city}", so reading the city used to mean
  /// splitting that string — which breaks for outlets predating migration 012,
  /// where [address] IS the bare city and there is no comma. Behaviour is keyed
  /// off this (checkout offers Train only where the city has rail), and keying
  /// behaviour off a display string is how that kind of thing silently breaks.
  ///
  /// Null for any response predating this field, which the transport lookup
  /// treats as "no rail" — the safe direction.
  final String? city;

  /// The server's transport profile for [city] (migration 029).
  ///
  /// `metro` | `tier_1` | `tier_2` | `tier_3`, or null when this deployment has
  /// no answer — an older backend, or a city with no `cities` row.
  final String? cityType;

  /// Whether this city offers Metro / Train, **as the server sees it**.
  ///
  /// Nullable, and null is NOT false. Three states, and the third is the whole
  /// reason these are `bool?`:
  ///
  ///   true  — the admin marked this city as having it
  ///   false — the admin marked this city as NOT having it
  ///   null  — the server did not say, so [CityTransport] falls back to the
  ///           built-in map
  ///
  /// Flatten null to false and every city loses Train the moment the app talks
  /// to a backend that predates migration 029 — a silent regression on a screen
  /// nobody would think to re-test.
  final bool? hasMetro;
  final bool? hasTrain;

  /// The full enabled mode list for this outlet's city (migration 030).
  ///
  /// THE authoritative answer when present — [hasMetro]/[hasTrain] are derived
  /// from the same source server-side and exist only for builds that predate
  /// this field. Null means the server did not say (pre-030 backend, or a city
  /// with no `cities` row), and the app falls back to the older fields and then
  /// to its built-in map.
  ///
  /// An EMPTY list is a real answer, not a missing one — see
  /// [OutletTransportMode.parseList].
  final List<OutletTransportMode>? transportModes;

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
    final cty = json['city'] as String?;
    final phone = json['phone_number'] as String?;
    final lat = json['latitude'];
    final lng = json['longitude'];
    return Outlet(
      id: json['id']?.toString() ?? '',
      name: (json['name'] ?? '') as String,
      address: (json['address'] ?? '') as String,
      isOpen: (json['is_open'] ?? false) as bool,
      // order_status is the authority; is_open is the coarse fallback for any
      // response predating migration 024.
      orderStatus: (json['order_status'] as String?)?.trim().isNotEmpty == true
          ? (json['order_status'] as String).trim()
          : ((json['is_open'] ?? true) == false ? 'closed' : 'open'),
      closedReason: (json['closed_reason'] as String?)?.trim().isNotEmpty == true
          ? (json['closed_reason'] as String).trim()
          : null,
      distanceKm: dist == null ? null : (dist as num).toDouble(),
      upiId: (upi != null && upi.isNotEmpty) ? upi : null,
      imageUrl: (img != null && img.isNotEmpty) ? img : null,
      offerCount: (json['offer_count'] as num?)?.toInt() ?? 0,
      offerText: (offer != null && offer.isNotEmpty) ? offer : null,
      locality: (loc != null && loc.isNotEmpty) ? loc : null,
      city: (cty != null && cty.trim().isNotEmpty) ? cty.trim() : null,
      // Read as `bool?` with NO ?? default, deliberately: a missing key must
      // stay null so CityTransport can tell "server says no" from "server said
      // nothing". See [hasMetro].
      cityType: (json['city_type'] as String?)?.trim().isNotEmpty == true
          ? (json['city_type'] as String).trim()
          : null,
      hasMetro: json['has_metro'] as bool?,
      hasTrain: json['has_train'] as bool?,
      transportModes: OutletTransportMode.parseList(json['transport_modes']),
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
        'order_status': orderStatus,
        'closed_reason': closedReason,
        'distance_km': distanceKm,
        'upi_id': upiId,
        'image_url': imageUrl,
        'offer_count': offerCount,
        'offer_text': offerText,
        'locality': locality,
        'city': city,
        // Carried through the cart's persistence too, not just the API read:
        // checkout renders its mode chips from the RESTORED outlet, so dropping
        // these here would make Metro/Train vanish on any cold start with a
        // saved cart — while still appearing on a fresh browse.
        'city_type': cityType,
        'has_metro': hasMetro,
        'has_train': hasTrain,
        'transport_modes': transportModes?.map((m) => m.toJson()).toList(),
        'phone_number': phoneNumber,
        'latitude': latitude,
        'longitude': longitude,
        'opening_time': opensAt,
        'closing_time': closesAt,
        'created_at': createdAt?.toIso8601String(),
      };
}
