import 'package:flutter/material.dart';

import '../app_colors.dart';
import '../app_theme.dart';

enum NeoButtonVariant { primary, accent, neutral, danger }

/// Chunky neobrutalist button with a hard offset shadow that "presses"
/// (shadow collapses, button nudges down) while held.
class NeoButton extends StatefulWidget {
  const NeoButton({
    super.key,
    required this.label,
    this.onPressed,
    this.icon,
    this.variant = NeoButtonVariant.primary,
    this.expand = true,
    this.loading = false,
    this.compact = false,
  });

  final String label;
  final VoidCallback? onPressed;
  final IconData? icon;
  final NeoButtonVariant variant;
  final bool expand;
  final bool loading;
  final bool compact;

  @override
  State<NeoButton> createState() => _NeoButtonState();
}

class _NeoButtonState extends State<NeoButton> {
  bool _pressed = false;

  @override
  Widget build(BuildContext context) {
    final c = AppColors.of(context);
    final disabled = widget.onPressed == null || widget.loading;

    final (bg, fg) = switch (widget.variant) {
      NeoButtonVariant.primary => (c.primary, c.onPrimary),
      NeoButtonVariant.accent => (c.accent, c.onAccent),
      NeoButtonVariant.neutral => (c.surface, c.ink),
      NeoButtonVariant.danger => (AppColors.tomato, AppColors.cream),
    };

    final pressed = _pressed && !disabled;
    final shadow = pressed ? Offset.zero : AppTheme.hardShadowOffset;

    final child = Row(
      mainAxisSize: widget.expand ? MainAxisSize.max : MainAxisSize.min,
      mainAxisAlignment: MainAxisAlignment.center,
      children: [
        if (widget.loading)
          SizedBox(
            width: 18,
            height: 18,
            child: CircularProgressIndicator(strokeWidth: 3, color: fg),
          )
        else ...[
          if (widget.icon != null) ...[
            Icon(widget.icon, color: fg, size: 20),
            const SizedBox(width: 8),
          ],
          Flexible(
            child: Text(
              widget.label,
              overflow: TextOverflow.ellipsis,
              style: Theme.of(context).textTheme.labelLarge?.copyWith(
                    color: fg,
                    fontSize: widget.compact ? 14 : 16,
                  ),
            ),
          ),
        ],
      ],
    );

    return Opacity(
      opacity: disabled && !widget.loading ? 0.5 : 1,
      child: GestureDetector(
        onTapDown: disabled ? null : (_) => setState(() => _pressed = true),
        onTapUp: disabled ? null : (_) => setState(() => _pressed = false),
        onTapCancel: disabled ? null : () => setState(() => _pressed = false),
        onTap: disabled ? null : widget.onPressed,
        child: AnimatedContainer(
          duration: const Duration(milliseconds: 70),
          transform: Matrix4.translationValues(
            pressed ? AppTheme.hardShadowOffset.dx : 0,
            pressed ? AppTheme.hardShadowOffset.dy : 0,
            0,
          ),
          padding: EdgeInsets.symmetric(
            horizontal: widget.compact ? 16 : 20,
            vertical: widget.compact ? 10 : 15,
          ),
          decoration: BoxDecoration(
            color: bg,
            borderRadius: BorderRadius.circular(AppTheme.radius),
            border: Border.all(color: c.border, width: AppTheme.borderWidth),
            boxShadow: [
              BoxShadow(color: c.shadow, offset: shadow, blurRadius: 0),
            ],
          ),
          child: child,
        ),
      ),
    );
  }
}
