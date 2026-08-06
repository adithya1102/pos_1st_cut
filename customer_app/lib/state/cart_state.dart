import 'dart:convert';

import 'package:flutter/foundation.dart';
import 'package:shared_preferences/shared_preferences.dart';

import '../models/cart_item.dart';
import '../models/menu.dart';
import '../models/outlet.dart';

/// Client-side cart, persisted to device storage.
///
/// The cart is tied to a single outlet. Persistence uses `shared_preferences`
/// (already a dependency for the auth token and theme) rather than adding hive:
/// a cart is one small JSON blob read once at startup, so a full embedded
/// database would buy nothing here.
///
/// Every mutation writes through to disk, so the cart survives backgrounding,
/// a force-close, and process death — not just navigation.
class CartState extends ChangeNotifier {
  static const _storageKey = 'carevo_cart_v1';

  final List<CartItem> _items = [];
  List<CartItem> get items => List.unmodifiable(_items);

  Outlet? _outlet;
  Outlet? get outlet => _outlet;
  String? get outletId => _outlet?.id;

  int _lineCounter = 0;

  /// False until [restore] finishes, so UI can avoid flashing an empty cart
  /// over one that is about to load.
  bool _restored = false;
  bool get restored => _restored;

  int get totalQuantity => _items.fold(0, (sum, i) => sum + i.quantity);
  double get subtotal => _items.fold(0.0, (sum, i) => sum + i.lineTotal);
  bool get isEmpty => _items.isEmpty;

  // ----------------------------- persistence -------------------------------

  /// Load any persisted cart. Called once at startup, before the first frame.
  Future<void> restore() async {
    try {
      final prefs = await SharedPreferences.getInstance();
      final raw = prefs.getString(_storageKey);
      if (raw != null && raw.isNotEmpty) {
        final map = jsonDecode(raw) as Map<String, dynamic>;
        final outletJson = (map['outlet'] as Map?)?.cast<String, dynamic>();
        if (outletJson != null) _outlet = Outlet.fromJson(outletJson);
        _items
          ..clear()
          ..addAll(((map['items'] as List?) ?? const [])
              .whereType<Map>()
              .map((i) => CartItem.fromJson(i.cast<String, dynamic>())));
        _lineCounter = int.tryParse(map['line_counter']?.toString() ?? '') ?? _items.length;
      }
    } catch (_) {
      // A corrupt or schema-changed blob must never brick startup: drop it and
      // begin with an empty cart.
      _items.clear();
      _outlet = null;
      _lineCounter = 0;
    }
    _restored = true;
    notifyListeners();
  }

  /// Fire-and-forget write. Not awaited by callers — a slow disk must never
  /// make tapping "add" feel laggy — but each mutation triggers one.
  Future<void> _persist() async {
    try {
      final prefs = await SharedPreferences.getInstance();
      if (_items.isEmpty && _outlet == null) {
        await prefs.remove(_storageKey);
        return;
      }
      await prefs.setString(
        _storageKey,
        jsonEncode({
          'outlet': _outlet?.toJson(),
          'items': _items.map((i) => i.toJson()).toList(),
          'line_counter': _lineCounter,
        }),
      );
    } catch (_) {
      // Persistence is best-effort; the in-memory cart stays authoritative for
      // this session even if the write fails.
    }
  }

  // ------------------------------- outlet ----------------------------------

  /// True when [outlet] differs from the cart's outlet AND the cart has items,
  /// i.e. binding to it would discard the customer's basket.
  ///
  /// Callers use this to prompt BEFORE calling [setOutlet]; merely browsing a
  /// different restaurant must not silently empty the cart.
  bool wouldDiscardCart(Outlet outlet) =>
      _items.isNotEmpty && _outlet != null && _outlet!.id != outlet.id;

  /// Bind the cart to [outlet]. Clears the basket only when switching to a
  /// DIFFERENT outlet — check [wouldDiscardCart] first and confirm with the
  /// customer, because this is not reversible.
  void setOutlet(Outlet outlet) {
    if (_outlet?.id != outlet.id) {
      _items.clear();
      _lineCounter = 0;
    }
    _outlet = outlet;
    _persist();
    notifyListeners();
  }

  /// Bind to [outlet] without touching the basket. Safe when the cart is empty
  /// or already belongs to this outlet; used when only browsing.
  void bindOutletIfSafe(Outlet outlet) {
    if (wouldDiscardCart(outlet)) return;
    setOutlet(outlet);
  }

  /// Drop lines whose menu item is no longer available, returning the removed
  /// names. Used by the pre-checkout availability gate (see checkout_screen).
  List<String> removeUnavailable(Set<String> unavailableItemIds) {
    final removed = <String>[];
    _items.removeWhere((line) {
      if (unavailableItemIds.contains(line.item.id)) {
        removed.add(line.item.name);
        return true;
      }
      return false;
    });
    if (removed.isNotEmpty) {
      _persist();
      notifyListeners();
    }
    return removed;
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
    _persist();
    notifyListeners();
  }

  void increment(String lineId) {
    final line = _find(lineId);
    if (line != null) {
      line.quantity++;
      _persist();
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
    _persist();
    notifyListeners();
  }

  void removeLine(String lineId) {
    _items.removeWhere((i) => i.lineId == lineId);
    _persist();
    notifyListeners();
  }

  void clear() {
    _items.clear();
    _lineCounter = 0;
    _persist();
    notifyListeners();
  }

  CartItem? _find(String lineId) {
    for (final i in _items) {
      if (i.lineId == lineId) return i;
    }
    return null;
  }

  /// Build the `POST /customer/orders` payload.
  ///
  /// PE Step 3 (FR-C1/C2): the checkout may attach a travel [transportMode]
  /// and the customer's [originLat]/[originLng] starting point so the
  /// prediction engine can estimate travel. All are optional — a customer who
  /// denies location still checks out, just with `origin_source: 'none'`.
  Map<String, dynamic> toOrderPayload({
    String? customerNotes,
    String? transportMode,
    double? originLat,
    double? originLng,
    String? originSource,
    String? couponCode,
  }) =>
      {
        'outlet_id': _outlet?.id,
        'items': _items.map((i) => i.toOrderItemJson()).toList(),
        if (customerNotes != null && customerNotes.trim().isNotEmpty)
          'customer_notes': customerNotes.trim(),
        // Omitted when blank: the server validates a minimum length, so an
        // empty string would be rejected rather than treated as "no coupon".
        if (couponCode != null && couponCode.trim().isNotEmpty)
          'coupon_code': couponCode.trim().toUpperCase(),
        'transport_mode': ?transportMode,
        'origin_lat': ?originLat,
        'origin_lng': ?originLng,
        'origin_source': ?originSource,
      };
}
