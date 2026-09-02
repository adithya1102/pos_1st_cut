import 'dart:async';

import 'package:flutter/material.dart';
import 'package:provider/provider.dart';

import '../models/order.dart';
import '../services/cashfree_service.dart';
import '../services/order_service.dart';
import '../theme/app_colors.dart';
import '../theme/widgets/neo_button.dart';
import '../theme/widgets/neo_card.dart';
import '../widgets/price_text.dart';
import 'pickup_screen.dart';

/// Where a Cashfree sheet that did NOT report success lands.
///
/// ## Why this is not simply a "payment failed, try again" screen
///
/// The SDK's callbacks fire on the DEVICE and are not authoritative — see the
/// class doc on [CashfreeService]. `onError` fires when the customer dismisses
/// the sheet, but it ALSO fires on genuine payments whose confirmation was lost
/// (app backgrounded returning from a UPI app, network dropped as the sheet
/// closed). The webhook is the only thing that moves an order to PAID.
///
/// So offering "Try Payment Again" the instant the sheet closes would open a
/// double-charge path: pay → confirmation lost → retry → the first payment's
/// webhook lands → charged twice. That is a worse bug than the one this screen
/// exists to fix.
///
/// This screen therefore does two things in order:
///
///   1. **Confirm.** Poll the order for [graceWindow] first. If the webhook
///      lands, this was never a failure — hand off to [PickupScreen] exactly as
///      the success path does, and never show a retry button at all.
///   2. **Only then offer retry.** Once the server has been given a fair chance
///      and still says unpaid, the customer gets "Try Payment Again".
///
/// Retry reopens the SAME order on the SAME payment session. A session id is
/// minted only by create_order server-side and there is no re-issue endpoint,
/// so a new order is neither possible here nor wanted: the customer keeps their
/// cart, their offer, their travel details and their price.
///
/// The cart is deliberately not touched anywhere in this file. Checkout stays
/// beneath this screen on the navigation stack, so backing out returns to it
/// with the basket exactly as it was — the customer is never sent back through
/// the menu to re-add items.
class PaymentOutcomeScreen extends StatefulWidget {
  const PaymentOutcomeScreen({
    super.key,
    required this.order,
    this.reason,
    this.graceWindow = defaultGraceWindow,
    this.pollInterval = defaultPollInterval,
  });

  /// The order that was already created and is still awaiting payment.
  final CreatedOrder order;

  /// What the SDK said went wrong. Advisory only.
  final String? reason;

  /// How long the webhook is given to land before retry is offered.
  ///
  /// Long enough to cover a normal UPI round trip, short enough that a customer
  /// staring at a spinner does not give up. Overridable so tests need not sit
  /// through it in real time.
  final Duration graceWindow;
  final Duration pollInterval;

  static const Duration defaultGraceWindow = Duration(seconds: 12);
  static const Duration defaultPollInterval = Duration(seconds: 3);

  /// Test/UI handles.
  static const confirmingKey = Key('payment_outcome_confirming');
  static const retryStateKey = Key('payment_outcome_retry');
  static const tryAgainKey = Key('payment_try_again');
  static const checkStatusKey = Key('payment_check_status');
  static const backToCartKey = Key('payment_back_to_cart');

  @override
  State<PaymentOutcomeScreen> createState() => _PaymentOutcomeScreenState();
}

enum _Phase {
  /// Giving the webhook its chance before calling this a failure.
  confirming,

  /// Server still says unpaid. Retry is offered.
  retry,

  /// A retry sheet is open.
  reopening,
}

class _PaymentOutcomeScreenState extends State<PaymentOutcomeScreen> {
  _Phase _phase = _Phase.confirming;

  /// Set when a retry attempt itself failed, so the second message can differ
  /// from the first rather than silently repeating it.
  String? _lastAttemptMessage;

  Timer? _poll;
  Timer? _giveUp;

