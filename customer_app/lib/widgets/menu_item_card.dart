import 'package:flutter/material.dart';

import '../models/menu.dart';
import '../theme/app_colors.dart';
import '../theme/widgets/neo_card.dart';
import 'price_text.dart';
import 'veg_badge.dart';

/// A menu item row: veg badge, name, meta, price + an ADD affordance.
class MenuItemCard extends StatelessWidget {
  const MenuItemCard({super.key, required this.item, required this.onTap});

  final MenuItem item;
  final VoidCallback onTap;

  @override
  Widget build(BuildContext context) {
    final c = AppColors.of(context);
    final textTheme = Theme.of(context).textTheme;
    final available = item.isAvailable;

    return Opacity(
      opacity: available ? 1 : 0.55,
      child: NeoCard(
        onTap: available ? onTap : null,
        child: Row(
          crossAxisAlignment: CrossAxisAlignment.start,
          children: [
            if (item.imageUrl != null) ...[
              _DishImage(url: item.imageUrl!),
              const SizedBox(width: 12),
            ],
            Expanded(
              child: Column(
                crossAxisAlignment: CrossAxisAlignment.start,
                children: [
                  Row(
                    children: [
                      VegBadge(isVeg: item.isVeg),
                      const SizedBox(width: 8),
                      Expanded(
                        child: Text(item.name, style: textTheme.titleMedium),
                      ),
                    ],
                  ),
                  const SizedBox(height: 8),
                  Row(
                    children: [
                      PriceText(item.basePrice),
                      if (item.prepTimeMinutes > 0) ...[
                        const SizedBox(width: 12),
                        Icon(Icons.schedule, size: 14, color: c.inkSoft),
                        const SizedBox(width: 3),
                        Text('${item.prepTimeMinutes} min',
                            style: textTheme.bodySmall),
                      ],
                    ],
                  ),
                  if (item.tags.isNotEmpty) ...[
                    const SizedBox(height: 8),
                    Wrap(
                      spacing: 6,
                      runSpacing: 6,
                      children: item.tags
                          .take(3)
                          .map((t) => _Tag(label: t))
                          .toList(),
                    ),
                  ],
                ],
              ),
            ),
            const SizedBox(width: 12),
            _AddChip(
              available: available,
              hasOptions: item.customizations.isNotEmpty,
            ),
          ],
        ),
      ),
    );
  }
}

/// Dish thumbnail with the neobrutalist bordered/shadowed treatment.
class _DishImage extends StatelessWidget {
  const _DishImage({required this.url});
  final String url;

  @override
  Widget build(BuildContext context) {
    final c = AppColors.of(context);
    return Container(
      width: 72,
      height: 72,
      decoration: BoxDecoration(
        color: c.surfaceAlt,
        borderRadius: BorderRadius.circular(12),
        border: Border.all(color: c.border, width: 3),
        boxShadow: [
          BoxShadow(color: c.shadow, offset: const Offset(3, 3), blurRadius: 0),
        ],
      ),
      clipBehavior: Clip.antiAlias,
      child: Image.network(
        url,
        fit: BoxFit.cover,
        // Neutral placeholder while loading / on failure — never breaks layout.
        loadingBuilder: (ctx, child, progress) =>
            progress == null ? child : Center(child: Icon(Icons.restaurant, color: c.inkSoft)),
        errorBuilder: (_, _, _) => Center(child: Icon(Icons.restaurant, color: c.inkSoft)),
      ),
    );
  }
}

class _AddChip extends StatelessWidget {
  const _AddChip({required this.available, required this.hasOptions});
  final bool available;
  final bool hasOptions;

  @override
  Widget build(BuildContext context) {
    final c = AppColors.of(context);
    return Column(
      children: [
        Container(
          padding: const EdgeInsets.symmetric(horizontal: 16, vertical: 9),
          decoration: BoxDecoration(
            color: available ? c.accent : c.surfaceAlt,
            borderRadius: BorderRadius.circular(12),
            border: Border.all(color: c.border, width: 3),
            boxShadow: [
              BoxShadow(color: c.shadow, offset: const Offset(3, 3), blurRadius: 0),
            ],
          ),
          child: Text(
            available ? 'ADD' : 'OUT',
            style: Theme.of(context)
                .textTheme
                .labelLarge
                ?.copyWith(color: available ? c.onAccent : c.inkSoft),
          ),
        ),
        if (hasOptions && available)
          Padding(
            padding: const EdgeInsets.only(top: 4),
            child: Text('customise',
                style: Theme.of(context).textTheme.bodySmall?.copyWith(fontSize: 10)),
          ),
      ],
    );
  }
}

class _Tag extends StatelessWidget {
  const _Tag({required this.label});
  final String label;

  @override
  Widget build(BuildContext context) {
    final c = AppColors.of(context);
    return Container(
      padding: const EdgeInsets.symmetric(horizontal: 8, vertical: 3),
      decoration: BoxDecoration(
        color: c.surfaceAlt,
        borderRadius: BorderRadius.circular(6),
        border: Border.all(color: c.border, width: 1.5),
      ),
      child: Text(
        label,
        style: Theme.of(context).textTheme.bodySmall?.copyWith(fontSize: 11),
      ),
    );
  }
}
