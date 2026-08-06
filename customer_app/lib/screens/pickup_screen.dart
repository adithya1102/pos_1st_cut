import 'dart:async';

import 'package:flutter/material.dart';
import 'package:google_fonts/google_fonts.dart';
import 'package:provider/provider.dart';

import '../config/app_config.dart';
import '../models/order.dart';
import '../models/order_notify.dart';
import '../services/location_service.dart';
import '../services/order_notify_service.dart';
import '../services/order_service.dart';
import '../services/upi_intent.dart';
import '../theme/app_colors.dart';
import '../theme/app_theme.dart';
import '../theme/widgets/neo_button.dart';
import '../theme/widgets/neo_card.dart';
import '../widgets/price_text.dart';
import 'location_screen.dart';
import '../widgets/account_button.dart';

/// Step 10: pickup screen — large pickup code + Received→Preparing→Ready
/// stepper, polled every ~4s.
class PickupScreen extends StatefulWidget {
  const PickupScreen({
    super.key,
    required this.orderId,
    this.upiVpa,
    this.payeeName,
    this.amount,
  });

  final String orderId;

  /// UPI-intent params (passed from checkout). When [upiVpa] is set and the
  /// order is still unpaid, a tappable "Pay via UPI" button is shown.
  final String? upiVpa;
  final String? payeeName;
  final double? amount;

  @override
  State<PickupScreen> createState() => _PickupScreenState();
}

class _PickupScreenState extends State<PickupScreen> {
  static const _steps = ['Received', 'Preparing', 'Ready'];

  Timer? _timer;
  OrderStatus? _status;
  String? _error;
  bool _loading = true;

  // Staff → customer "notify" pushes (display-only), over a WebSocket that
  // lives alongside — and never replaces — the polling loop above.
  OrderNotifyClient? _notifyClient;
  StreamSubscription<OrderNotify>? _notifySub;
  OrderNotify? _banner;
  Timer? _bannerTimer;

  // PE Step 3 travel events. Tracked locally for the session; the backend is
  // idempotent so re-taps or a reopened screen never double-record.
  bool _departed = false;
  bool _departing = false;
  bool _arrived = false;
  bool _feedbackSent = false;
  Timer? _locTimer;

  @override
  void initState() {
    super.initState();
    _poll();
    _timer = Timer.periodic(AppConfig.pickupPollInterval, (_) => _poll());
    _connectNotify();
  }

  @override
  void dispose() {
    _timer?.cancel();
    _bannerTimer?.cancel();
    _locTimer?.cancel();
    _notifySub?.cancel();
    _notifyClient?.dispose();
    super.dispose();
  }

  // ------------------------ PE Step 3: travel events -----------------------

  /// FR-C3 — "I'm leaving". Best-effort location (a denial still records the
  /// departure, just without coordinates) then kicks off en-route pings.
  Future<void> _onLeaving() async {
    final orders = context.read<OrderService>();
    final location = context.read<LocationService>();
    setState(() => _departing = true);
    try {
      final loc = await location.getCurrentLocation();
      await orders.depart(
        widget.orderId,
        lat: loc.hasCoordinates ? loc.latitude : null,
        lng: loc.hasCoordinates ? loc.longitude : null,
      );
      if (!mounted) return;
      setState(() => _departed = true);
      _startEnRoutePings();
    } catch (_) {
      // Non-fatal: the customer can retry; the button re-enables.
    } finally {
      if (mounted) setState(() => _departing = false);
    }
  }

  /// FR-C4 — stream location every 60s while en route. The backend throttles
  /// and infers the 150m geofence, so a stationary customer just gets ignored.
  void _startEnRoutePings() {
    _locTimer?.cancel();
    _locTimer = Timer.periodic(const Duration(seconds: 60), (_) => _pingLocation());
    _pingLocation();
  }

  Future<void> _pingLocation() async {
    if (!mounted || _arrived) return;
    final orders = context.read<OrderService>();
    // Timer-driven, so it must never raise a permission dialog on its own: it
    // rides on the grant "I'm leaving now" already asked for, and silently
    // no-ops without one.
    final loc = await context
        .read<LocationService>()
        .getCurrentLocation(allowPrompt: false);
    if (!mounted || !loc.hasCoordinates) return;
    try {
      await orders.sendLocation(
        widget.orderId,
        lat: loc.latitude!,
        lng: loc.longitude!,
      );
    } catch (_) {/* transient; next tick retries */}
  }