  /// Set once this screen has navigated away.
  ///
  /// The poll tick and the grace deadline can land on the same instant. Without
  /// this, a poll that returns PAID at exactly the moment the window closes
  /// would hand off to pickup AND flip the phase to retry behind it — briefly
  /// offering to re-pay an order that just confirmed.
  bool _handedOff = false;

  @override
  void initState() {
    super.initState();
    _lastAttemptMessage = widget.reason;
    _startConfirming();
  }

  @override
  void dispose() {
    _poll?.cancel();
    _giveUp?.cancel();
    super.dispose();
  }

  /// Poll the order until it is PAID or the grace window expires.
  void _startConfirming() {
    _poll?.cancel();
    _giveUp?.cancel();
    setState(() => _phase = _Phase.confirming);

    _poll = Timer.periodic(widget.pollInterval, (_) => _checkPaid());
    _giveUp = Timer(widget.graceWindow, () {
      if (!mounted || _handedOff) return;
      _poll?.cancel();
      setState(() => _phase = _Phase.retry);
    });
    // Ask immediately as well: the webhook often beats the sheet closing, in
    // which case there is nothing to confirm and no reason to make the customer
    // watch a spinner.
    _checkPaid();
  }

  Future<void> _checkPaid() async {
    if (!mounted) return;
    final OrderStatus status;
    try {
      status = await context.read<OrderService>().fetchStatus(widget.order.id);
    } catch (_) {
      // Transient. The next tick retries; the grace window still expires on
      // schedule, so a dead network cannot trap the customer in confirming.
      return;
    }
    if (!mounted) return;
    if (status.paymentStatus.toUpperCase() == 'PAID') {
      _goToPickup();
    }
  }

  /// Hand off to the normal post-payment screen.
  ///
  /// pushReplacement, not push: this screen has done its job and must not sit
  /// in the stack behind a confirmed order. Checkout remains beneath, which is
  /// how PickupScreen has always been reached, and its own "Order more" clears
  /// the stack entirely.
  void _goToPickup() {
    if (_handedOff) return;
    _handedOff = true;
    _poll?.cancel();
    _giveUp?.cancel();
    Navigator.of(context).pushReplacement(
      MaterialPageRoute(
        builder: (_) => PickupScreen(
          orderId: widget.order.id,
          amount: widget.order.finalAmount,
        ),
      ),
    );
  }

  /// Reopen the same checkout for the same order.
  Future<void> _tryAgain() async {
    final sessionId = widget.order.payment?.paymentSessionId;
    if (sessionId == null || sessionId.isEmpty) {
      // Nothing to reopen. Should be unreachable — this screen is only pushed
      // from the Cashfree branch, which requires a session — but failing
      // loudly here beats opening an empty sheet.
      setState(() {
        _phase = _Phase.retry;
        _lastAttemptMessage =
            'This order can no longer be paid for. Please start a new one.';
      });
      return;
    }

    setState(() => _phase = _Phase.reopening);
    final result = await context.read<CashfreeService>().openCheckout(
          orderId: widget.order.id,
          paymentSessionId: sessionId,
        );
    if (!mounted) return;

    if (result.outcome == CheckoutOutcome.notStarted) {
      // The sheet never opened, so nothing was charged on this attempt.
      setState(() {
        _phase = _Phase.retry;
        _lastAttemptMessage = result.message ?? 'Could not open payment.';
      });
      return;
    }

    // Verified or failed, the same uncertainty applies as the first time, so
    // the same rule does: ask the server, do not trust the sheet.
    setState(() => _lastAttemptMessage = result.verified ? null : result.message);
    _startConfirming();
  }

