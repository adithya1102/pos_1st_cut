import 'package:flutter/material.dart';

import '../models/menu.dart';
import '../theme/app_colors.dart';
import '../theme/widgets/neo_card.dart';
import 'price_text.dart';
import 'veg_badge.dart';

/// Width of the thumbnail column, and of the gutter that stands in for it when
/// the row is reserving space for siblings that have a photo.
const double _kThumbSlot = 72;
const double _kThumbGap = 12;

/// Width of the trailing action column.
///
/// Wide enough for the ADD pill and for the "customise" caption underneath it,
/// so neither can be what decides the column's width.
const double _kActionSlot = 78;

/// A menu item row: veg badge, name, meta, price + an ADD affordance.
///
/// ## Fixed columns, not content-driven ones
///
/// Every horizontal position in this row used to be decided by the width of
/// whatever text happened to be in it, so cards in the same list did not line
/// up with each other. Three separate reported symptoms, one cause:
///
///  * the ADD button sat at a different x depending on whether the label read
///    ADD or OUT and whether the "customise" caption was present;
///  * the veg/non-veg badge started at a different x depending on whether that
///    particular item had a photo;
///  * the prep-time cluster slid left and right with the price's digit count.
///
/// The row is now three columns with fixed geometry — a leading thumbnail slot,
/// a flexible middle, and a fixed trailing action slot — and the two things
/// inside the middle column that used to chase each other are anchored to
/// opposite edges. Nothing here measures text to decide a position.
class MenuItemCard extends StatelessWidget {
  const MenuItemCard({
    super.key,
    required this.item,
    required this.onTap,
    this.reserveThumbnail = false,
  });

  final MenuItem item;
  final VoidCallback onTap;

  /// Hold the thumbnail column open even when THIS item has no photo.
  ///
  /// Set by the list when any sibling has one, so a menu that mixes items with
  /// and without photos keeps every veg badge, name and price on the same
  /// vertical line. Left false when no item in the list has a photo, so a
  /// photoless menu does not carry an empty 72px gutter down its whole length.
  final bool reserveThumbnail;

  @override
  Widget build(BuildContext context) {
    final c = AppColors.of(context);
    final textTheme = Theme.of(context).textTheme;
    final available = item.isAvailable;
    final url = item.imageUrl;

    return Opacity(
      opacity: available ? 1 : 0.55,
      child: NeoCard(
        // TAPPABLE even when unavailable. It used to be inert, which left a
        // greyed row that swallowed presses with no explanation — the customer
        // taps their usual dish, nothing happens, and they cannot tell a
        // sold-out item from a broken screen. The caller answers the tap with
        // "{name} — not available"; see MenuScreen._openItem.
        onTap: onTap,
        child: Row(
          crossAxisAlignment: CrossAxisAlignment.start,
          children: [
            if (url != null) ...[
              _DishImage(url: url),
              const SizedBox(width: _kThumbGap),
            ] else if (reserveThumbnail)
              // An empty gutter, not a placeholder box: the alignment is what
              // matters, and drawing a grey square for every photoless item
              // would be louder than the problem it solves.
              const SizedBox(width: _kThumbSlot + _kThumbGap),
            Expanded(
              child: Column(
                crossAxisAlignment: CrossAxisAlignment.start,
                children: [
                  Row(
                    children: [
                      VegBadge(isVeg: item.isVeg),
                      const SizedBox(width: 8),
                      Expanded(
                        child: Text(
                          item.name,
                          style: textTheme.titleMedium,
                          // Bounded so a long name cannot grow the row's height
                          // out of step with its neighbours either.
                          maxLines: 2,
                          overflow: TextOverflow.ellipsis,
                        ),
                      ),
                    ],
                  ),
                  const SizedBox(height: 8),
                  Row(
                    children: [
                      PriceText(item.basePrice),
                      if (item.prepTimeMinutes > 0) ...[
                        // Spacer, not a fixed gap: this pins the prep time to
                        // the RIGHT edge of the middle column, so the price's
                        // digit count can no longer push it around.
                        const Spacer(),
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

/// The trailing ADD / OUT affordance, in a slot of constant width.
///
/// The width is [_kActionSlot] regardless of what is in it. Previously the
/// column sized itself to its widest child, so "ADD" + "customise" and a bare
/// "OUT" produced different widths and the button's left edge moved from card
/// to card — the most visible of the alignment bugs, because the eye tracks
/// straight down a column of buttons.
class _AddChip extends StatelessWidget {
  const _AddChip({required this.available, required this.hasOptions});
  final bool available;
  final bool hasOptions;

  @override
  Widget build(BuildContext context) {
    final c = AppColors.of(context);
    return SizedBox(
      width: _kActionSlot,
      child: Column(
        // Stretch, so the pill fills the fixed slot instead of centring at its
        // own intrinsic width inside it.
        crossAxisAlignment: CrossAxisAlignment.stretch,
        mainAxisSize: MainAxisSize.min,
        children: [
          Container(
            padding: const EdgeInsets.symmetric(vertical: 9),
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
              textAlign: TextAlign.center,
              style: Theme.of(context)
                  .textTheme
                  .labelLarge
                  ?.copyWith(color: available ? c.onAccent : c.inkSoft),
            ),
          ),
          if (hasOptions && available)
            Padding(
              padding: const EdgeInsets.only(top: 4),
              child: Text(
                'customise',
                textAlign: TextAlign.center,
                maxLines: 1,
                overflow: TextOverflow.ellipsis,
                style: Theme.of(context)
                    .textTheme
                    .bodySmall
                    ?.copyWith(fontSize: 10),
              ),
            ),
        ],
      ),
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
