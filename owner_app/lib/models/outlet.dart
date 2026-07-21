/// Represents the staff member's outlet and its public visibility state.
class Outlet {
  final int id;
  final String locationName;
  final bool isVisible;

  const Outlet({
    required this.id,
    required this.locationName,
    required this.isVisible,
  });

  factory Outlet.fromJson(Map<String, dynamic> json) {
    return Outlet(
      id: json['id'] as int,
      locationName: (json['location_name'] as String?) ?? '',
      isVisible: (json['is_visible'] as bool?) ?? false,
    );
  }

  Outlet copyWith({bool? isVisible}) {
    return Outlet(
      id: id,
      locationName: locationName,
      isVisible: isVisible ?? this.isVisible,
    );
  }
}