  /// FR-C4 / FR-C6 — explicit arrival tap (the fallback when GPS is off and the
  /// geofence can't fire on its own).
  Future<void> _onArrived() async {
    final orders = context.read<OrderService>();
    setState(() => _arrived = true);
    _locTimer?.cancel();
    try {
      await orders.arrived(widget.orderId);
    } catch (_) {
      if (mounted) setState(() => _arrived = false);
    }
  }

  /// FR-C5 — one-tap perceived-wait bucket, shown once after pickup.
  Future<void> _sendFeedback(String bucket) async {
    final orders = context.read<OrderService>();
    setState(() => _feedbackSent = true);
    try {
      await orders.sendWaitFeedback(widget.orderId, bucket);
    } catch (_) {
      if (mounted) setState(() => _feedbackSent = false);
    }
  }

  void _connectNotify() {
    final client = OrderNotifyClient(widget.orderId);
    _notifyClient = client;
    _notifySub = client.notifications.listen(_onNotify);
    client.connect();
  }

  void _onNotify(OrderNotify notify) {
    if (!mounted) return;
    _bannerTimer?.cancel();
    setState(() => _banner = notify);
    // ready/delayed auto-dismiss; item_unavailable stays until dismissed.
    if (!notify.isPersistent) {
      _bannerTimer = Timer(const Duration(seconds: 6), () {
        if (mounted) setState(() => _banner = null);
      });
    }
  }

  void _dismissBanner() {
    _bannerTimer?.cancel();
    setState(() => _banner = null);
  }

  Future<void> _poll() async {
    try {
      final status =
          await context.read<OrderService>().fetchStatus(widget.orderId);
      if (!mounted) return;
      setState(() {
        _status = status;
        _error = null;
        _loading = false;
      });
      // Keep polling through Ready → Completed so the wait-feedback prompt
      // (FR-C5) can appear once the pickup is verified; then stop.
      if (status.isCompleted) {
        _timer?.cancel();
        _locTimer?.cancel();
      }
    } catch (e) {
      if (!mounted) return;
      setState(() {
        _loading = false;
        _error = 'Reconnecting…';
      });
    }
  }

