import 'package:flutter/services.dart' show PlatformException;
import 'package:url_launcher/url_launcher.dart';

import 'cashfree_service.dart' show CheckoutOutcome, CheckoutResult;

/// Opens YOUPI PG's hosted checkout.
///
/// Deliberately thinner than [CashfreeService]: there is no SDK and no result
/// callback. YOUPI settles peer-to-peer into the merchant's own VPA and learns
/// the payment happened only when an observer on the merchant's phone forwards
/// the bank credit alert — which can arrive seconds after the customer is back
/// in this app, or before they ever return to it.
///
/// So this NEVER reports [CheckoutOutcome.verified]. The best it can say is
/// "the page opened"; whether money moved is decided by the signed webhook and
/// read back by polling the order. Reporting anything stronger would invite a
/// caller to treat a launched browser as a payment.
///
/// Why the hosted page rather than a `upi://pay` intent built here: that page
/// performs the select-method and payment-done transitions the gateway requires
/// before an observed credit can be attributed to the session. A raw intent
/// skips them, and the payment never verifies.
class YoupiService {
  Future<CheckoutResult> openCheckout({
    required String orderId,
    required String checkoutUrl,
  }) async {
    final uri = Uri.tryParse(checkoutUrl);
    if (uri == null || !uri.hasScheme) {
      return const CheckoutResult(
        CheckoutOutcome.notStarted,
        message: 'Payment page address was invalid.',
      );
    }

    try {
      // externalApplication, not an in-app webview: the page hands off to the
      // customer's UPI app, and an embedded webview cannot follow that intent
      // back and forth reliably.
      final launched = await launchUrl(uri, mode: LaunchMode.externalApplication);
      if (!launched) {
        return const CheckoutResult(
          CheckoutOutcome.notStarted,
          message: 'Could not open the payment page.',
        );
      }
    } on PlatformException catch (e) {
      return CheckoutResult(CheckoutOutcome.notStarted, message: e.message);
    } catch (e) {
      return CheckoutResult(CheckoutOutcome.notStarted, message: e.toString());
    }

    // Opened, outcome unknown — the caller must confirm against the server.
    // `failed` is the existing "we cannot vouch for this" value, which routes
    // PickupScreen into its confirming-and-polling state. That is the correct
    // destination here: it is not a claim the payment failed.
    return const CheckoutResult(
      CheckoutOutcome.failed,
      message: 'Confirming your payment…',
    );
  }
}
