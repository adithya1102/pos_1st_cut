import 'package:flutter/material.dart';
import 'package:flutter/services.dart';
import 'package:provider/provider.dart';
import 'package:url_launcher/url_launcher.dart';

import '../models/order.dart';
import '../services/api_client.dart';
import '../services/order_service.dart';
import '../state/cart_state.dart';
import '../theme/app_colors.dart';
import '../theme/widgets/neo_button.dart';
import '../theme/widgets/neo_card.dart';
import '../widgets/account_button.dart';
import '../widgets/price_text.dart';
import 'pickup_screen.dart';

/// Pay the restaurant directly, UPI to UPI (backend migration 035).
///
/// WHAT THIS SCREEN IS CAREFUL ABOUT
/// ---------------------------------
/// CareVo is not in the payment path. The money goes from the customer's UPI
/// app straight to the restaurant's VPA, which means:
///
///   * nothing here can verify a payment. "I've paid" records a CLAIM, and the
///     copy says so — the restaurant confirms by looking at its own UPI app.
///     Telling the customer they have paid would be asserting something this
///     app cannot know.
///   * the exact amount matters. The restaurant matches the payment by amount
///     and order number, so both are shown prominently and the amount is
///     copied into the intent to two decimals.
///   * there is a deadline. The server cancels an unclaimed order after its
///     pay window, so the screen says the order will be cancelled rather than
///     letting it vanish unexplained.
///
/// WHY THE CLAIM IS A SEPARATE TAP FROM OPENING THE UPI APP
/// --------------------------------------------------------
/// Opening the chooser proves nothing — the customer may close it, pick the
/// wrong account, or fail the transaction. So the claim is its own deliberate
/// action, available whether or not the intent was ever launched (some people
/// will pay from a different phone, or scan the ID into another app). What the
/// app must never do is claim on the customer's behalf.
class UpiPayScreen extends StatefulWidget {
  const UpiPayScreen({
    super.key,
    required this.order,
    this.outletName,
    this.onClaimed,
  });

  final CreatedOrder order;
  final String? outletName;

  /// Test seam: lets a widget test observe the claim without a navigator.
  final VoidCallback? onClaimed;

  @override
  State<UpiPayScreen> createState() => _UpiPayScreenState();
}

class _UpiPayScreenState extends State<UpiPayScreen> {
  bool _claiming = false;
  String? _error;
  bool _opened = false;

  UpiPaymentInfo? get _upi => widget.order.upiPayment;

  Future<void> _copyVpa() async {
    final vpa = _upi?.vpa;
    if (vpa == null) return;
    await Clipboard.setData(ClipboardData(text: vpa));
    if (!mounted) return;
    ScaffoldMessenger.of(context)
      ..hideCurrentSnackBar()
      ..showSnackBar(const SnackBar(content: Text('UPI ID copied')));
  }

  /// Hands off to whatever UPI apps are installed.
  ///
  /// `externalApplication` so the chooser opens outside this app rather than in
  /// a webview, which cannot complete a payment. A device with no UPI app
  /// installed returns false from launchUrl — said plainly, because the
  /// customer can still pay by copying the ID into their banking app.
  Future<void> _openUpiApp() async {
    final upi = _upi;
    if (upi == null) return;
    setState(() => _error = null);
    try {
      final ok = await launchUrl(upi.intentUri,
          mode: LaunchMode.externalApplication);
      if (!mounted) return;
      if (ok) {
        setState(() => _opened = true);
      } else {
        setState(() => _error =
            'No UPI app found on this phone. Copy the UPI ID above and pay '
            'from your bank app instead.');
      }
    } catch (_) {
      if (!mounted) return;
      setState(() => _error =
          'Could not open a UPI app. Copy the UPI ID above and pay from your '
          'bank app instead.');
    }
  }

  Future<void> _claim() async {
    setState(() {
      _claiming = true;
      _error = null;
    });
    final orders = context.read<OrderService>();
    final cart = context.read<CartState>();
    try {
      await orders.claimPaid(widget.order.id);
      if (!mounted) return;
      // The cart is cleared only now. Before the claim the order is still
      // cancellable by the pay window, and a customer who backs out should
      // find their basket intact.
      cart.clear();
      widget.onClaimed?.call();
      if (widget.onClaimed != null) return;
      Navigator.of(context).pushReplacement(MaterialPageRoute(
        builder: (_) => PickupScreen(
          orderId: widget.order.id,
          amount: widget.order.finalAmount,
          outletName: widget.outletName,
        ),
      ));
    } on ApiException catch (e) {
      // The server's own prose, not a generic failure: PAY_WINDOW_EXPIRED and
      // NOT_CLAIMABLE both tell the customer something they can act on.
      if (mounted) {
        setState(() {
          _claiming = false;
          _error = e.message;
        });
      }
    } catch (_) {
      if (mounted) {
        setState(() {
          _claiming = false;
          _error = 'Could not reach the restaurant. Check your connection '
              'and try again.';
        });
      }
    }
  }