  @override
  Widget build(BuildContext context) {
    final c = AppColors.of(context);
    final textTheme = Theme.of(context).textTheme;
    final status = _status;
    final step = status?.stepIndex ?? 0;
    final isPaid = status?.paymentStatus.toUpperCase() == 'PAID';
    final completed = status?.isCompleted ?? false;
    final estimate = status?.waitEstimate;

    return Scaffold(
      appBar: AppBar(
        automaticallyImplyLeading: false,
        title: const Text('Pickup'),
        actions: careVoActions(),
      ),
      body: SafeArea(
        child: _loading && status == null
            ? const Center(child: CircularProgressIndicator())
            : ListView(
                padding: const EdgeInsets.fromLTRB(20, 12, 20, 24),
                children: [
                  if (_banner != null) ...[
                    _NotifyBanner(notify: _banner!, onDismiss: _dismissBanner),
                    const SizedBox(height: 16),
                  ],
                  Text(
                    step >= 2
                        ? 'Ready to\ncollect!'
                        : (isPaid ? 'Order\nconfirmed.' : 'Almost\nthere.'),
                    style: textTheme.displaySmall,
                  ),
                  const SizedBox(height: 6),
                  Text(
                    isPaid
                        ? 'Show or say your pickup code at the counter.'
                        : 'Pay via UPI, then the restaurant confirms your order.',
                    style: textTheme.bodyLarge?.copyWith(color: c.inkSoft),
                  ),
                  const SizedBox(height: 20),
                  // Bug 1: a REAL tappable button that launches the upi:// intent.
                  if (!isPaid && widget.upiVpa != null) ...[
                    _UpiPayButton(
                      vpa: widget.upiVpa!,
                      payeeName: widget.payeeName ?? 'Restaurant',
                      amount: status?.totalAmount ?? widget.amount ?? 0,
                      orderId: widget.orderId,
                    ),
                    const SizedBox(height: 16),
                  ],
                  _PickupCodeCard(
                    code: status?.pickupCode,
                    highlight: step >= 2,
                    paid: isPaid,
                  ),
                  // FR-C5 — perceived-wait prompt, shown once after pickup.
                  if (completed && !_feedbackSent) ...[
                    const SizedBox(height: 16),
                    _WaitFeedbackCard(onPick: _sendFeedback),
                  ],
                  // FR-C7 — cold-start / shadow estimate: always framed as a
                  // wide, approximate range while the engine is unproven.
                  if (isPaid && !completed && estimate != null) ...[
                    const SizedBox(height: 16),
                    _WaitEstimateCard(estimate: estimate),
                  ],
                  // FR-C3/C4/C6 — travel controls.
                  if (isPaid && !completed) ...[
                    const SizedBox(height: 16),
                    _TravelControls(
                      departed: _departed,
                      departing: _departing,
                      arrived: _arrived,
                      onLeaving: _departing ? null : _onLeaving,
                      onArrived: _onArrived,
                    ),
                  ],
                  const SizedBox(height: 24),
                  Text('Order status', style: textTheme.headlineSmall),
                  const SizedBox(height: 16),
                  _StatusStepper(currentStep: step, steps: _steps),
                  if (_error != null) ...[
                    const SizedBox(height: 12),
                    Row(
                      children: [
                        SizedBox(
                          width: 14,
                          height: 14,
                          child: CircularProgressIndicator(
                              strokeWidth: 2, color: c.inkSoft),
                        ),
                        const SizedBox(width: 8),
                        Text(_error!, style: textTheme.bodySmall),
                      ],
                    ),
                  ],
                  const SizedBox(height: 24),
                  if (status != null) _OrderSummaryCard(status: status),
                  const SizedBox(height: 24),
                  NeoButton(
                    label: 'Order more',
                    icon: Icons.add,
                    variant: NeoButtonVariant.neutral,
                    onPressed: () => Navigator.of(context).pushAndRemoveUntil(
                      MaterialPageRoute(builder: (_) => const LocationScreen()),
                      (route) => false,
                    ),
                  ),
                ],
              ),
      ),
    );
  }
}

/// Prominent, read-only banner surfacing a staff "notify" push over the
/// stepper. Reuses [NeoCard] so it looks native to the neobrutalist app.
/// Display-only: the single button is an X that dismisses locally.
class _NotifyBanner extends StatelessWidget {
  const _NotifyBanner({required this.notify, required this.onDismiss});
  final OrderNotify notify;
  final VoidCallback onDismiss;

  @override
  Widget build(BuildContext context) {
    final c = AppColors.of(context);
    final textTheme = Theme.of(context).textTheme;

    // Unavailable is a warning tone (sunny); ready/delayed use the accent.
    final bool warn = notify.type == OrderNotify.itemUnavailable;
    final Color bg = warn ? AppColors.sunny : c.accent;
    final Color fg = warn ? AppColors.ink : c.onAccent;

    return NeoCard(
      color: bg,
      shadowOffset: const Offset(5, 5),
      padding: const EdgeInsets.fromLTRB(16, 14, 10, 14),
      child: Row(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          Expanded(
            child: Column(
              crossAxisAlignment: CrossAxisAlignment.start,
              children: [
                Text(
                  'FROM THE KITCHEN',
                  style: textTheme.labelLarge?.copyWith(
                    color: fg.withValues(alpha: 0.75),
                    letterSpacing: 2,
                    fontSize: 11,
                  ),
                ),
                const SizedBox(height: 6),
                Text(
                  notify.bannerText,
                  style: textTheme.titleMedium?.copyWith(color: fg),
                ),
              ],
            ),
          ),
          const SizedBox(width: 4),
          IconButton(
            icon: Icon(Icons.close, color: fg, size: 22),
            visualDensity: VisualDensity.compact,
            tooltip: 'Dismiss',
            onPressed: onDismiss,
          ),
        ],
      ),
    );
  }
}

/// Tappable UPI pay button — actually launches the upi:// intent (bug 1 fix).
class _UpiPayButton extends StatefulWidget {
  const _UpiPayButton({
    required this.vpa,
    required this.payeeName,
    required this.amount,
    required this.orderId,
  });
  final String vpa;
  final String payeeName;
  final double amount;
  final String orderId;

