import 'package:flutter/material.dart';
import 'package:provider/provider.dart';

import '../models/order.dart';
import '../services/payment_service.dart';
import '../state/cart_state.dart';
import '../theme/app_colors.dart';
import '../theme/app_theme.dart';
import '../theme/widgets/neo_button.dart';
import '../widgets/price_text.dart';
import 'pickup_screen.dart';

/// Step 9: payment processing. Drives [PaymentService] (stub → simulate)
/// then hands off to the pickup screen on success.
class PaymentProcessingScreen extends StatefulWidget {
  const PaymentProcessingScreen({
    super.key,
    required this.order,
    required this.method,
  });

  final CreatedOrder order;
  final PaymentMethod method;

  @override
  State<PaymentProcessingScreen> createState() =>
      _PaymentProcessingScreenState();
}

enum _Phase { processing, failed }

class _PaymentProcessingScreenState extends State<PaymentProcessingScreen> {
  _Phase _phase = _Phase.processing;
  String? _error;

  @override
  void initState() {
    super.initState();
    _process();
  }

  Future<void> _process() async {
    setState(() {
      _phase = _Phase.processing;
      _error = null;
    });
    // Capture provider references before any await to avoid using
    // BuildContext across async gaps.
    final paymentService = context.read<PaymentService>();
    final cart = context.read<CartState>();

    // Small delay so the processing state is visible for the stub gateway.
    await Future<void>.delayed(const Duration(milliseconds: 700));
    try {
      final result = await paymentService.pay(
            orderId: widget.order.id,
            method: widget.method,
          );
      if (!mounted) return;
      if (result.success) {
        cart.clear();
        Navigator.of(context).pushReplacement(
          MaterialPageRoute(
            builder: (_) => PickupScreen(orderId: widget.order.id),
          ),
        );
      } else {
        setState(() {
          _phase = _Phase.failed;
          _error = result.message ?? 'Payment could not be completed.';
        });
      }
    } catch (e) {
      if (!mounted) return;
      setState(() {
        _phase = _Phase.failed;
        _error = 'Payment failed. Please try again.';
      });
    }
  }

  @override
  Widget build(BuildContext context) {
    final c = AppColors.of(context);
    final textTheme = Theme.of(context).textTheme;

    return Scaffold(
      body: SafeArea(
        child: Center(
          child: Padding(
            padding: const EdgeInsets.all(28),
            child: _phase == _Phase.processing
                ? Column(
                    mainAxisSize: MainAxisSize.min,
                    children: [
                      Container(
                        padding: const EdgeInsets.all(28),
                        decoration: BoxDecoration(
                          color: c.accent,
                          borderRadius: BorderRadius.circular(AppTheme.radius),
                          border: Border.all(color: c.border, width: AppTheme.borderWidth),
                          boxShadow: [
                            BoxShadow(color: c.shadow, offset: const Offset(5, 5), blurRadius: 0),
                          ],
                        ),
                        child: SizedBox(
                          width: 46,
                          height: 46,
                          child: CircularProgressIndicator(
                              strokeWidth: 4, color: c.onAccent),
                        ),
                      ),
                      const SizedBox(height: 28),
                      Text('Processing payment', style: textTheme.headlineSmall),
                      const SizedBox(height: 8),
                      Text(
                        'Paying ${formatRupees(widget.order.totalAmount)} via ${widget.method.label}',
                        style: textTheme.bodyLarge?.copyWith(color: c.inkSoft),
                        textAlign: TextAlign.center,
                      ),
                      const SizedBox(height: 8),
                      Text('Please don\'t close this screen.',
                          style: textTheme.bodySmall),
                    ],
                  )
                : Column(
                    mainAxisSize: MainAxisSize.min,
                    children: [
                      Icon(Icons.error_outline, size: 60, color: AppColors.tomato),
                      const SizedBox(height: 16),
                      Text('Payment failed', style: textTheme.headlineSmall),
                      const SizedBox(height: 8),
                      Text(_error ?? 'Something went wrong.',
                          style: textTheme.bodyLarge, textAlign: TextAlign.center),
                      const SizedBox(height: 24),
                      NeoButton(
                        label: 'Retry payment',
                        icon: Icons.refresh,
                        onPressed: _process,
                      ),
                      const SizedBox(height: 12),
                      NeoButton(
                        label: 'Back to cart',
                        variant: NeoButtonVariant.neutral,
                        onPressed: () => Navigator.of(context).pop(),
                      ),
                    ],
                  ),
          ),
        ),
      ),
    );
  }
}
