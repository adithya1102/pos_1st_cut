/// A single dish in the flat (no-category) menu list.
class MenuItem {
  final int id;
  final String name;
  final bool isAvailable;
  final bool isActive;
  final double basePrice;

  const MenuItem({
    required this.id,
    required this.name,
    required this.isAvailable,
    required this.isActive,
    required this.basePrice,
  });

  factory MenuItem.fromJson(Map<String, dynamic> json) {
    return MenuItem(
      id: json['id'] as int,
      name: (json['name'] as String?) ?? '',
      isAvailable: (json['is_available'] as bool?) ?? false,
      isActive: (json['is_active'] as bool?) ?? true,
      basePrice: _toDouble(json['base_price']),
    );
  }

  MenuItem copyWith({bool? isAvailable}) {
    return MenuItem(
      id: id,
      name: name,
      isAvailable: isAvailable ?? this.isAvailable,
      isActive: isActive,
      basePrice: basePrice,
    );
  }

  static double _toDouble(dynamic value) {
    if (value is num) return value.toDouble();
    if (value is String) return double.tryParse(value) ?? 0.0;
    return 0.0;
  }
}