  @override
  State<_UpiPayButton> createState() => _UpiPayButtonState();
}

class _UpiPayButtonState extends State<_UpiPayButton> {
  bool _busy = false;

  Future<void> _pay() async {
    setState(() => _busy = true);
    final messenger = ScaffoldMessenger.of(context);
    try {
      final opened = await UpiIntent.launch(
        payeeVpa: widget.vpa,
        payeeName: widget.payeeName,
        amount: widget.amount,
        orderId: widget.orderId,
      );
      if (!opened && mounted) {
        messenger.showSnackBar(SnackBar(
          content: Text('No UPI app found. Pay ${widget.vpa} '
              '${formatRupees(widget.amount)} from any UPI app.'),
        ));
      }
    } finally {
      if (mounted) setState(() => _busy = false);
    }
  }

  @override
  Widget build(BuildContext context) {
    return NeoButton(
      label: _busy
          ? 'Opening UPI…'
          : 'Pay ${formatRupees(widget.amount)} via UPI',
      icon: Icons.account_balance_wallet,
      loading: _busy,
      onPressed: _busy ? null : _pay,
    );
  }
}

/// FR-C7 — the customer-facing wait range. Shadow mode (§16): wide, labelled
/// "approximate", never a precise ETA or a departure instruction.
class _WaitEstimateCard extends StatelessWidget {
  const _WaitEstimateCard({required this.estimate});
  final WaitEstimate estimate;

  @override
  Widget build(BuildContext context) {
    final c = AppColors.of(context);
    final textTheme = Theme.of(context).textTheme;
    return NeoCard(
      color: c.surface,
      child: Row(
        children: [
          Icon(Icons.schedule, color: c.ink),
          const SizedBox(width: 14),
          Expanded(
            child: Column(
              crossAxisAlignment: CrossAxisAlignment.start,
              children: [
                Text('Estimated wait', style: textTheme.titleMedium),
                Text(
                  estimate.approximate
                      ? 'Rough guess — we\'re still learning this kitchen.'
                      : 'Based on the kitchen and your travel.',
                  style: textTheme.bodySmall?.copyWith(color: c.inkSoft),
                ),
              ],
            ),
          ),
          const SizedBox(width: 8),
          Text('~${estimate.label}',
              style: textTheme.titleLarge?.copyWith(fontWeight: FontWeight.w700)),
        ],
      ),
    );
  }
}

/// FR-C3/C4/C6 — "I'm leaving" → en-route → "I've arrived".
class _TravelControls extends StatelessWidget {
  const _TravelControls({
    required this.departed,
    required this.departing,
    required this.arrived,
    required this.onLeaving,
    required this.onArrived,
  });
  final bool departed;
  final bool departing;
  final bool arrived;
  final VoidCallback? onLeaving;
  final VoidCallback? onArrived;

  @override
  Widget build(BuildContext context) {
    final c = AppColors.of(context);
    final textTheme = Theme.of(context).textTheme;

    if (arrived) {
      return NeoCard(
        color: c.accent,
        child: Row(
          children: [
            Icon(Icons.check_circle, color: c.onAccent),
            const SizedBox(width: 12),
            Expanded(
              child: Text('You\'re here — head to the counter.',
                  style: textTheme.titleMedium?.copyWith(color: c.onAccent)),
            ),
          ],
        ),
      );
    }

    if (!departed) {
      return NeoButton(
        label: departing ? 'One sec…' : 'I\'m leaving now',
        icon: Icons.directions_run,
        loading: departing,
        onPressed: onLeaving,
      );
    }

    // Departed, not yet arrived.
    return NeoCard(
      color: c.surface,
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          Row(
            children: [
              Icon(Icons.navigation, color: c.primary),
              const SizedBox(width: 12),
              Expanded(
                child: Text('On your way — we\'re timing your food.',
                    style: textTheme.titleMedium),
              ),
            ],
          ),
          const SizedBox(height: 12),
          NeoButton(
            label: 'I\'ve arrived',
            icon: Icons.place,
            variant: NeoButtonVariant.neutral,
            onPressed: onArrived,
          ),
        ],
      ),
    );
  }
}

