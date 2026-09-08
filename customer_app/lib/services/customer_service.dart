import '../models/customer.dart';
import 'api_client.dart';

/// One past order, as shown in the in-app history list.
class OrderHistoryEntry {
  const OrderHistoryEntry({
    required this.orderId,
    required this.status,
    this.outletName,
    this.paymentStatus,
    this.totalAmount = 0,
    this.discountAmount = 0,
    this.createdAt,
    this.pickupCode,
    this.items = const [],
  });

  final String orderId;
  final String status;
  final String? outletName;
  final String? paymentStatus;
  final double totalAmount;
  final double discountAmount;
  final DateTime? createdAt;

  /// Null until payment lands. Carried in the list so an in-progress order can
  /// be reopened from history — before this the code lived only on the
  /// transient post-checkout screen and was lost the moment you left it.
  final String? pickupCode;
  final List<OrderHistoryLine> items;

  bool get isPaid => (paymentStatus ?? '').toUpperCase() == 'PAID';

  /// Still going: the customer has paid and has not collected yet. These are
  /// the orders that need to stay reachable.
  static const activeStatuses = {'PAID', 'RECEIVED', 'PREPARING', 'READY'};

  bool get isActive => activeStatuses.contains(status.toUpperCase());

  /// One-line summary of the basket, e.g. "2x Masala Dosa, 1x Filter Coffee".
  String get itemSummary => items.isEmpty
      ? '—'
      : items.map((i) => '${i.quantity}x ${i.name ?? 'Item'}').join(', ');

  factory OrderHistoryEntry.fromJson(Map<String, dynamic> json) {
    double num(Object? v) => double.tryParse(v?.toString() ?? '') ?? 0;
    return OrderHistoryEntry(
      orderId: json['order_id']?.toString() ?? '',
      status: json['status']?.toString() ?? '',
      outletName: json['outlet_name']?.toString(),
      paymentStatus: json['payment_status']?.toString(),
      totalAmount: num(json['total_amount']),
      discountAmount: num(json['discount_amount']),
      createdAt: DateTime.tryParse(json['created_at']?.toString() ?? ''),
      pickupCode: json['pickup_code']?.toString(),
      items: ((json['items'] as List?) ?? const [])
          .whereType<Map<String, dynamic>>()
          .map(OrderHistoryLine.fromJson)
          .toList(),
    );
  }
}

class OrderHistoryLine {
  const OrderHistoryLine({this.name, this.quantity = 1});
  final String? name;
  final int quantity;

  factory OrderHistoryLine.fromJson(Map<String, dynamic> json) =>
      OrderHistoryLine(
        name: json['name']?.toString(),
        quantity: int.tryParse(json['quantity']?.toString() ?? '') ?? 1,
      );
}

/// Points balance plus the ledger behind it.
class PointsSummary {
  const PointsSummary({
    this.balance = 0,
    this.threshold = 50,
    this.valueRupees = 100,
    this.canRedeem = false,
    this.transactions = const [],
  });

  final double balance;

  /// Redemption rule comes from the server so the app never hardcodes it — if
  /// the rate changes, the app follows without a release.
  final double threshold;
  final double valueRupees;
  final bool canRedeem;
  final List<PointsEntry> transactions;

  /// 0..1 progress toward the next redemption, for the profile progress bar.
  double get progress =>
      threshold <= 0 ? 0 : (balance / threshold).clamp(0, 1).toDouble();

  factory PointsSummary.fromJson(Map<String, dynamic> json) {
    double num(Object? v) => double.tryParse(v?.toString() ?? '') ?? 0;
    return PointsSummary(
      balance: num(json['points_balance']),
      threshold: num(json['redemption_threshold']),
      valueRupees: num(json['redemption_value_rupees']),
      canRedeem: json['can_redeem'] == true,
      transactions: ((json['transactions'] as List?) ?? const [])
          .whereType<Map<String, dynamic>>()
          .map(PointsEntry.fromJson)
          .toList(),
    );
  }
}

class PointsEntry {
  const PointsEntry({required this.delta, required this.reason, this.createdAt});
  final double delta;
  final String reason;
  final DateTime? createdAt;

  /// Human label for the ledger row; the server sends machine reasons.
  String get label => switch (reason) {
        'ORDER_ACCRUAL' => 'Earned on an order',
        'COUPON_REDEMPTION' => 'Redeemed for a coupon',
        _ => reason,
      };

  factory PointsEntry.fromJson(Map<String, dynamic> json) => PointsEntry(
        delta: double.tryParse(json['points_delta']?.toString() ?? '') ?? 0,
        reason: json['reason']?.toString() ?? '',
        createdAt: DateTime.tryParse(json['created_at']?.toString() ?? ''),
      );
}

