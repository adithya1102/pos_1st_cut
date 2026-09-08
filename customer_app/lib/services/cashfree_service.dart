import 'dart:async';

import 'package:flutter/foundation.dart';
import 'package:flutter_cashfree_pg_sdk/api/cferrorresponse/cferrorresponse.dart';
import 'package:flutter_cashfree_pg_sdk/api/cfpayment/cfwebcheckoutpayment.dart';
import 'package:flutter_cashfree_pg_sdk/api/cfpaymentgateway/cfpaymentgatewayservice.dart';
import 'package:flutter_cashfree_pg_sdk/api/cfsession/cfsession.dart';
import 'package:flutter_cashfree_pg_sdk/utils/cfenums.dart';
import 'package:flutter_cashfree_pg_sdk/utils/cfexceptions.dart';

import '../config/app_config.dart';

/// How Cashfree's checkout sheet finished, from the SDK's point of view.
///
/// READ THE DOC ON [CashfreeService.openCheckout] BEFORE TRUSTING THIS.
/// `verified` does NOT mean paid — it means the sheet closed claiming success.
/// The webhook is the authority.
enum CheckoutOutcome {
  /// SDK reported success. Still requires server confirmation.
  verified,

  /// SDK reported an error, or the customer dismissed the sheet.
  failed,

  /// Could not even open — misconfiguration or an unsupported platform.
  notStarted,
}

class CheckoutResult {
  const CheckoutResult(this.outcome, {this.message});
  final CheckoutOutcome outcome;
  final String? message;

  bool get verified => outcome == CheckoutOutcome.verified;
}

/// Thin wrapper over Cashfree's Drop-in checkout.
///
/// ## Why this returns a "maybe" and not a payment
///
/// The SDK's onVerify callback fires on the DEVICE. It is UX feedback, not
/// settlement: it can fire on a payment the bank later reverses, and it can
/// fail to fire on a payment that genuinely succeeded (app killed, network
/// dropped as the sheet closed, customer switching back from their UPI app).
///
/// The webhook is the only thing that flips an order to PAID server-side, and
/// it does so whether or not this callback ever runs. So callers must treat
/// [CheckoutResult] purely as "stop showing the sheet, start polling", and let
/// the ORDER STATUS decide what the customer is told.
class CashfreeService {
  CashfreeService() {
    // The SDK dispatches to one global callback pair, not per-payment. Set
    // once here and route through a Completer, so two checkouts can never
    // cross-talk and a stale callback cannot resolve a newer attempt.
    CFPaymentGatewayService().setCallback(_onVerify, _onError);
  }

  Completer<CheckoutResult>? _pending;

  CFEnvironment get _environment => AppConfig.cashfreeIsProduction
      ? CFEnvironment.PRODUCTION
      : CFEnvironment.SANDBOX;

  void _onVerify(String orderId) {
    if (kDebugMode) debugPrint('Cashfree onVerify: $orderId');
    _complete(const CheckoutResult(CheckoutOutcome.verified));
  }

  void _onError(CFErrorResponse error, String orderId) {
    if (kDebugMode) debugPrint('Cashfree onError: ${error.getMessage()} ($orderId)');
    _complete(CheckoutResult(
      CheckoutOutcome.failed,
      message: error.getMessage(),
    ));
  }

  void _complete(CheckoutResult r) {
    final p = _pending;
    _pending = null;
    if (p != null && !p.isCompleted) p.complete(r);
  }

  /// Opens the hosted checkout for [paymentSessionId] and resolves when the
  /// sheet closes.
  ///
  /// [orderId] must be OUR customer_orders.id — the same value the backend
  /// sent to Cashfree as `order_id`, which is what Cashfree echoes back on the
  /// webhook. Passing the cf_order_id here would break that correlation.
  Future<CheckoutResult> openCheckout({
    required String orderId,
    required String paymentSessionId,
  }) async {
    if (paymentSessionId.isEmpty) {
      return const CheckoutResult(
        CheckoutOutcome.notStarted,
        message: 'No payment session was issued for this order.',
      );
    }
    // A previous sheet is still open; refuse rather than orphan its completer.
    if (_pending != null && !_pending!.isCompleted) {
      return const CheckoutResult(
        CheckoutOutcome.notStarted,
        message: 'A payment is already in progress.',
      );
    }

    final completer = Completer<CheckoutResult>();
    _pending = completer;

    try {
      final session = CFSessionBuilder()
          .setEnvironment(_environment)
          .setOrderId(orderId)
          .setPaymentSessionId(paymentSessionId)
          .build();

      // Web checkout, NOT the Drop-in builder: the SDK marks
      // CFDropCheckoutPaymentBuilder deprecated — "this integration is no
      // longer supported" — and points here instead.
      //
      // Cashfree renders UPI, cards and netbanking in this one sheet, which is
      // why the app no longer asks the customer to pick a method: that choice
      // moved to Cashfree, along with the compliance burden of ever touching
      // card details.
      final payment = CFWebCheckoutPaymentBuilder().setSession(session).build();

      CFPaymentGatewayService().doPayment(payment);
    } on CFException catch (e) {
      _pending = null;
      return CheckoutResult(CheckoutOutcome.notStarted, message: e.message);
    } catch (e) {
      _pending = null;
      return CheckoutResult(CheckoutOutcome.notStarted, message: e.toString());
    }

    return completer.future;
  }
}
