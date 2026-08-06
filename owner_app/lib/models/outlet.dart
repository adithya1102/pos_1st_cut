/// Represents the staff member's outlet and its public visibility state.
class Outlet {
  final String id;
  final String locationName;
  final bool isVisible;

  /// Storefront photo shown on the customer app's outlet card (migration 011).
  /// Null until the owner uploads one.
  final String? imageUrl;

  const Outlet({
    required this.id,
    required this.locationName,
    required this.isVisible,
    this.imageUrl,
  });

  factory Outlet.fromJson(Map<String, dynamic> json) {
    return Outlet(
      id: json['id'] as String,
      locationName: (json['location_name'] as String?) ?? '',
      isVisible: (json['is_visible'] as bool?) ?? false,
      imageUrl: (json['image_url'] as String?)?.isNotEmpty == true
          ? json['image_url'] as String
          : null,
    );
  }

  Outlet copyWith({bool? isVisible, String? imageUrl}) {
    return Outlet(
      id: id,
      locationName: locationName,
      isVisible: isVisible ?? this.isVisible,
      imageUrl: imageUrl ?? this.imageUrl,
    );
  }
}
