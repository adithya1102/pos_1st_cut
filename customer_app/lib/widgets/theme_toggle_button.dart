import 'package:flutter/material.dart';
import 'package:provider/provider.dart';

import '../theme/app_colors.dart';
import '../theme/app_theme.dart';
import '../theme/theme_provider.dart';

/// A chunky sun/moon toggle that flips + persists the theme.
class ThemeToggleButton extends StatelessWidget {
  const ThemeToggleButton({super.key});

  @override
  Widget build(BuildContext context) {
    final c = AppColors.of(context);
    final theme = context.watch<ThemeProvider>();
    return GestureDetector(
      onTap: theme.toggle,
      child: Container(
        width: 44,
        height: 44,
        decoration: BoxDecoration(
          color: c.accent,
          borderRadius: BorderRadius.circular(AppTheme.radius),
          border: Border.all(color: c.border, width: AppTheme.borderWidth),
          boxShadow: [
            BoxShadow(color: c.shadow, offset: const Offset(3, 3), blurRadius: 0),
          ],
        ),
        child: Icon(
          theme.isDark ? Icons.dark_mode : Icons.light_mode,
          color: c.onAccent,
          size: 22,
        ),
      ),
    );
  }
}
