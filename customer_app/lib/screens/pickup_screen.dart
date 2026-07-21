import 'dart:async';

import 'package:flutter/material.dart';
import 'package:google_fonts/google_fonts.dart';
import 'package:provider/provider.dart';

import '../config/app_config.dart';
import '../models/order.dart';
import '../services/order_service.dart';
import '../theme/app_colors.dart';
import '../theme/app_theme.dart';
import '../theme/widgets/neo_button.dart';
import '../theme/widgets/neo_card.dart';
import '../widgets/price_text.dart';
import '../widgets/theme_toggle_button.dart';
import 'location_screen.dart';

/// Step 10: pickup screen — large pickup code + Received→Preparing→Ready
/// stepper, polled every ~4s.
class PickupScreen extends StatefulWidget {
  const PickupScreen({super.key, required this.orderId});
  final String orderId;

  @override
  State<PickupScreen> createState() => _PickupScreenState();
}

class _PickupScreenState extends State<PickupScreen> {
  static const _steps = ['Received', 'Preparing', 'Ready'];

  Timer? _timer;
  OrderStatus? _status;
  String? _error;
  bool _loading = true;

  @override
  void initState() {
    super.initState();
    _poll();
    _timer = Timer.periodic(AppConfig.pickupPollInterval, (_) => _poll());
  }

  @override
  void dispose() {
    _timer?.cancel();
    super.dispose();
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
      if (status.stepIndex >= 2) {
        _timer?.cancel();
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

    return Scaffold(
      appBar: AppBar(
        automaticallyImplyLeading: false,
        title: const Text('Pickup'),
        actions: const [
          Padding(padding: EdgeInsets.only(right: 16), child: ThemeToggleButton()),
        ],
      ),
      body: SafeArea(
        child: _loading && status == null
            ? const Center(child: CircularProgressIndicator())
            : ListView(
                padding: const EdgeInsets.fromLTRB(20, 12, 20, 24),
                children: [
                  Text(
                    step >= 2 ? 'Ready to\ncollect!' : 'Order\nconfirmed.',
                    style: textTheme.displaySmall,
                  ),
                  const SizedBox(height: 6),
                  Text(
                    'Show or say your pickup code at the counter.',
                    style: textTheme.bodyLarge?.copyWith(color: c.inkSoft),
                  ),
                  const SizedBox(height: 20),
                  _PickupCodeCard(
                    code: status?.pickupCode,
                    highlight: step >= 2,
                  ),
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

class _PickupCodeCard extends StatelessWidget {
  const _PickupCodeCard({required this.code, required this.highlight});
  final String? code;
  final bool highlight;

  @override
  Widget build(BuildContext context) {
    final c = AppColors.of(context);
    final textTheme = Theme.of(context).textTheme;
    return NeoCard(
      color: highlight ? c.accent : c.primary,
      shadowOffset: const Offset(6, 6),
      padding: const EdgeInsets.symmetric(vertical: 28, horizontal: 20),
      child: Column(
        children: [
          Text(
            'PICKUP CODE',
            style: textTheme.labelLarge?.copyWith(
              color: highlight ? c.onAccent : c.onPrimary,
              letterSpacing: 4,
            ),
          ),
          const SizedBox(height: 12),
          Text(
            code ?? '••••',
            style: GoogleFonts.bevan(
              color: highlight ? c.onAccent : c.onPrimary,
              fontSize: 56,
              letterSpacing: 8,
            ),
          ),
          const SizedBox(height: 6),
          Text(
            highlight ? 'Your food is ready!' : 'Keep this handy',
            style: textTheme.bodyMedium?.copyWith(
              color: (highlight ? c.onAccent : c.onPrimary).withValues(alpha: 0.85),
            ),
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
              Text('Order #${status.id}', style: textTheme.titleMedium),
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
