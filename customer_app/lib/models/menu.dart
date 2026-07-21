// Menu domain models. Parsing is deliberately tolerant because the
// backend is being built in parallel and the `customizations` shape may
// arrive as either structured option groups or a flat list of strings.

class MenuResponse {
  const MenuResponse({required this.outletId, required this.categories});

  final String outletId;
  final List<MenuCategory> categories;

  factory MenuResponse.fromJson(Map<String, dynamic> json) {
    final cats = (json['categories'] as List<dynamic>? ?? [])
        .map((e) => MenuCategory.fromJson(e as Map<String, dynamic>))
        .toList();
    return MenuResponse(
      outletId: json['outlet_id']?.toString() ?? '',
      categories: cats,
    );
  }
}

class MenuCategory {
  const MenuCategory({required this.id, required this.name, required this.items});

  final String id;
  final String name;
  final List<MenuItem> items;

  factory MenuCategory.fromJson(Map<String, dynamic> json) {
    final items = (json['items'] as List<dynamic>? ?? [])
        .map((e) => MenuItem.fromJson(e as Map<String, dynamic>))
        .toList();
    return MenuCategory(
      id: json['id']?.toString() ?? '',
      name: (json['name'] ?? '') as String,
      items: items,
    );
  }
}

class MenuItem {
  const MenuItem({
    required this.id,
    required this.name,
    required this.basePrice,
    required this.isVeg,
    required this.isAvailable,
    required this.prepTimeMinutes,
    required this.tags,
    required this.customizations,
  });

  final String id;
  final String name;
  final double basePrice;
  final bool isVeg;
  final bool isAvailable;
  final int prepTimeMinutes;
  final List<String> tags;
  final List<CustomizationGroup> customizations;

  factory MenuItem.fromJson(Map<String, dynamic> json) {
    return MenuItem(
      id: json['id']?.toString() ?? '',
      name: (json['name'] ?? '') as String,
      basePrice: (json['base_price'] as num?)?.toDouble() ?? 0,
      isVeg: (json['is_veg'] ?? true) as bool,
      isAvailable: (json['is_available'] ?? true) as bool,
      prepTimeMinutes: (json['prep_time_minutes'] as num?)?.toInt() ?? 0,
      tags: ((json['tags'] as List<dynamic>?) ?? [])
          .map((e) => e.toString())
          .toList(),
      customizations: CustomizationGroup.listFrom(json['customizations']),
    );
  }
}

/// A group of choices, e.g. "Size" -> Regular / Large.
class CustomizationGroup {
  const CustomizationGroup({
    required this.name,
    required this.required,
    required this.multiSelect,
    required this.options,
  });

  final String name;
  final bool required;
  final bool multiSelect;
  final List<CustomizationOption> options;

  /// Tolerant parser: accepts a list of group maps, or a flat list of
  /// strings (treated as a single optional group).
  static List<CustomizationGroup> listFrom(dynamic raw) {
    if (raw is! List) return const [];
    if (raw.isEmpty) return const [];

    // Flat list of strings -> single group of single-select options.
    if (raw.every((e) => e is String)) {
      return [
        CustomizationGroup(
          name: 'Options',
          required: false,
          multiSelect: false,
          options: raw
              .map((e) => CustomizationOption(name: e as String, priceDelta: 0))
              .toList(),
        ),
      ];
    }

    return raw.whereType<Map<String, dynamic>>().map((g) {
      final type = (g['type'] ?? '').toString().toLowerCase();
      final rawOptions = g['options'] as List<dynamic>? ?? [];
      return CustomizationGroup(
        name: (g['name'] ?? 'Options') as String,
        required: (g['required'] ?? false) as bool,
        multiSelect: (g['multi_select'] ?? (type == 'multi')) as bool,
        options: rawOptions.map((o) {
          if (o is String) return CustomizationOption(name: o, priceDelta: 0);
          final m = o as Map<String, dynamic>;
          return CustomizationOption(
            name: (m['name'] ?? '') as String,
            priceDelta: (m['price_delta'] as num?)?.toDouble() ?? 0,
          );
        }).toList(),
      );
    }).toList();
  }
}

class CustomizationOption {
  const CustomizationOption({required this.name, required this.priceDelta});

  final String name;
  final double priceDelta;
}
