import 'package:flutter/material.dart';
import 'package:provider/provider.dart';

import '../state/cart_state.dart';
import '../theme/app_colors.dart';
import '../theme/app_theme.dart';
import 'price_text.dart';

/// Persistent bottom bar summarising the cart with a CTA to review it.
class CartBar extends StatelessWidget {
  const CartBar({super.key, required this.onView});
  final VoidCallback onView;

  @override
  Widget build(BuildContext context) {
    final cart = context.watch<CartState>();
    if (cart.isEmpty) return const SizedBox.shrink();
    final c = AppColors.of(context);
    final textTheme = Theme.of(context).textTheme;

    return SafeArea(
      top: false,
      child: Padding(
        padding: const EdgeInsets.fromLTRB(16, 0, 16, 16),
        child: GestureDetector(
          onTap: onView,
          child: Container(
            padding: const EdgeInsets.symmetric(horizontal: 18, vertical: 14),
            decoration: BoxDecoration(
              color: c.primary,
              borderRadius: BorderRadius.circular(AppTheme.radius),
              border: Border.all(color: c.border, width: AppTheme.borderWidth),
              boxShadow: [
                BoxShadow(color: c.shadow, offset: const Offset(4, 4), blurRadius: 0),
              ],
            ),
            child: Row(
              children: [
                Container(
                  padding: const EdgeInsets.all(8),
                  decoration: BoxDecoration(
                    color: c.accent,
                    borderRadius: BorderRadius.circular(10),
                    border: Border.all(color: c.border, width: 2),
                  ),
                  child: Text(
                    '${cart.totalQuantity}',
                    style: textTheme.labelLarge?.copyWith(color: c.onAccent),
                  ),
                ),
                const SizedBox(width: 12),
                Column(
                  crossAxisAlignment: CrossAxisAlignment.start,
                  mainAxisSize: MainAxisSize.min,
                  children: [
                    Text('View cart',
                        style: textTheme.titleMedium?.copyWith(color: c.onPrimary)),
                    PriceText(
                      cart.subtotal,
                      style: textTheme.bodySmall?.copyWith(
                        color: c.onPrimary.withValues(alpha: 0.85),
                      ),
                    ),
                  ],
                ),
                const Spacer(),
                Icon(Icons.arrow_forward, color: c.onPrimary),
              ],
            ),
          ),
        ),
      ),
    );
  }
}
