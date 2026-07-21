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

  /// A stable signature used to merge identical configurations.
  String get signature {
    final opts = selectedOptions
        .map((o) => '${o.groupName}:${o.optionName}')
        .toList()
      ..sort();
    return '${item.id}|${opts.join(',')}|${notes?.trim() ?? ''}';
  }
}
