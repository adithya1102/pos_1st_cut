/// A single dish in the flat (no-category) menu list.
class MenuItem {
  final String id;
  final String name;
  final bool isAvailable;
  final bool isActive;
  final double basePrice;
  final bool isVeg;
  final int? prepTimeMinutes;
  final String? imageUrl;
  final String? categoryId;
  final String? categoryName;

  const MenuItem({
    required this.id,
    required this.name,
    required this.isAvailable,
    required this.isActive,
    required this.basePrice,
    this.isVeg = true,
    this.prepTimeMinutes,
    this.imageUrl,
    this.categoryId,
    this.categoryName,
  });

  factory MenuItem.fromJson(Map<String, dynamic> json) {
    return MenuItem(
      id: json['id'] as String,
      name: (json['name'] as String?) ?? '',
      isAvailable: (json['is_available'] as bool?) ?? false,
      isActive: (json['is_active'] as bool?) ?? true,
      basePrice: _toDouble(json['base_price']),
      isVeg: (json['is_veg'] as bool?) ?? true,
      prepTimeMinutes: json['prep_time_minutes'] as int?,
      imageUrl: json['image_url'] as String?,
      categoryId: json['category_id'] as String?,
      categoryName: json['category_name'] as String?,
    );
  }

  MenuItem copyWith({bool? isAvailable}) {
    return MenuItem(
      id: id,
      name: name,
      isAvailable: isAvailable ?? this.isAvailable,
      isActive: isActive,
      basePrice: basePrice,
      isVeg: isVeg,
      prepTimeMinutes: prepTimeMinutes,
      imageUrl: imageUrl,
      categoryId: categoryId,
      categoryName: categoryName,
    );
  }

  static double _toDouble(dynamic value) {
    if (value is num) return value.toDouble();
    if (value is String) return double.tryParse(value) ?? 0.0;
    return 0.0;
  }
}
