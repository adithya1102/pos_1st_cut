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
    if (!await canLaunchUrl(uri)) return false;
    return launchUrl(uri, mode: LaunchMode.externalApplication);
  }
}
