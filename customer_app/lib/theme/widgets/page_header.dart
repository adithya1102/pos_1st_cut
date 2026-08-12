import 'package:flutter/material.dart';

/// The page title, rendered on exactly ONE line, app-wide.
///
/// Headers used to carry hard `\n` breaks ("Pick a\nspot.", "Where are\nyou?")
/// which forced two lines regardless of how much room there was. This renders a
/// single line and scales the glyphs DOWN if the string is too wide for the
/// device, rather than wrapping — so the same header reads the same way on a
/// small phone as on a large one.
///
/// ## Font
/// This deliberately uses the theme's existing display font. The revision list
/// asked for a face called "Shock Surgent"; it is not in `design/`, not bundled
/// anywhere in the repo, and not in the google_fonts catalogue, so there is
/// nothing to apply. Substituting a lookalike would silently make a decision
/// that belongs to whoever named that font — see the report. When the file
/// arrives, adding it is a one-line change HERE and nowhere else, which is half
/// the reason this widget exists.
///
/// [textHeightBehavior] carries over the existing fix for Bevan's tall
/// ascenders: the theme sets a line height tighter than the font's natural line
/// box, which let the first line's glyphs overflow above the widget's top edge
/// and collide with the app bar.
class PageHeader extends StatelessWidget {
  const PageHeader(this.text, {super.key, this.style, this.color});

  final String text;

  /// Defaults to `displaySmall`. Pass a smaller role for dense screens.
  final TextStyle? style;
  final Color? color;

  @override
  Widget build(BuildContext context) {
    final base = style ?? Theme.of(context).textTheme.displaySmall;
    return SizedBox(
      width: double.infinity,
      child: FittedBox(
        fit: BoxFit.scaleDown,
        alignment: Alignment.centerLeft,
        child: Text(
          text,
          maxLines: 1,
          softWrap: false,
          overflow: TextOverflow.visible,
          style: color == null ? base : base?.copyWith(color: color),
          textHeightBehavior: const TextHeightBehavior(
            applyHeightToFirstAscent: false,
          ),
        ),
      ),
    );
  }
}