/// FR-C5 — perceived wait bucket, one tap.
class _WaitFeedbackCard extends StatelessWidget {
  const _WaitFeedbackCard({required this.onPick});
  final void Function(String bucket) onPick;

  static const _buckets = [
    ('0', 'No wait'),
    ('1-3', '1–3 min'),
    ('3-5', '3–5 min'),
    ('5+', '5+ min'),
  ];

  @override
  Widget build(BuildContext context) {
    final c = AppColors.of(context);
    final textTheme = Theme.of(context).textTheme;
    return NeoCard(
      color: c.surface,
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          Text('How long did you wait at the counter?',
              style: textTheme.titleMedium),
          const SizedBox(height: 4),
          Text('Helps us get your next order\'s timing right.',
              style: textTheme.bodySmall?.copyWith(color: c.inkSoft)),
          const SizedBox(height: 12),
          Wrap(
            spacing: 10,
            runSpacing: 10,
            children: [
              for (final b in _buckets)
                GestureDetector(
                  onTap: () => onPick(b.$1),
                  child: Container(
                    padding: const EdgeInsets.symmetric(horizontal: 14, vertical: 10),
                    decoration: BoxDecoration(
                      color: c.surfaceAlt,
                      borderRadius: BorderRadius.circular(10),
                      border: Border.all(color: c.border, width: 2.5),
                    ),
                    child: Text(b.$2, style: textTheme.titleSmall),
                  ),
                ),
            ],
          ),
        ],
      ),
    );
  }
}

class _PickupCodeCard extends StatelessWidget {
  const _PickupCodeCard({
    required this.code,
    required this.highlight,
    required this.paid,
  });
  final String? code;
  final bool highlight;
  final bool paid;

  @override
  Widget build(BuildContext context) {
    final c = AppColors.of(context);
    final textTheme = Theme.of(context).textTheme;
    final onColor = highlight ? c.onAccent : c.onPrimary;
    final hasCode = code != null && code!.isNotEmpty;
    return NeoCard(
      color: highlight ? c.accent : c.primary,
      shadowOffset: const Offset(6, 6),
      padding: const EdgeInsets.symmetric(vertical: 28, horizontal: 20),
      child: Column(
        children: [
          Text(
            'PICKUP CODE',
            style: textTheme.labelLarge?.copyWith(color: onColor, letterSpacing: 4),
          ),
          const SizedBox(height: 12),
          if (hasCode)
            Text(
              code!,
              style: GoogleFonts.bevan(color: onColor, fontSize: 56, letterSpacing: 8),
            )
          else ...[
            Icon(Icons.lock_clock, color: onColor.withValues(alpha: 0.9), size: 40),
            const SizedBox(height: 10),
            Text('Appears after payment',
                style: textTheme.titleMedium?.copyWith(color: onColor)),
          ],
          const SizedBox(height: 6),
          Text(
            hasCode
                ? (highlight ? 'Your food is ready!' : 'Keep this handy')
                : 'The restaurant will confirm your payment shortly.',
            textAlign: TextAlign.center,
            style: textTheme.bodyMedium?.copyWith(color: onColor.withValues(alpha: 0.85)),
          ),
        ],
      ),
    );
  }
}

class _StatusStepper extends StatelessWidget {
  const _StatusStepper({required this.currentStep, required this.steps});
  final int currentStep;
  final List<String> steps;

  @override
  Widget build(BuildContext context) {
    final c = AppColors.of(context);
    final textTheme = Theme.of(context).textTheme;
    final icons = [Icons.receipt_long, Icons.outdoor_grill, Icons.shopping_bag];

    return Column(
      children: [
        for (var i = 0; i < steps.length; i++)
          IntrinsicHeight(
            child: Row(
              crossAxisAlignment: CrossAxisAlignment.start,
              children: [
                Column(
                  children: [
                    _StepDot(
                      active: i <= currentStep,
                      current: i == currentStep,
                      icon: icons[i],
                    ),
                    if (i != steps.length - 1)
                      Expanded(
                        child: Container(
                          width: 3,
                          color: i < currentStep ? c.primary : c.border,
                        ),
                      ),
                  ],
                ),
                const SizedBox(width: 16),
                Padding(
                  padding: const EdgeInsets.only(top: 12, bottom: 20),
                  child: Column(
                    crossAxisAlignment: CrossAxisAlignment.start,
                    children: [
                      Text(
                        steps[i],
                        style: textTheme.titleMedium?.copyWith(
                          color: i <= currentStep ? c.ink : c.inkSoft,
                        ),
                      ),
                      Text(
                        _subtitle(i),
                        style: textTheme.bodySmall?.copyWith(color: c.inkSoft),
                      ),
                    ],
                  ),
                ),
              ],
            ),
          ),
      ],
    );
  }

