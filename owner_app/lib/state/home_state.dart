import 'package:flutter/foundation.dart' hide Category;

import '../models/category.dart';
import '../models/menu_item.dart';
import '../models/outlet.dart';
import '../services/menu_service.dart';
import '../services/outlet_service.dart';

/// Backs the Home screen: outlet visibility + the flat dish availability list.
/// Toggles are optimistic and revert on failure.
class HomeState extends ChangeNotifier {
  final OutletService _outletService;
  final MenuService _menuService;

  HomeState(this._outletService, this._menuService);

  bool _loading = false;
  String? _error;
  Outlet? _outlet;
  List<MenuItem> _items = [];

  bool get loading => _loading;
  String? get error => _error;
  Outlet? get outlet => _outlet;
  List<MenuItem> get items => List.unmodifiable(_items);

  Future<void> load() async {
    _loading = true;
    _error = null;
    notifyListeners();
    try {
      final results = await Future.wait([
        _outletService.getOutlet(),
        _menuService.getMenuItems(),
      ]);
      _outlet = results[0] as Outlet;
      _items = results[1] as List<MenuItem>;
    } catch (e, st) {
      // Surface the real cause in debug builds — a swallowed cast/parse error
      // here previously masked a data-fetch bug behind a generic message.
      if (kDebugMode) {
        debugPrint('HomeState.load failed: $e\n$st');
      }
      _error = 'Could not load outlet and menu. Pull to retry.';
    } finally {
      _loading = false;
      notifyListeners();
    }
  }

  /// Persist a new storefront photo URL (or null to clear).
  ///
  /// Not optimistic, unlike [toggleVisibility]: the Cloudinary upload has
  /// already completed by the time this runs, so there is no latency left worth
  /// hiding, and showing an image that failed to save would be misleading.
  Future<bool> setOutletImage(String? imageUrl) async {
    final current = _outlet;
    if (current == null) return false;
    try {
      _outlet = await _outletService.setImage(imageUrl);
      notifyListeners();
      return true;
    } catch (_) {
      return false;
    }
  }

  /// Set the daily opening/closing schedule (migration 024). Not optimistic —
  /// the server recomputes order_status from the new times, so the returned
  /// outlet is the source of truth. Returns null on success, or an error.
  Future<String?> setHours(String? openingTime, String? closingTime) async {
    if (_outlet == null) return 'No outlet loaded.';
    try {
      _outlet = await _outletService.setHours(openingTime, closingTime);
      notifyListeners();
      return null;
    } catch (_) {
      return 'Could not save the hours. Try again.';
    }
  }

  /// Flip the "temporarily closed" toggle (migration 024). Optimistic on the
  /// flag itself, then reconciled with the server's returned outlet (which also
  /// carries the recomputed order_status).
  Future<bool> setManuallyClosed(bool next) async {
    final current = _outlet;
    if (current == null) return false;
    _outlet = current.copyWith(isManuallyClosed: next);
    notifyListeners();
    try {
      _outlet = await _outletService.setManualClosed(next);
      notifyListeners();
      return true;
    } catch (_) {
      _outlet = current; // revert
      notifyListeners();
      return false;
    }
  }

  /// Optimistically flips outlet visibility; reverts if the call fails.
  Future<bool> toggleVisibility(bool next) async {
    final current = _outlet;
    if (current == null) return false;

    _outlet = current.copyWith(isVisible: next);
    notifyListeners();

    try {
      final confirmed = await _outletService.setVisibility(current.id, next);
      _outlet = current.copyWith(isVisible: confirmed);
      notifyListeners();
      return true;
    } catch (_) {
      _outlet = current; // revert
      _error = 'Could not update outlet visibility.';
      notifyListeners();
      return false;
    }
  }

  /// Optimistically flips a dish's availability; reverts if the call fails.
  Future<bool> toggleItemAvailability(String itemId, bool next) async {
    final index = _items.indexWhere((i) => i.id == itemId);
    if (index < 0) return false;
    final original = _items[index];

    _items[index] = original.copyWith(isAvailable: next);
    notifyListeners();

    try {
      final confirmed = await _menuService.setAvailability(itemId, next);
      _items[index] = original.copyWith(isAvailable: confirmed);
      notifyListeners();
      return true;
    } catch (_) {
      _items[index] = original; // revert
      _error = 'Could not update "${original.name}".';
      notifyListeners();
      return false;
    }
  }

  // --------------------------- Menu CRUD ---------------------------------
  List<Category> _categories = [];
  List<Category> get categories => List.unmodifiable(_categories);

  /// Loads categories for the dish form's picker. Always refetches: HomeState is
  /// a singleton that survives logout, so a cached list could belong to a
  /// previously-signed-in outlet — which would show wrong categories and make
  /// dish-add fail (the category wouldn't belong to the current outlet).
  Future<List<Category>> ensureCategories() async {
    _categories = await _menuService.getCategories();
    return _categories;
  }

  /// Creates a dish, then refreshes the list. Returns null on success, or a
  /// staff-facing error message on failure.
  Future<String?> createDish({
    required String name,
    required double basePrice,
    required String categoryId,
    required bool isVeg,
    int? prepTimeMinutes,
    String? imageUrl,
  }) async {
    try {
      await _menuService.createItem(
        name: name,
        basePrice: basePrice,
        categoryId: categoryId,
        isVeg: isVeg,
        prepTimeMinutes: prepTimeMinutes,
        imageUrl: imageUrl,
      );
      await load();
      return null;
    } catch (e) {
      if (kDebugMode) debugPrint('createDish failed: $e');
      return 'Could not add dish.';
    }
  }

  /// Updates a dish, then refreshes the list.
  Future<String?> updateDish(
    String itemId, {
    String? name,
    double? basePrice,
    String? categoryId,
    bool? isVeg,
    int? prepTimeMinutes,
    String? imageUrl,
  }) async {
    try {
      await _menuService.updateItem(
        itemId,
        name: name,
        basePrice: basePrice,
        categoryId: categoryId,
        isVeg: isVeg,
        prepTimeMinutes: prepTimeMinutes,
        imageUrl: imageUrl,
      );
      await load();
      return null;
    } catch (e) {
      if (kDebugMode) debugPrint('updateDish failed: $e');
      return 'Could not save changes.';
    }
  }

  /// Deletes (deactivates) a dish, then refreshes the list.
  Future<String?> deleteDish(String itemId) async {
    try {
      await _menuService.deleteItem(itemId);
      await load();
      return null;
    } catch (e) {
      if (kDebugMode) debugPrint('deleteDish failed: $e');
      return 'Could not delete dish.';
    }
  }

  void clearError() {
    _error = null;
  }
}
