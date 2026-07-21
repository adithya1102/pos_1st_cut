import 'package:flutter/material.dart';

import '../models/menu_item.dart';

/// A single dish row: name (+ price) and an availability toggle.
class DishRow extends StatelessWidget {
  final MenuItem item;
  final ValueChanged<bool> onChanged;

  const DishRow({super.key, required this.item, required this.onChanged});

  @override
  Widget build(BuildContext context) {
    final theme = Theme.of(context);
    final dimmed = !item.isAvailable;

    return ListTile(
      title: Text(
        item.name,
        style: TextStyle(
          fontWeight: FontWeight.w600,
          color: dimmed ? theme.colorScheme.outline : null,
        ),
      ),
      subtitle: Text(
        item.isAvailable ? 'Available' : 'Unavailable',
        style: theme.textTheme.bodySmall?.copyWith(
          color: item.isAvailable
              ? theme.colorScheme.primary
              : theme.colorScheme.outline,
        ),
      ),
      trailing: Row(
        mainAxisSize: MainAxisSize.min,
        children: [
          Text(
            '₹${item.basePrice.toStringAsFixed(0)}',
            style: theme.textTheme.labelLarge,
          ),
          const SizedBox(width: 8),
          Switch(value: item.isAvailable, onChanged: onChanged),
        ],
      ),
    );
  }
}
