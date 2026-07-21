import 'package:flutter/material.dart';

import '../app_colors.dart';
import '../app_theme.dart';

/// A container with a thick ink border and a HARD (no-blur) offset shadow.
/// The signature CareVo Skip surface.
class NeoCard extends StatelessWidget {
  const NeoCard({
    super.key,
    required this.child,
    this.color,
    this.padding = const EdgeInsets.all(16),
    this.margin = EdgeInsets.zero,
    this.onTap,
    this.borderColor,
    this.shadowOffset = AppTheme.hardShadowOffset,
    this.radius = AppTheme.radius,
  });

  final Widget child;
  final Color? color;
  final EdgeInsetsGeometry padding;
  final EdgeInsetsGeometry margin;
  final VoidCallback? onTap;
  final Color? borderColor;
  final Offset shadowOffset;
  final double radius;

  @override
  Widget build(BuildContext context) {
    final c = AppColors.of(context);
    final content = Container(
      padding: padding,
      decoration: BoxDecoration(
        color: color ?? c.surface,
        borderRadius: BorderRadius.circular(radius),
        border: Border.all(color: borderColor ?? c.border, width: AppTheme.borderWidth),
        boxShadow: [
          BoxShadow(
            color: c.shadow,
            offset: shadowOffset,
            blurRadius: 0,
          ),
        ],
      ),
      child: child,
    );

    return Container(
      margin: margin,
      child: onTap == null
          ? content
          : Material(
              color: Colors.transparent,
              child: InkWell(
                borderRadius: BorderRadius.circular(radius),
                onTap: onTap,
                child: content,
              ),
            ),
    );
  }
}