  @override
  Widget build(BuildContext context) {
    final c = AppColors.of(context);
    final textTheme = Theme.of(context).textTheme;

    return Scaffold(
      appBar: AppBar(
        title: const Text('Payment'),
        // A back button, unlike PickupScreen: nothing has been paid for, so
        // returning to checkout is exactly right — and the cart is still there.
        automaticallyImplyLeading: true,
      ),
      body: SafeArea(
        child: ListView(
          padding: const EdgeInsets.fromLTRB(20, 24, 20, 24),
          children: _phase == _Phase.retry
              ? _retryBody(c, textTheme)
              : _confirmingBody(c, textTheme),
        ),
      ),
    );
  }

  List<Widget> _confirmingBody(AppColorScheme c, TextTheme textTheme) {
    return [
      Column(
        key: PaymentOutcomeScreen.confirmingKey,
        children: [
          const SizedBox(height: 40),
          const SizedBox(
            width: 48,
            height: 48,
            child: CircularProgressIndicator(strokeWidth: 4),
          ),
          const SizedBox(height: 28),
          Text(
            _phase == _Phase.reopening
                ? 'Opening payment…'
                : 'Checking with your bank',
            style: textTheme.headlineSmall,
            textAlign: TextAlign.center,
          ),
          const SizedBox(height: 8),
          Text(
            _phase == _Phase.reopening
                ? 'Complete the payment in the window that opens.'
                : 'If your payment did go through, this will confirm on its own '
                    'in a moment. Please don\'t pay again yet.',
            style: textTheme.bodyLarge?.copyWith(color: c.inkSoft),
            textAlign: TextAlign.center,
          ),
        ],
      ),
    ];
  }

  List<Widget> _retryBody(AppColorScheme c, TextTheme textTheme) {
    return [
      Column(
        key: PaymentOutcomeScreen.retryStateKey,
        crossAxisAlignment: CrossAxisAlignment.stretch,
        children: [
          Icon(Icons.error_outline, size: 56, color: AppColors.tomato),
          const SizedBox(height: 16),
          Text(
            'Payment not\ncompleted.',
            style: textTheme.displaySmall,
            textAlign: TextAlign.center,
          ),
          const SizedBox(height: 10),
          Text(
            _lastAttemptMessage ??
                'The payment was cancelled or didn\'t go through.',
            style: textTheme.bodyLarge?.copyWith(color: c.inkSoft),
            textAlign: TextAlign.center,
          ),
          const SizedBox(height: 8),
          Text(
            'You have not been charged. Your order is still here.',
            style: textTheme.bodyMedium?.copyWith(color: c.inkSoft),
            textAlign: TextAlign.center,
          ),
          const SizedBox(height: 24),
          // The order is restated rather than assumed remembered: the customer
          // has just been through a payment sheet and may have been sent to a
          // banking app and back.
          NeoCard(
            child: Row(
              children: [
                Icon(Icons.receipt_long, color: c.primary),
                const SizedBox(width: 14),
                Expanded(
                  child: Text('Your order is saved',
                      style: textTheme.titleMedium),
                ),
                PriceText(widget.order.finalAmount,
                    style: textTheme.titleMedium),
              ],
            ),
          ),
          const SizedBox(height: 24),
          NeoButton(
            key: PaymentOutcomeScreen.tryAgainKey,
            label: 'Try Payment Again',
            icon: Icons.refresh,
            onPressed: _tryAgain,
          ),
          const SizedBox(height: 12),
          // The escape hatch for "but my bank DID debit me". Rare, because the
          // grace window above catches nearly all of these, but a customer who
          // is sure must never be left arguing with a retry button.
          NeoButton(
            key: PaymentOutcomeScreen.checkStatusKey,
            label: 'I was charged — check status',
            icon: Icons.search,
            variant: NeoButtonVariant.neutral,
            onPressed: _goToPickup,
          ),
          const SizedBox(height: 12),
          NeoButton(
            key: PaymentOutcomeScreen.backToCartKey,
            label: 'Back to my order',
            icon: Icons.arrow_back,
            variant: NeoButtonVariant.neutral,
            onPressed: () => Navigator.of(context).pop(),
          ),
        ],
      ),
    ];
  }
}
