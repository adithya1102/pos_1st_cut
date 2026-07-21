import 'package:flutter/material.dart';
import 'package:provider/provider.dart';

import '../models/cart_item.dart';
import '../state/cart_state.dart';
import '../theme/app_colors.dart';
import '../theme/widgets/neo_button.dart';
import '../theme/widgets/neo_card.dart';
import '../theme/widgets/neo_text_field.dart';
import '../widgets/price_text.dart';
import '../widgets/theme_toggle_button.dart';
import '../widgets/veg_badge.dart';
import 'checkout_screen.dart';

/// Step 7: cart review. Prominent SELF PICKUP callout, NO delivery option.
class CartScreen extends StatefulWidget {
  const CartScreen({super.key});

  @override
  State<CartScreen> createState() => _CartScreenState();
}

class _CartScreenState extends State<CartScreen> {
  final _notesController = TextEditingController();

  @override
  void dispose() {
    _notesController.dispose();
    super.dispose();
  }

  @override
  Widget build(BuildContext context) {
    final cart = context.watch<CartState>();
    final c = AppColors.of(context);
    final textTheme = Theme.of(context).textTheme;

    return Scaffold(
      appBar: AppBar(
        title: const Text('Your Cart'),
        actions: const [
          Padding(padding: EdgeInsets.only(right: 16), child: ThemeToggleButton()),
        ],
      ),
      bottomNavigationBar: cart.isEmpty
          ? null
          : _CheckoutBar(
              subtotal: cart.subtotal,
              onCheckout: () => Navigator.of(context).push(
                MaterialPageRoute(
                  builder: (_) => CheckoutScreen(
                    customerNotes: _notesController.text,
                  ),
                ),
              ),
            ),
      body: SafeArea(
        bottom: false,
        child: cart.isEmpty
            ? _EmptyCart()
            : ListView(
                padding: const EdgeInsets.fromLTRB(20, 12, 20, 24),
                children: [
                  // SELF PICKUP callout — the signature, prominent element.
                  _SelfPickupCallout(outletName: cart.outlet?.name ?? 'the outlet'),
                  const SizedBox(height: 20),
                  Text('Items', style: textTheme.headlineSmall),
                  const SizedBox(height: 12),
                  for (final line in cart.items) ...[
                    _CartLineCard(line: line),
                    const SizedBox(height: 12),
                  ],
                  const SizedBox(height: 8),
                  NeoTextField(
                    labelText: 'Notes for the kitchen (optional)',
                    controller: _notesController,
                    hintText: 'Any overall instructions?',
                    maxLines: 2,
                    maxLength: 160,
                  ),
                  const SizedBox(height: 20),
                  _BillSummary(subtotal: cart.subtotal),
                  const SizedBox(height: 12),
                  Center(
                    child: Text(
                      'No delivery fees — you pick it up yourself.',
                      style: textTheme.bodySmall?.copyWith(color: c.inkSoft),
                    ),
                  ),
                ],
              ),
      ),
    );
  }
}

class _SelfPickupCallout extends StatelessWidget {
  const _SelfPickupCallout({required this.outletName});
  final String outletName;

  @override
  Widget build(BuildContext context) {
    final c = AppColors.of(context);
    final textTheme = Theme.of(context).textTheme;
    return NeoCard(
      color: c.accent,
      shadowOffset: const Offset(5, 5),
      child: Row(
        children: [
          Container(
            padding: const EdgeInsets.all(12),
            decoration: BoxDecoration(
              color: c.surface,
              borderRadius: BorderRadius.circular(12),
              border: Border.all(color: c.border, width: 3),
            ),
            child: Icon(Icons.storefront, color: c.primary, size: 30),
          ),
          const SizedBox(width: 14),
          Expanded(
            child: Column(
              crossAxisAlignment: CrossAxisAlignment.start,
              children: [
                Text('SELF PICKUP',
                    style: textTheme.titleLarge?.copyWith(
                      color: c.onAccent,
                      letterSpacing: 1.5,
                    )),
                const SizedBox(height: 4),
                Text(
                  'Collect your order at $outletName. No delivery — skip the wait.',
                  style: textTheme.bodyMedium?.copyWith(color: c.onAccent),
                ),
              ],
            ),
          ),
        ],
      ),
    );
  }
}

class _CartLineCard extends StatelessWidget {
  const _CartLineCard({required this.line});
  final CartItem line;