  String _subtitle(int i) {
    switch (i) {
      case 0:
        return 'We\'ve got your order.';
      case 1:
        return 'The kitchen is cooking.';
      default:
        return 'Collect it at the counter.';
    }
  }
}

class _StepDot extends StatelessWidget {
  const _StepDot({required this.active, required this.current, required this.icon});
  final bool active;
  final bool current;
  final IconData icon;

  @override
  Widget build(BuildContext context) {
    final c = AppColors.of(context);
    return Container(
      width: 48,
      height: 48,
      decoration: BoxDecoration(
        color: active ? c.primary : c.surface,
        borderRadius: BorderRadius.circular(AppTheme.radius),
        border: Border.all(color: c.border, width: AppTheme.borderWidth),
        boxShadow: [
          BoxShadow(
            color: c.shadow,
            offset: current ? const Offset(4, 4) : const Offset(2, 2),
            blurRadius: 0,
          ),
        ],
      ),
      child: Icon(icon, color: active ? c.onPrimary : c.inkSoft, size: 22),
    );
  }
}

class _OrderSummaryCard extends StatelessWidget {
  const _OrderSummaryCard({required this.status});
  final OrderStatus status;

  @override
  Widget build(BuildContext context) {
    final textTheme = Theme.of(context).textTheme;
    final c = AppColors.of(context);
    return NeoCard(
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          Row(
            mainAxisAlignment: MainAxisAlignment.spaceBetween,
            children: [
              // Bug 3: truncate the UUID + Flexible so it can't overflow.
              Flexible(
                child: Text(
                  'Order #${status.id.length > 8 ? '${status.id.substring(0, 8)}…' : status.id}',
                  style: textTheme.titleMedium,
                  overflow: TextOverflow.ellipsis,
                ),
              ),
              const SizedBox(width: 8),
              _PaymentBadge(paid: status.paymentStatus.toUpperCase() == 'PAID'),
            ],
          ),
          const SizedBox(height: 12),
          for (final line in status.items)
            Padding(
              padding: const EdgeInsets.symmetric(vertical: 3),
              child: Row(
                children: [
                  Text('${line.quantity}×',
                      style: textTheme.bodyLarge?.copyWith(color: c.inkSoft)),
                  const SizedBox(width: 8),
                  Expanded(child: Text(line.name, style: textTheme.bodyLarge)),
                  PriceText(line.lineTotal, style: textTheme.bodyLarge),
                ],
              ),
            ),
          const SizedBox(height: 8),
          const Divider(thickness: 2),
          const SizedBox(height: 4),
          Row(
            mainAxisAlignment: MainAxisAlignment.spaceBetween,
            children: [
              Text('Total', style: textTheme.titleMedium),
              PriceText(status.totalAmount, style: textTheme.titleLarge),
            ],
          ),
        ],
      ),
    );
  }
}

class _PaymentBadge extends StatelessWidget {
  const _PaymentBadge({required this.paid});
  final bool paid;

  @override
  Widget build(BuildContext context) {
    final c = AppColors.of(context);
    return Container(
      padding: const EdgeInsets.symmetric(horizontal: 10, vertical: 5),
      decoration: BoxDecoration(
        color: paid ? c.accent : c.surfaceAlt,
        borderRadius: BorderRadius.circular(8),
        border: Border.all(color: c.border, width: 2),
      ),
      child: Text(
        paid ? 'PAID' : 'PENDING',
        style: Theme.of(context)
            .textTheme
            .labelLarge
            ?.copyWith(color: paid ? c.onAccent : c.inkSoft, fontSize: 12),
      ),
    );
  }
}
