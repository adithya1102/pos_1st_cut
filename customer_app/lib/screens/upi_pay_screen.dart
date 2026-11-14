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

  /// The 12-digit UPI reference number (UTR) the customer reads out of their
  /// own UPI app after paying.
  ///
  /// WHY THE CLAIM NOW REQUIRES IT. Before this, "I've paid" was a bare
  /// assertion and the restaurant had to match a payment by amount and
  /// timestamp — which is ambiguous the moment two customers owe the same
  /// total within the same few minutes. The UTR is the bank's own identifier
  /// for the transfer, so the restaurant can search for it. Requiring it does
  /// not make the claim any more verified (CareVo cannot ask a bank anything);
  /// it makes the claim CHECKABLE by the only party who can check it.
  final _referenceController = TextEditingController();

  UpiPaymentInfo? get _upi => widget.order.upiPayment;

  /// Digits only and never more than 12, enforced by the input formatters on
  /// the field — so "complete" is simply "all 12 are there".
  bool get _referenceComplete => _referenceController.text.length == 12;

  @override
  void dispose() {
    _referenceController.dispose();
    super.dispose();
  }

  /// Puts [value] on the clipboard and says so.
  ///
  /// Every value the restaurant matches a payment against is copyable, because
  /// the alternative is the customer retyping it into a bank app mid-payment:
  /// a mistyped VPA sends money to a stranger and a mistyped amount cannot be
  /// matched to the order at all.
  Future<void> _copy(String value, String said) async {
    await Clipboard.setData(ClipboardData(text: value));
    if (!mounted) return;
    ScaffoldMessenger.of(context)
      ..hideCurrentSnackBar()
      ..showSnackBar(SnackBar(content: Text(said)));
  }

  Future<void> _copyVpa() async {
    final vpa = _upi?.vpa;
    if (vpa == null) return;
    await _copy(vpa, 'UPI ID copied');
  }

  /// The exact payable figure, in the form a bank app accepts pasted in —
  /// two decimals, no symbol, no separators. The same string the intent
  /// carries in `am=`, so what is pasted and what is deep-linked agree.
  Future<void> _copyAmount() async {
    final upi = _upi;
    if (upi == null) return;
    await _copy(upi.amountParam, 'Amount copied');
  }

  Future<void> _copyNote() async {
    final note = _upi?.note;
    if (note == null || note.isEmpty) return;
    await _copy(note, 'Reference copied');
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
      await orders.claimPaid(widget.order.id,
          upiReference: _referenceController.text);
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
      // The server's own prose, not a generic failure: PAY_WINDOW_EXPIRED,
      // NOT_CLAIMABLE, INVALID_UPI_REFERENCE (422) and
      // UPI_REFERENCE_ALREADY_USED (409) all tell the customer something they
      // can act on. Every one of those arrives as a `detail` MAP carrying a
      // `message`, which ApiClient extracts into [ApiException.message] — so
      // showing it is showing plain words, not a code. (This is also why the
      // backend raises the 12-digit rule itself instead of leaving it to
      // Pydantic, whose 422 body is a list that would surface here as the
      // useless "Request failed (422)".)
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

            // The exact amount, copyable. The restaurant matches the payment
            // on the amount as well as the reference, so a figure retyped
            // slightly wrong is a payment nobody can place.
            NeoCard(
              child: Row(
                children: [
                  Expanded(
                    child: Column(
                      crossAxisAlignment: CrossAxisAlignment.start,
                      children: [
                        Text('Exact amount',
                            style: textTheme.bodySmall
                                ?.copyWith(color: c.inkSoft)),
                        const SizedBox(height: 2),
                        Text(upi.amountParam,
                            key: const Key('upi_amount_text'),
                            style: textTheme.titleMedium),
                      ],
                    ),
                  ),
                  IconButton(
                    key: const Key('upi_copy_amount'),
                    tooltip: 'Copy amount',
                    onPressed: _copyAmount,
                    icon: const Icon(Icons.copy_outlined),
                  ),
                ],
              ),
            ),
            const SizedBox(height: 12),

            // The order reference, prominent and copyable. It is what the
            // restaurant reads in its own UPI app — it travels in the
            // intent's `tn=` field (see UpiPaymentInfo.intentUri), so the
            // string shown here and the one in the deep link are one value.
            NeoCard(
              child: Row(
                children: [
                  Icon(Icons.receipt_long_outlined, color: c.primary),
                  const SizedBox(width: 14),
                  Expanded(
                    child: Column(
                      crossAxisAlignment: CrossAxisAlignment.start,
                      children: [
                        Text('Order reference',
                            style: textTheme.bodySmall
                                ?.copyWith(color: c.inkSoft)),
                        const SizedBox(height: 2),
                        Text(upi.note,
                            key: const Key('upi_note_text'),
                            style: textTheme.titleMedium),
                      ],
                    ),
                  ),
                  IconButton(
                    key: const Key('upi_copy_note'),
                    tooltip: 'Copy order reference',
                    onPressed: _copyNote,
                    icon: const Icon(Icons.copy_outlined),
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

            // THE REFERENCE NUMBER. Typed, not copied: it does not exist
            // until the transfer has actually happened, which is what makes
            // it worth asking for — an empty field means there is nothing for
            // the restaurant to go and look up.
            //
            // Digits only and capped at 12 by the formatters, so the field
            // cannot hold a value the server would reject for its shape. The
            // server still re-checks: formatters are a convenience, not a
            // guarantee (a paste, an IME, or an older build all bypass them).
            TextField(
              key: const Key('upi_reference_field'),
              controller: _referenceController,
              keyboardType: TextInputType.number,
              inputFormatters: [
                FilteringTextInputFormatter.digitsOnly,
                LengthLimitingTextInputFormatter(12),
              ],
              maxLength: 12,
              decoration: const InputDecoration(
                hintText: '12-digit UPI reference number',
                labelText: 'UPI reference number',
                helperText: 'Find it in your UPI app next to this payment.',
                counterText: '',
                prefixIcon: Icon(Icons.pin_outlined),
                border: OutlineInputBorder(),
              ),
              // Rebuilds so the button below re-reads [_referenceComplete],
              // and clears a stale server error: once they are editing the
              // number, last attempt's complaint about it is noise.
              onChanged: (_) => setState(() => _error = null),
            ),
            const SizedBox(height: 14),

            NeoButton(
              key: const Key('upi_claim_paid'),
              label: "I've paid",
              icon: Icons.check_circle_outline,
              loading: _claiming,
              // GATED ON THE REFERENCE, and deliberately on nothing else.
              // Still enabled when the intent was never opened: paying from
              // another device or a banking app is normal and the app must not
              // decide it knows better. `_opened` only changes the emphasis
              // below. What it will not do is send a claim the restaurant
              // cannot look up, or one the server would bounce with a 422.
              onPressed:
                  (_claiming || !_referenceComplete) ? null : _claim,
            ),
            if (!_referenceComplete) ...[
              const SizedBox(height: 10),
              Text(
                'Enter the 12-digit reference number from your UPI app to '
                'confirm you have paid.',
                key: const Key('upi_reference_required_note'),
                style: textTheme.bodySmall?.copyWith(color: c.inkSoft),
                textAlign: TextAlign.center,
              ),
            ],
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
