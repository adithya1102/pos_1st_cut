import 'menu.dart';

/// A selected option within a cart line, remembering its price delta so
/// the line total is stable even if the menu reloads.
class SelectedOption {
  const SelectedOption({
    required this.groupName,
    required this.optionName,
    required this.priceDelta,
  });

  final String groupName;
  final String optionName;
  final double priceDelta;

  Map<String, dynamic> toJson() => {
        'group_name': groupName,
        'option_name': optionName,
        'price_delta': priceDelta,
      };

  factory SelectedOption.fromJson(Map<String, dynamic> json) => SelectedOption(
        groupName: json['group_name']?.toString() ?? '',
        optionName: json['option_name']?.toString() ?? '',
        priceDelta: (json['price_delta'] as num?)?.toDouble() ?? 0,
      );
}

/// A single configured line in the cart.
class CartItem {
  CartItem({
    required this.lineId,
    required this.item,
    required this.quantity,
    required this.selectedOptions,
    this.notes,
  });

  final String lineId;
  final MenuItem item;
  int quantity;
  final List<SelectedOption> selectedOptions;
  String? notes;

  double get unitPrice =>
      item.basePrice +
      selectedOptions.fold(0.0, (sum, o) => sum + o.priceDelta);

  double get lineTotal => unitPrice * quantity;

  /// Serialize to the shape expected by `POST /customer/orders`.
  Map<String, dynamic> toOrderItemJson() => {
        'menu_item_id': item.id,
        'quantity': quantity,
        if (selectedOptions.isNotEmpty)
          'customizations': selectedOptions
              .map((o) => {'group': o.groupName, 'option': o.optionName})
              .toList(),
        if (notes != null && notes!.trim().isNotEmpty)
          'item_notes': notes!.trim(),
      };

  /// Serialize for on-device cart persistence (NOT the order payload).
  ///
  /// The embedded [MenuItem] is stored as a price/name snapshot without its
  /// customization groups: a restored line is display-and-quantity only (the
  /// cart screen has no line editor), and its already-chosen
  /// [selectedOptions] carry the price deltas the total depends on.
  Map<String, dynamic> toJson() => {
        'line_id': lineId,
        'item': item.toCartSnapshotJson(),
        'quantity': quantity,
        'selected_options': selectedOptions.map((o) => o.toJson()).toList(),
        'notes': notes,
      };

  factory CartItem.fromJson(Map<String, dynamic> json) => CartItem(
        lineId: json['line_id']?.toString() ?? 'l0',
        item: MenuItem.fromCartSnapshotJson(
          (json['item'] as Map?)?.cast<String, dynamic>() ?? const {},
        ),
        quantity: int.tryParse(json['quantity']?.toString() ?? '') ?? 1,
        selectedOptions: ((json['selected_options'] as List?) ?? const [])
            .whereType<Map>()
            .map((o) => SelectedOption.fromJson(o.cast<String, dynamic>()))
            .toList(),
        notes: json['notes']?.toString(),
      );

  /// A stable signature used to merge identical configurations.
  String get signature {
    final opts = selectedOptions
        .map((o) => '${o.groupName}:${o.optionName}')
        .toList()
      ..sort();
    return '${item.id}|${opts.join(',')}|${notes?.trim() ?? ''}';
  }
}
