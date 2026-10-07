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

  /// Limited quantity for today (backend migration 033).
  ///
  /// NULL means UNTRACKED — unlimited, which is how every dish behaves until
  /// an owner opts it in. That is why this is nullable rather than defaulting
  /// to 0: 0 means "counted, and there are none left", and collapsing the two
  /// would make turning tracking off look identical to selling out.
  final int? stockRemaining;

  /// True when this dish is counted at all.
  bool get isStockTracked => stockRemaining != null;

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
    this.stockRemaining,
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
      // Absent on an older backend, which reads as untracked — the safe
      // default, since untracked never blocks an order.
      stockRemaining: (json['stock_remaining'] as num?)?.toInt(),
    );
  }

  /// [clearStock] exists because `stockRemaining: null` cannot express
  /// "set this to untracked" — a null argument is indistinguishable from an
  /// omitted one in Dart's optional parameters. Without it, turning tracking
  /// OFF would be the one state this method could not reach.
  MenuItem copyWith({
    bool? isAvailable,
    int? stockRemaining,
    bool clearStock = false,
  }) {
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
      stockRemaining:
          clearStock ? null : (stockRemaining ?? this.stockRemaining),
    );
  }

  static double _toDouble(dynamic value) {
    if (value is num) return value.toDouble();
    if (value is String) return double.tryParse(value) ?? 0.0;
    return 0.0;
  }
}