  @override
  Widget build(BuildContext context) {
    final cart = context.read<CartState>();
    final c = AppColors.of(context);
    final textTheme = Theme.of(context).textTheme;

    return NeoCard(
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          Row(
            crossAxisAlignment: CrossAxisAlignment.start,
            children: [
              VegBadge(isVeg: line.item.isVeg),
              const SizedBox(width: 8),
              Expanded(child: Text(line.item.name, style: textTheme.titleMedium)),
              PriceText(line.lineTotal),
            ],
          ),
          if (line.selectedOptions.isNotEmpty) ...[
            const SizedBox(height: 6),
            Text(
              line.selectedOptions.map((o) => o.optionName).join(' · '),
              style: textTheme.bodySmall?.copyWith(color: c.inkSoft),
            ),
          ],
          if ((line.notes ?? '').trim().isNotEmpty) ...[
            const SizedBox(height: 4),
            Text('Note: ${line.notes!.trim()}',
                style: textTheme.bodySmall?.copyWith(fontStyle: FontStyle.italic)),
          ],
          const SizedBox(height: 12),
          Row(
            children: [
              _MiniButton(icon: Icons.remove, onTap: () => cart.decrement(line.lineId)),
              SizedBox(
                width: 44,
                child: Center(
                  child: Text('${line.quantity}', style: textTheme.titleMedium),
                ),
              ),
              _MiniButton(icon: Icons.add, onTap: () => cart.increment(line.lineId)),
              const Spacer(),
              TextButton.icon(
                onPressed: () => cart.removeLine(line.lineId),
                icon: Icon(Icons.delete_outline, size: 18, color: c.inkSoft),
                label: Text('Remove',
                    style: textTheme.bodyMedium?.copyWith(color: c.inkSoft)),
              ),
            ],
          ),
        ],
      ),
    );
  }
}

class _MiniButton extends StatelessWidget {
  const _MiniButton({required this.icon, required this.onTap});
  final IconData icon;
  final VoidCallback onTap;

  @override
  Widget build(BuildContext context) {
    final c = AppColors.of(context);
    return GestureDetector(
      onTap: onTap,
      child: Container(
        width: 38,
        height: 38,
        decoration: BoxDecoration(
          color: c.surfaceAlt,
          borderRadius: BorderRadius.circular(10),
          border: Border.all(color: c.border, width: 2.5),
        ),
        child: Icon(icon, size: 18, color: c.ink),
      ),
    );
  }
}

class _BillSummary extends StatelessWidget {
  const _BillSummary({required this.subtotal});
  final double subtotal;

  @override
  Widget build(BuildContext context) {
    final textTheme = Theme.of(context).textTheme;
    Widget row(String label, double value, {bool bold = false}) => Padding(
          padding: const EdgeInsets.symmetric(vertical: 4),
          child: Row(
            mainAxisAlignment: MainAxisAlignment.spaceBetween,
            children: [
              Text(label,
                  style: bold ? textTheme.titleMedium : textTheme.bodyLarge),
              PriceText(value,
                  style: bold ? textTheme.titleLarge : textTheme.bodyLarge),
            ],
          ),
        );

    return NeoCard(
      child: Column(
        children: [
          row('Subtotal', subtotal),
          row('Taxes & charges', 0),
          const SizedBox(height: 4),
          const Divider(thickness: 2),
          const SizedBox(height: 4),
          row('Total', subtotal, bold: true),
        ],
      ),
    );
  }
}

class _CheckoutBar extends StatelessWidget {
  const _CheckoutBar({required this.subtotal, required this.onCheckout});
  final double subtotal;
  final VoidCallback onCheckout;

  @override
  Widget build(BuildContext context) {
    final textTheme = Theme.of(context).textTheme;
    final c = AppColors.of(context);
    return SafeArea(
      top: false,
      child: Padding(
        padding: const EdgeInsets.fromLTRB(16, 8, 16, 16),
        child: Row(
          children: [
            Column(
              crossAxisAlignment: CrossAxisAlignment.start,
              mainAxisSize: MainAxisSize.min,
              children: [
                Text('Total', style: textTheme.bodySmall?.copyWith(color: c.inkSoft)),
                PriceText(subtotal, style: textTheme.titleLarge),
              ],
            ),
            const SizedBox(width: 16),
            Expanded(
              child: NeoButton(
                label: 'Checkout',
                icon: Icons.lock_outline,
                onPressed: onCheckout,
              ),
            ),
          ],
        ),
      ),
    );
  }
}

class _EmptyCart extends StatelessWidget {
  @override
  Widget build(BuildContext context) {
    final textTheme = Theme.of(context).textTheme;
    return Center(
      child: Padding(
        padding: const EdgeInsets.all(28),
        child: Column(
          mainAxisSize: MainAxisSize.min,
          children: [
            const Icon(Icons.shopping_bag_outlined, size: 56),
            const SizedBox(height: 14),
            Text('Your cart is empty', style: textTheme.headlineSmall),
            const SizedBox(height: 8),
            Text('Add some dishes to get started.',
                style: textTheme.bodyLarge, textAlign: TextAlign.center),
            const SizedBox(height: 20),
            NeoButton(
              label: 'Back to menu',
              icon: Icons.arrow_back,
              expand: false,
              variant: NeoButtonVariant.neutral,
              onPressed: () => Navigator.of(context).pop(),
            ),
          ],
        ),
      ),
    );
  }
}
