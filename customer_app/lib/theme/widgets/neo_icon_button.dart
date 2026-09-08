import 'package:flutter/material.dart';

import '../app_colors.dart';
import '../app_theme.dart';

/// A square, bordered, hard-shadowed icon button.
///
/// The prototype's auth and detail screens carry no app bar — the back affordance
/// is a small bordered chip sitting in the content, in the same visual language
/// as every other surface. This is that chip.
class NeoIconButton extends StatefulWidget {
  const NeoIconButton({
    super.key,
    required this.icon,
    required this.onPressed,
    this.tooltip,
    this.color,
    this.size = 22,
  });

  final IconData icon;
  final VoidCallback? onPressed;
  final String? tooltip;

  /// Fill. Defaults to the card surface.
  final Color? color;
  final double size;

  @override
  State<NeoIconButton> createState() => _NeoIconButtonState();
}

class _NeoIconButtonState extends State<NeoIconButton> {
  bool _pressed = false;

  @override
  Widget build(BuildContext context) {
    final c = AppColors.of(context);
    final disabled = widget.onPressed == null;
    final pressed = _pressed && !disabled;

    final button = GestureDetector(
      onTapDown: disabled ? null : (_) => setState(() => _pressed = true),
      onTapUp: disabled ? null : (_) => setState(() => _pressed = false),
      onTapCancel: disabled ? null : () => setState(() => _pressed = false),
      onTap: widget.onPressed,
      child: AnimatedContainer(
        duration: const Duration(milliseconds: 70),
        transform: Matrix4.translationValues(
          pressed ? 3 : 0,
          pressed ? 3 : 0,
          0,
        ),
        padding: const EdgeInsets.all(9),
        decoration: BoxDecoration(
          color: widget.color ?? c.surface,
          borderRadius: BorderRadius.circular(AppTheme.radius - 4),
          border: Border.all(color: c.border, width: AppTheme.borderWidth),
          boxShadow: [
            BoxShadow(
              color: c.shadow,
              offset: pressed ? Offset.zero : const Offset(3, 3),
              blurRadius: 0,
            ),
          ],
        ),
        child: Icon(widget.icon, size: widget.size, color: c.ink),
      ),
    );

    if (widget.tooltip == null) return button;
    return Tooltip(message: widget.tooltip!, child: button);
  }
}
