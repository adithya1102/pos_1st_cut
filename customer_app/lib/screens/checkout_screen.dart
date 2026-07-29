import 'package:flutter/material.dart';
import 'package:provider/provider.dart';

import '../services/api_client.dart';
import '../services/order_service.dart';
import '../services/payment_service.dart';
import '../services/upi_intent.dart';
import '../state/cart_state.dart';
import '../theme/app_colors.dart';
import '../theme/widgets/neo_button.dart';
import '../theme/widgets/neo_card.dart';
import '../widgets/price_text.dart';
import '../widgets/theme_toggle_button.dart';
import 'payment_processing_screen.dart';
import 'pickup_screen.dart';

/// Step 8: checkout with UPI / Card / Net Banking ONLY (no pay-at-counter).
class CheckoutScreen extends StatefulWidget {
  const CheckoutScreen({super.key, this.customerNotes});
  final String? customerNotes;

  @override
  State<CheckoutScreen> createState() => _CheckoutScreenState();
}

class _CheckoutScreenState extends State<CheckoutScreen> {
  PaymentMethod _method = PaymentMethod.upi;
  bool _placing = false;

  Future<void> _payNow() async {
    final cart = context.read<CartState>();
    final outlet = cart.outlet;
    final messenger = ScaffoldMessenger.of(context);
    setState(() => _placing = true);
    try {
      final order = await context.read<OrderService>().createOrder(
            cart.toOrderPayload(customerNotes: widget.customerNotes),
          );
      if (!mounted) return;

      // UPI-intent MVP: open the user's UPI app with the outlet's VPA + amount
      // locked, then wait on the pickup screen for staff to confirm payment.
      if (_method == PaymentMethod.upi) {
        final vpa = outlet?.upiId;
        if (vpa == null || vpa.isEmpty) {
          messenger.showSnackBar(const SnackBar(
              content: Text('This outlet has not set up UPI payments yet.')));
        } else {
          final opened = await UpiIntent.launch(
            payeeVpa: vpa,
            payeeName: outlet?.name ?? 'Restaurant',
            amount: order.totalAmount,
            orderId: order.id,
          );
          if (!opened) {
            messenger.showSnackBar(SnackBar(
                content: Text('Open your UPI app and pay $vpa '
                    '${formatRupees(order.totalAmount)}.')));
          }
        }
        if (!mounted) return;
        cart.clear();
        Navigator.of(context).pushReplacement(
          MaterialPageRoute(builder: (_) => PickupScreen(orderId: order.id)),
        );
        return;
      }

      Navigator.of(context).push(
        MaterialPageRoute(
          builder: (_) => PaymentProcessingScreen(order: order, method: _method),
        ),
      );
    } on ApiException catch (e) {
      if (mounted) {
        ScaffoldMessenger.of(context)
            .showSnackBar(SnackBar(content: Text(e.message)));
      }
    } catch (_) {
      if (mounted) {
        ScaffoldMessenger.of(context).showSnackBar(
          const SnackBar(content: Text('Could not place order. Try again.')),
        );
      }
    } finally {
      if (mounted) setState(() => _placing = false);
    }
  }

  @override
  Widget build(BuildContext context) {
    final cart = context.watch<CartState>();
    final textTheme = Theme.of(context).textTheme;
    final c = AppColors.of(context);

    return Scaffold(
      appBar: AppBar(
        title: const Text('Checkout'),
        actions: const [
          Padding(padding: EdgeInsets.only(right: 16), child: ThemeToggleButton()),
        ],
      ),
      bottomNavigationBar: SafeArea(
        top: false,
        child: Padding(
          padding: const EdgeInsets.fromLTRB(16, 8, 16, 16),
          child: NeoButton(
            label: 'Pay ${formatRupees(cart.subtotal)}  •  ${_method.label}',
            icon: Icons.lock,
            loading: _placing,
            onPressed: cart.isEmpty ? null : _payNow,
          ),
        ),
      ),
      body: SafeArea(
        bottom: false,
        child: ListView(
          padding: const EdgeInsets.fromLTRB(20, 12, 20, 24),
          children: [
            NeoCard(
              color: c.primary,
              child: Row(
                children: [
                  Icon(Icons.storefront, color: c.onPrimary),
                  const SizedBox(width: 12),
                  Expanded(
                    child: Text(
                      'Self pickup at ${cart.outlet?.name ?? 'the outlet'}',
                      style: textTheme.titleMedium?.copyWith(color: c.onPrimary),
                    ),
                  ),
                ],
              ),
            ),
            const SizedBox(height: 24),
            Text('Payment method', style: textTheme.headlineSmall),
            const SizedBox(height: 6),
            Text('Pay securely online. Counter payment is not available.',
                style: textTheme.bodyMedium?.copyWith(color: c.inkSoft)),
            const SizedBox(height: 16),
            for (final method in PaymentMethod.values) ...[
              _MethodTile(
                method: method,
                selected: _method == method,
                onTap: () => setState(() => _method = method),
              ),
              const SizedBox(height: 12),
            ],
            const SizedBox(height: 12),
            _TotalRow(subtotal: cart.subtotal),
          ],
        ),
      ),
    );
  }
}

class _MethodTile extends StatelessWidget {
  const _MethodTile({
    required this.method,
    required this.selected,
    required this.onTap,
  });
  final PaymentMethod method;
  final bool selected;
  final VoidCallback onTap;

  IconData get _icon => switch (method) {
        PaymentMethod.upi => Icons.qr_code_2,
        PaymentMethod.card => Icons.credit_card,
        PaymentMethod.netbanking => Icons.account_balance,
      };

  @override
  Widget build(BuildContext context) {
    final c = AppColors.of(context);
    final textTheme = Theme.of(context).textTheme;
    return NeoCard(
      onTap: onTap,
      color: selected ? c.accent : c.surface,
      child: Row(
        children: [
          Container(
            padding: const EdgeInsets.all(10),
            decoration: BoxDecoration(
              color: selected ? c.surface : c.surfaceAlt,
              borderRadius: BorderRadius.circular(10),
              border: Border.all(color: c.border, width: 2.5),
            ),
            child: Icon(_icon, color: c.ink),
          ),
          const SizedBox(width: 14),
          Expanded(
            child: Column(
              crossAxisAlignment: CrossAxisAlignment.start,
              children: [
                Text(method.label,
                    style: textTheme.titleMedium?.copyWith(
                        color: selected ? c.onAccent : c.ink)),
                Text(method.subtitle,
                    style: textTheme.bodySmall?.copyWith(
                        color: selected ? c.onAccent : c.inkSoft)),
              ],
            ),
          ),
          Icon(
            selected ? Icons.radio_button_checked : Icons.radio_button_off,
            color: selected ? c.onAccent : c.inkSoft,
          ),
        ],
      ),
    );
  }
}

class _TotalRow extends StatelessWidget {
  const _TotalRow({required this.subtotal});
  final double subtotal;

  @override
  Widget build(BuildContext context) {
    final textTheme = Theme.of(context).textTheme;
    return Container(
      padding: const EdgeInsets.symmetric(horizontal: 4, vertical: 4),
      decoration: const BoxDecoration(),
      child: Row(
        mainAxisAlignment: MainAxisAlignment.spaceBetween,
        children: [
          Text('Amount payable', style: textTheme.titleMedium),
          PriceText(subtotal,
              style: textTheme.headlineSmall?.copyWith(fontWeight: FontWeight.w700)),
        ],
      ),
    );
  }
}
