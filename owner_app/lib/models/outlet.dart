/// Represents the staff member's outlet and its public visibility state.
class Outlet {
  final String id;
  final String locationName;
  final bool isVisible;

  /// Storefront photo shown on the customer app's outlet card (migration 011).
  /// Null until the owner uploads one.
  final String? imageUrl;

  /// Daily opening/closing schedule as "HH:MM" (24h local), or null when unset
  /// (migration 024). Null = no schedule; the outlet accepts orders any time
  /// until the manual toggle or the customer app says otherwise.
  final String? openingTime;
  final String? closingTime;

  /// The owner's on-demand "temporarily closed" switch. Independent of the
  /// schedule and of [isVisible].
  final bool isManuallyClosed;

  /// The live status the backend computes from hours + the toggle:
  /// 'open' | 'closing_soon' | 'closed'. Lets the owner see exactly what a
  /// customer sees right now.
  final String orderStatus;

  const Outlet({
    required this.id,
    required this.locationName,
    required this.isVisible,
    this.imageUrl,
    this.openingTime,
    this.closingTime,
    this.isManuallyClosed = false,
    this.orderStatus = 'open',
  });

  factory Outlet.fromJson(Map<String, dynamic> json) {
    String? nonEmpty(Object? v) =>
        (v is String && v.trim().isNotEmpty) ? v.trim() : null;
    return Outlet(
      id: json['id'] as String,
      locationName: (json['location_name'] as String?) ?? '',
      isVisible: (json['is_visible'] as bool?) ?? false,
      imageUrl: nonEmpty(json['image_url']),
      openingTime: nonEmpty(json['opening_time']),
      closingTime: nonEmpty(json['closing_time']),
      isManuallyClosed: (json['is_manually_closed'] as bool?) ?? false,
      orderStatus: nonEmpty(json['order_status']) ?? 'open',
    );
  }

  Outlet copyWith({
    bool? isVisible,
    String? imageUrl,
    String? openingTime,
    String? closingTime,
    bool? isManuallyClosed,
    String? orderStatus,
  }) {
    return Outlet(
      id: id,
      locationName: locationName,
      isVisible: isVisible ?? this.isVisible,
      imageUrl: imageUrl ?? this.imageUrl,
      openingTime: openingTime ?? this.openingTime,
      closingTime: closingTime ?? this.closingTime,
      isManuallyClosed: isManuallyClosed ?? this.isManuallyClosed,
      orderStatus: orderStatus ?? this.orderStatus,
    );
  }
}