class CouponEntry {
  const CouponEntry({
    required this.code,
    required this.kind,
    this.discountAmount = 0,
    this.trialDays = 0,
  });

  final String code;
  final String kind;
  final double discountAmount;
  final int trialDays;

  bool get isDiscount => kind == 'POINTS_DISCOUNT';

  factory CouponEntry.fromJson(Map<String, dynamic> json) => CouponEntry(
        code: json['code']?.toString() ?? '',
        kind: json['kind']?.toString() ?? '',
        discountAmount:
            double.tryParse(json['discount_amount']?.toString() ?? '') ?? 0,
        trialDays: int.tryParse(json['trial_days']?.toString() ?? '') ?? 0,
      );
}

/// Result of redeeming a premium-trial code. No payment is involved anywhere
/// in this flow — the trial is granted outright.
class TrialRedemption {
  const TrialRedemption({required this.message, this.premiumUntil, this.plan = 'Free'});
  final String message;
  final DateTime? premiumUntil;
  final String plan;

  factory TrialRedemption.fromJson(Map<String, dynamic> json) =>
      TrialRedemption(
        message: json['message']?.toString() ?? 'Trial activated.',
        premiumUntil:
            DateTime.tryParse(json['premium_until']?.toString() ?? ''),
        plan: json['plan']?.toString() ?? 'Free',
      );
}

/// Everything under `/customer/*` that concerns the signed-in customer
/// themselves: profile, order history, points and coupons.
///
/// No method takes a customer id — the server resolves the customer from the
/// bearer token, so the app cannot ask for anyone else's data even by mistake.
/// Outcome of an account deletion. `ordersRetained` is deliberately surfaced:
/// past orders survive as the restaurants' tax records, detached from any
/// person, and telling the customer that plainly is better than implying a
/// total erasure that did not happen.
class DeleteAccountResult {
  const DeleteAccountResult({required this.ordersRetained, required this.message});
  final int ordersRetained;
  final String message;
}

class CustomerService {
  CustomerService(this._api);
  final ApiClient _api;

  Future<Customer> me() async {
    final json = await _api.get('/customer/me');
    return Customer.fromJson(json as Map<String, dynamic>);
  }

  /// `DELETE /customer/me` — irreversibly erase this account's personal data.
  ///
  /// Play Store policy requires an in-app deletion route for apps with
  /// accounts. Returns the server's summary so the confirmation can be
  /// specific about what was kept and why.
  Future<DeleteAccountResult> deleteAccount() async {
    final res = await _api.delete('/customer/me');
    final m = ((res as Map?) ?? const {}).cast<String, dynamic>();
    return DeleteAccountResult(
      ordersRetained: (m['orders_retained'] as num?)?.toInt() ?? 0,
      message: m['message']?.toString() ??
          'Your account and personal details have been deleted.',
    );
  }

  Future<Customer> updateName(String name) async {
    final json = await _api.patch('/customer/me', body: {'name': name});
    return Customer.fromJson(json as Map<String, dynamic>);
  }

  Future<List<OrderHistoryEntry>> orders({int limit = 50}) async {
    final json = await _api.get('/customer/orders', query: {'limit': limit});
    return ((json as List?) ?? const [])
        .whereType<Map<String, dynamic>>()
        .map(OrderHistoryEntry.fromJson)
        .toList();
  }

  Future<PointsSummary> points() async {
    final json = await _api.get('/customer/points');
    return PointsSummary.fromJson(json as Map<String, dynamic>);
  }

  /// Spends points for a discount coupon. Throws [ApiException] with the
  /// server's message (409) when the balance is short.
  Future<CouponEntry> redeemPoints() async {
    final json = await _api.post('/customer/points/redeem');
    final map = json as Map<String, dynamic>;
    return CouponEntry.fromJson(map['coupon'] as Map<String, dynamic>);
  }

  Future<List<CouponEntry>> coupons() async {
    final json = await _api.get('/customer/coupons');
    return ((json as List?) ?? const [])
        .whereType<Map<String, dynamic>>()
        .map(CouponEntry.fromJson)
        .toList();
  }

  /// Redeems a PREMIUM_TRIAL code. Discount coupons are not redeemed here —
  /// those are applied by passing the code at checkout.
  Future<TrialRedemption> redeemTrialCode(String code) async {
    final json = await _api.post(
      '/customer/coupons/redeem',
      body: {'code': code.trim().toUpperCase()},
    );
    return TrialRedemption.fromJson(json as Map<String, dynamic>);
  }
}
