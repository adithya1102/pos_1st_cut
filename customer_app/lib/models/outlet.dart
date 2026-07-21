/// A nearby restaurant/outlet available for self pickup.
class Outlet {
  const Outlet({
    required this.id,
    required this.name,
    required this.address,
    required this.isOpen,
    this.distanceKm,
  });

  final String id;
  final String name;
  final String address;
  final bool isOpen;
  final double? distanceKm;

  factory Outlet.fromJson(Map<String, dynamic> json) {
    final dist = json['distance_km'];
    return Outlet(
      id: json['id']?.toString() ?? '',
      name: (json['name'] ?? '') as String,
      address: (json['address'] ?? '') as String,
      isOpen: (json['is_open'] ?? false) as bool,
      distanceKm: dist == null ? null : (dist as num).toDouble(),
    );
  }
}
