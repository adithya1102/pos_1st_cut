import 'package:url_launcher/url_launcher.dart';

/// Builds a `upi://pay` intent link and opens the user's UPI app.
///
/// The payee (`pa`) is the OUTLET's stored VPA; amount (`am`) is locked; the
/// order id rides along as the transaction reference (`tr`). The payer's own
/// UPI ID is chosen inside their UPI app and never touches our backend.
class UpiIntent {
  static Uri buildUri({
    required String payeeVpa,
    required String payeeName,
    required double amount,
    required String orderId,
  }) {
    return Uri(
      scheme: 'upi',
      host: 'pay',
      queryParameters: {
        'pa': payeeVpa,
        'pn': payeeName,
        'am': amount.toStringAsFixed(2),
        'cu': 'INR',
        'tr': orderId,
        'tn': 'Order $orderId',
      },
    );
  }

  /// Returns true if a UPI app was opened. False if none could handle it
  /// (e.g. no UPI app installed) — the caller should fall back to showing
  /// the VPA/amount for a manual transfer.
  ///
  /// IMPORTANT: we do NOT gate on canLaunchUrl(). For the `upi://` scheme it
  /// returns false-NEGATIVES on many devices even when GPay/Paytm/PhonePe are
  /// installed (a known url_launcher limitation). Instead we attempt the launch
  /// directly with externalApplication mode and treat only a real throw
  /// (no activity can handle it) as "no UPI app".
  static Future<bool> launch({
    required String payeeVpa,
    required String payeeName,
    required double amount,
    required String orderId,
  }) async {
    final uri = buildUri(
      payeeVpa: payeeVpa,
      payeeName: payeeName,
      amount: amount,
      orderId: orderId,
    );
    try {
      return await launchUrl(uri, mode: LaunchMode.externalApplication);
    } catch (_) {
      return false;
    }
  }
}
