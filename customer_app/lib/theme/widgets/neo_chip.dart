import 'package:flutter/material.dart';

import '../app_colors.dart';
import '../app_theme.dart';

/// Selectable chip used for horizontal category rails and tags.
class NeoChip extends StatelessWidget {
  const NeoChip({
    super.key,
    required this.label,
    this.selected = false,
    this.onTap,
    this.icon,
  });

  final String label;
  final bool selected;
  final VoidCallback? onTap;
  final IconData? icon;

  @override
  Widget build(BuildContext context) {
    final c = AppColors.of(context);
    final bg = selected ? c.primary : c.surface;
    final fg = selected ? c.onPrimary : c.ink;

    return GestureDetector(
      onTap: onTap,
      child: AnimatedContainer(
        duration: const Duration(milliseconds: 120),
        padding: const EdgeInsets.symmetric(horizontal: 16, vertical: 9),
        decoration: BoxDecoration(
          color: bg,
          borderRadius: BorderRadius.circular(AppTheme.radius),
          border: Border.all(color: c.border, width: AppTheme.borderWidth),
          boxShadow: [
            BoxShadow(
              color: c.shadow,
              offset: selected ? const Offset(3, 3) : const Offset(2, 2),
              blurRadius: 0,
            ),
          ],
        ),
        child: Row(
          mainAxisSize: MainAxisSize.min,
          children: [
            if (icon != null) ...[
              Icon(icon, size: 16, color: fg),
              const SizedBox(width: 6),
            ],
            Text(
              label,
              style: Theme.of(context).textTheme.labelLarge?.copyWith(
                    color: fg,
                    fontSize: 14,
                  ),
            ),
          ],
        ),
      ),
    );
  }
}
