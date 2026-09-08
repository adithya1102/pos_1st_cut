import 'package:flutter/material.dart';
import 'package:flutter/services.dart';

import '../../widgets/focus_release.dart';
import '../app_colors.dart';
import '../app_theme.dart';

/// Text field styled with the ink border + hard-shadow surface.
///
/// Every input in the app is one of these, which is why the tap-outside focus
/// release lives here rather than being repeated per screen — see
/// [releaseFocus].
class NeoTextField extends StatelessWidget {
  const NeoTextField({
    super.key,
    this.controller,
    this.focusNode,
    this.hintText,
    this.labelText,
    this.keyboardType,
    this.prefixIcon,
    this.maxLength,
    this.inputFormatters,
    this.onChanged,
    this.onSubmitted,
    this.textAlign = TextAlign.start,
    this.autofocus = false,
    this.maxLines = 1,
    this.style,
    this.textCapitalization = TextCapitalization.none,
  });

  final TextEditingController? controller;
  final FocusNode? focusNode;
  final String? hintText;
  final String? labelText;
  final TextInputType? keyboardType;
  final IconData? prefixIcon;
  final int? maxLength;
  final List<TextInputFormatter>? inputFormatters;
  final ValueChanged<String>? onChanged;
  final ValueChanged<String>? onSubmitted;
  final TextAlign textAlign;
  final bool autofocus;
  final int maxLines;
  final TextStyle? style;
  final TextCapitalization textCapitalization;

  @override
  Widget build(BuildContext context) {
    final c = AppColors.of(context);
    return Column(
      crossAxisAlignment: CrossAxisAlignment.start,
      children: [
        if (labelText != null) ...[
          Text(
            labelText!,
            style: Theme.of(context).textTheme.labelLarge?.copyWith(color: c.ink),
          ),
          const SizedBox(height: 6),
        ],
        Container(
          decoration: BoxDecoration(
            color: c.surface,
            borderRadius: BorderRadius.circular(AppTheme.radius),
            border: Border.all(color: c.border, width: AppTheme.borderWidth),
            boxShadow: [
              BoxShadow(color: c.shadow, offset: const Offset(3, 3), blurRadius: 0),
            ],
          ),
          child: TextField(
            controller: controller,
            focusNode: focusNode,
            // THE tap-outside fix. On Android a TextField with a null
            // onTapOutside keeps focus when you tap away — the field stays
            // focused, so the IME stays up AND the caret keeps blinking. Those
            // were reported as two bugs; they are one piece of state.
            //
            // onTapOutside rather than a screen-level GestureDetector wrapping
            // the body: this hook is delivered outside the gesture arena, so it
            // cannot compete with (or swallow) taps meant for buttons and list
            // rows underneath. A translucent catch-all GestureDetector can.
            onTapOutside: (_) => releaseFocus(),
            keyboardType: keyboardType,
            maxLength: maxLength,
            maxLines: maxLines,
            autofocus: autofocus,
            textAlign: textAlign,
            textCapitalization: textCapitalization,
            inputFormatters: inputFormatters,
            onChanged: onChanged,
            onSubmitted: onSubmitted,
            cursorColor: c.primary,
            style: style ?? Theme.of(context).textTheme.bodyLarge,
            decoration: InputDecoration(
              counterText: '',
              hintText: hintText,
              hintStyle: Theme.of(context)
                  .textTheme
                  .bodyLarge
                  ?.copyWith(color: c.inkSoft),
              prefixIcon: prefixIcon == null ? null : Icon(prefixIcon, color: c.ink),
              border: InputBorder.none,
              contentPadding: const EdgeInsets.symmetric(horizontal: 16, vertical: 16),
            ),
          ),
        ),
      ],
    );
  }
}
