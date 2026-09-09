import 'package:flutter/material.dart';

import '../models/menu_item.dart';

/// A single dish row: veg indicator, optional thumbnail, name (+ category/price)
/// and an availability toggle. Tapping the row opens the edit screen.
class DishRow extends StatelessWidget {
  final MenuItem item;
  final ValueChanged<bool> onChanged;
  final VoidCallback? onTap;

  const DishRow({
    super.key,
    required this.item,
    required this.onChanged,
    this.onTap,
  });

  @override
  Widget build(BuildContext context) {
    final theme = Theme.of(context);
    final dimmed = !item.isAvailable;
    final subtitleParts = <String>[
      item.isAvailable ? 'Available' : 'Unavailable',
      if (item.categoryName != null && item.categoryName!.isNotEmpty) item.categoryName!,
      if (item.prepTimeMinutes != null) '${item.prepTimeMinutes} min',
    ];

    return ListTile(
      onTap: onTap,
      leading: _leading(),
      title: Row(
        children: [
          _VegDot(isVeg: item.isVeg),
          const SizedBox(width: 8),
          Expanded(
            child: Text(
              item.name,
              style: TextStyle(
                fontWeight: FontWeight.w600,
                color: dimmed ? theme.colorScheme.outline : null,
              ),
            ),
          ),
        ],
      ),
      subtitle: Text(
        subtitleParts.join(' · '),
        style: theme.textTheme.bodySmall?.copyWith(
          color: item.isAvailable ? theme.colorScheme.primary : theme.colorScheme.outline,
        ),
      ),
      trailing: Row(
        mainAxisSize: MainAxisSize.min,
        children: [
          Text('₹${item.basePrice.toStringAsFixed(0)}', style: theme.textTheme.labelLarge),
          const SizedBox(width: 8),
          Switch(value: item.isAvailable, onChanged: onChanged),
        ],
      ),
    );
  }

  Widget _leading() {
    if (item.imageUrl != null && item.imageUrl!.isNotEmpty) {
      return ClipRRect(
        borderRadius: BorderRadius.circular(8),
        child: Image.network(
          item.imageUrl!,
          width: 44,
          height: 44,
          fit: BoxFit.cover,
          errorBuilder: (_, __, ___) => _placeholder(),
        ),
      );
    }
    return _placeholder();
  }

  Widget _placeholder() => Container(
        width: 44,
        height: 44,
        decoration: BoxDecoration(
          color: Colors.grey.shade200,
          borderRadius: BorderRadius.circular(8),
        ),
        child: const Icon(Icons.restaurant, size: 20, color: Colors.grey),
      );
}

/// Green (veg) / red (non-veg) square-in-square indicator.
class _VegDot extends StatelessWidget {
  final bool isVeg;
  const _VegDot({required this.isVeg});

  @override
  Widget build(BuildContext context) {
    final color = isVeg ? Colors.green : Colors.red;
    return Container(
      width: 14,
      height: 14,
      decoration: BoxDecoration(
        border: Border.all(color: color, width: 1.5),
        borderRadius: BorderRadius.circular(2),
      ),
      child: Center(
        child: Container(
          width: 7,
          height: 7,
          decoration: BoxDecoration(color: color, shape: BoxShape.circle),
        ),
      ),
    );
  }
}
