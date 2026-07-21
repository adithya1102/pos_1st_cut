import 'package:flutter/foundation.dart';

import '../models/cart_item.dart';
import '../models/menu.dart';
import '../models/outlet.dart';

/// Client-side cart. Tied to a single outlet; switching outlets clears it.
class CartState extends ChangeNotifier {
  final List<CartItem> _items = [];
  List<CartItem> get items => List.unmodifiable(_items);

  Outlet? _outlet;
  Outlet? get outlet => _outlet;
  String? get outletId => _outlet?.id;

  int _lineCounter = 0;

  int get totalQuantity => _items.fold(0, (sum, i) => sum + i.quantity);
  double get subtotal => _items.fold(0.0, (sum, i) => sum + i.lineTotal);
  bool get isEmpty => _items.isEmpty;

  /// Ensure the cart belongs to [outlet]; clear if switching restaurants.
  void setOutlet(Outlet outlet) {
    if (_outlet?.id != outlet.id) {
      _items.clear();
      _lineCounter = 0;
    }
    _outlet = outlet;
    notifyListeners();
  }

  void addItem(
    MenuItem item, {
    int quantity = 1,
    List<SelectedOption> options = const [],
    String? notes,
  }) {
    final candidate = CartItem(
      lineId: 'l${_lineCounter++}',
      item: item,
      quantity: quantity,
      selectedOptions: List.of(options),
      notes: notes,
    );

    // Merge with an existing identical configuration.
    final existing = _items
        .where((c) => c.signature == candidate.signature)
        .cast<CartItem?>()
        .firstWhere((_) => true, orElse: () => null);

    if (existing != null) {
      existing.quantity += quantity;
    } else {
      _items.add(candidate);
    }
    notifyListeners();
  }

  void increment(String lineId) {
    final line = _find(lineId);
    if (line != null) {
      line.quantity++;
      notifyListeners();
    }
  }

  void decrement(String lineId) {
    final line = _find(lineId);
    if (line == null) return;
    line.quantity--;
    if (line.quantity <= 0) {
      _items.removeWhere((i) => i.lineId == lineId);
    }
    notifyListeners();
  }

  void removeLine(String lineId) {
    _items.removeWhere((i) => i.lineId == lineId);
    notifyListeners();
  }

  void clear() {
    _items.clear();
    _lineCounter = 0;
    notifyListeners();
  }

  CartItem? _find(String lineId) {
    for (final i in _items) {
      if (i.lineId == lineId) return i;
    }
    return null;
  }

  /// Build the `POST /customer/orders` payload.
  Map<String, dynamic> toOrderPayload({String? customerNotes}) => {
        'outlet_id': _outlet?.id,
        'items': _items.map((i) => i.toOrderItemJson()).toList(),
        if (customerNotes != null && customerNotes.trim().isNotEmpty)
          'customer_notes': customerNotes.trim(),
      };
}
