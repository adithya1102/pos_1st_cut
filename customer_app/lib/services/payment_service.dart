import 'api_client.dart';

/// Payment methods offered at checkout (NO pay-at-counter, NO delivery).
enum PaymentMethod { upi, card, netbanking }

extension PaymentMethodX on PaymentMethod {
  /// Wire value expected by `POST /customer/payment/simulate`.
  String get wire => switch (this) {
        PaymentMethod.upi => 'upi',
        PaymentMethod.card => 'card',
        PaymentMethod.netbanking => 'netbanking',
      };

  String get label => switch (this) {
        PaymentMethod.upi => 'UPI',
        PaymentMethod.card => 'Card',
        PaymentMethod.netbanking => 'Net Banking',
      };

  String get subtitle => switch (this) {
        PaymentMethod.upi => 'GPay, PhonePe, Paytm & more',
        PaymentMethod.card => 'Credit or debit card',
        PaymentMethod.netbanking => 'All major banks',
      };
}

class PaymentResult {
  const PaymentResult({required this.success, required this.status, this.message});
  final bool success;
  final String status;
  final String? message;
}

/// Abstraction so a real Razorpay checkout can replace the stub later
/// without changing the checkout UI.
abstract class PaymentService {
  Future<PaymentResult> pay({
    required String orderId,
    required PaymentMethod method,
  });
}

/// This-run implementation: there are no real gateway keys, so we call
/// the backend simulate endpoint to advance the order to PAID.
class StubPaymentService implements PaymentService {
  StubPaymentService(this._api);
  final ApiClient _api;

  @override
  Future<PaymentResult> pay({
    required String orderId,
    required PaymentMethod method,
  }) async {
    final res = await _api.post(
      '/customer/payment/simulate',
      body: {'order_id': orderId, 'method': method.wire},
    );
    final map = (res is Map) ? res.cast<String, dynamic>() : <String, dynamic>{};
    final status = (map['payment_status'] ?? map['status'] ?? 'PAID').toString();
    final ok = status.toUpperCase() == 'PAID' ||
        (map['success'] == true) ||
        status.toUpperCase() == 'SUCCESS';
    return PaymentResult(success: ok, status: status);
  }
}
