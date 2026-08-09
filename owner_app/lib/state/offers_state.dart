import 'package:flutter/foundation.dart';

import '../models/offer.dart';
import '../services/api_client.dart';
import '../services/offer_service.dart';

/// Backs the Offers tab. Same shape as [HomeState]: load, optimistic toggle
/// that reverts, and create/update that refetch rather than patch locally.
class OffersState extends ChangeNotifier {
  final OfferService _service;

  OffersState(this._service);

  bool _loading = false;
  String? _error;
  List<Offer> _offers = [];

  bool get loading => _loading;
  String? get error => _error;
  List<Offer> get offers => List.unmodifiable(_offers);

  Future<void> load() async {
    _loading = true;
    _error = null;
    notifyListeners();
    try {
      _offers = await _service.list();
    } catch (e, st) {
      if (kDebugMode) debugPrint('OffersState.load failed: $e\n$st');
      _error = 'Could not load your offers. Pull to retry.';
    } finally {
      _loading = false;
      notifyListeners();
    }
  }

  /// Optimistically flips the live switch; reverts if the call fails.
  Future<bool> toggleActive(String offerId, bool next) async {
    final index = _offers.indexWhere((o) => o.id == offerId);
    if (index < 0) return false;
    final original = _offers[index];

    _offers[index] = original.copyWith(isActive: next);
    notifyListeners();

    try {
      final saved = await _service.setActive(offerId, next);
      _offers[index] = saved;
      notifyListeners();
      return true;
    } catch (_) {
      _offers[index] = original;
      notifyListeners();
      return false;
    }
  }

  /// Returns null on success, or an owner-facing message on failure.
  ///
  /// The server's own message is preferred when it sends one: a rejected
  /// percentage-without-a-cap explains exactly what to fix, and replacing that
  /// with "Could not save" would throw the useful part away.
  Future<String?> create({
    required String discountType,
    required double discountValue,
    double? maxDiscountAmount,
    double? minOrderValue,
    String? code,
    int? maxRedemptionsTotal,
    int maxRedemptionsPerCustomer = 1,
    bool isActive = false,
  }) async {
    try {
      await _service.create(
        discountType: discountType,
        discountValue: discountValue,
        maxDiscountAmount: maxDiscountAmount,
        minOrderValue: minOrderValue,
        code: code,
        maxRedemptionsTotal: maxRedemptionsTotal,
        maxRedemptionsPerCustomer: maxRedemptionsPerCustomer,
        isActive: isActive,
      );
      await load();
      return null;
    } on ApiException catch (e) {
      return e.message;
    } catch (e) {
      if (kDebugMode) debugPrint('createOffer failed: $e');
      return 'Could not create the offer.';
    }
  }

  Future<String?> update(
    String offerId, {
    String? discountType,
    double? discountValue,
    double? maxDiscountAmount,
    double? minOrderValue,
    String? code,
    int? maxRedemptionsTotal,
    int? maxRedemptionsPerCustomer,
    bool? isActive,
  }) async {
    try {
      await _service.update(
        offerId,
        discountType: discountType,
        discountValue: discountValue,
        maxDiscountAmount: maxDiscountAmount,
        minOrderValue: minOrderValue,
        code: code,
        maxRedemptionsTotal: maxRedemptionsTotal,
        maxRedemptionsPerCustomer: maxRedemptionsPerCustomer,
        isActive: isActive,
      );
      await load();
      return null;
    } on ApiException catch (e) {
      return e.message;
    } catch (e) {
      if (kDebugMode) debugPrint('updateOffer failed: $e');
      return 'Could not save the offer.';
    }
  }
}