  @override
  Widget build(BuildContext context) {
    final c = AppColors.of(context);
    final textTheme = Theme.of(context).textTheme;
    final upi = _upi;

    if (upi == null) {
      // Defensive: the server does not return a UPI order without a VPA
      // (ck_outlets_upi_manual_requires_vpa makes it impossible), so this is a
      // dead end rather than a state to design for — but a blank screen with a
      // Pay button would be worse than saying so.
      return Scaffold(
        appBar: AppBar(title: const Text('Pay')),
        body: Center(
          child: Padding(
            padding: const EdgeInsets.all(28),
            child: Text(
              'This restaurant has not finished setting up UPI payments. '
              'Please contact them directly.',
              key: const Key('upi_pay_unavailable'),
              textAlign: TextAlign.center,
              style: textTheme.bodyLarge,
            ),
          ),
        ),
      );
    }

    return Scaffold(
      appBar: AppBar(
        title: const Text('Pay by UPI'),
        actions: careVoActions(),
      ),
      body: SafeArea(
        child: ListView(
          padding: const EdgeInsets.fromLTRB(20, 12, 20, 24),
          children: [
            Text('Pay ${formatRupees(upi.amount)}',
                key: const Key('upi_amount_heading'),
                style: textTheme.displaySmall),
            const SizedBox(height: 6),
            Text(
              upi.payeeName.trim().isEmpty
                  ? 'Pay the restaurant directly from your UPI app.'
                  : 'to ${upi.payeeName}',
              key: const Key('upi_payee_line'),
              style: textTheme.titleMedium?.copyWith(color: c.inkSoft),
            ),
            const SizedBox(height: 20),

            // The UPI ID, with a copy button. Shown as text as well as behind
            // the intent button because plenty of people pay from a banking
            // app that the chooser will not surface.
            NeoCard(
              child: Row(
                children: [
                  Expanded(
                    child: Column(
                      crossAxisAlignment: CrossAxisAlignment.start,
                      children: [
                        Text('UPI ID',
                            style: textTheme.bodySmall
                                ?.copyWith(color: c.inkSoft)),
                        const SizedBox(height: 2),
                        Text(upi.vpa,
                            key: const Key('upi_vpa_text'),
                            style: textTheme.titleMedium),
                      ],
                    ),
                  ),
                  IconButton(
                    key: const Key('upi_copy_vpa'),
                    tooltip: 'Copy UPI ID',
                    onPressed: _copyVpa,
                    icon: const Icon(Icons.copy_outlined),
                  ),
                ],
              ),
            ),
            const SizedBox(height: 12),

            // The order number, because it is what the restaurant matches the
            // payment against alongside the amount.
            NeoCard(
              child: Row(
                children: [
                  Icon(Icons.receipt_long_outlined, color: c.primary),
                  const SizedBox(width: 14),
                  Expanded(
                    child: Text('Reference: ${upi.note}',
                        key: const Key('upi_note_text'),
                        style: textTheme.titleMedium),
                  ),
                ],
              ),
            ),
            const SizedBox(height: 20),

            NeoButton(
              key: const Key('upi_open_app'),
              label: 'Open UPI app',
              icon: Icons.account_balance_outlined,
              onPressed: _openUpiApp,
            ),
            const SizedBox(height: 20),

            Text(
              'Pay the exact amount, then tap below. The restaurant checks '
              'their UPI app before they start cooking.',
              key: const Key('upi_exact_amount_note'),
              style: textTheme.bodyMedium?.copyWith(color: c.inkSoft),
            ),
            const SizedBox(height: 14),

            NeoButton(
              key: const Key('upi_claim_paid'),
              label: "I've paid",
              icon: Icons.check_circle_outline,
              loading: _claiming,
              // Deliberately enabled even when the intent was never opened:
              // paying from another device or another app is normal, and the
              // app must not decide it knows better. `_opened` only changes
              // the emphasis below.
              onPressed: _claiming ? null : _claim,
            ),
            if (!_opened) ...[
              const SizedBox(height: 10),
              Text(
                'Already paid another way? Tap "I\'ve paid" anyway.',
                style: textTheme.bodySmall?.copyWith(color: c.inkSoft),
                textAlign: TextAlign.center,
              ),
            ],
            if (_error != null) ...[
              const SizedBox(height: 16),
              Row(
                key: const Key('upi_error'),
                crossAxisAlignment: CrossAxisAlignment.start,
                children: [
                  Icon(Icons.error_outline, size: 18, color: AppColors.tomato),
                  const SizedBox(width: 8),
                  Expanded(
                    child: Text(_error!,
                        style: textTheme.bodyMedium
                            ?.copyWith(color: AppColors.tomato)),
                  ),
                ],
              ),
            ],
            const SizedBox(height: 20),
            Text(
              'Pay within a few minutes or this order is cancelled '
              'automatically.',
              key: const Key('upi_window_note'),
              textAlign: TextAlign.center,
              style: textTheme.bodySmall?.copyWith(color: c.inkSoft),
            ),
          ],
        ),
      ),
    );
  }
}
