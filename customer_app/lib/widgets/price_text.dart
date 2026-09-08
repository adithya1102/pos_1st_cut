import 'package:flutter/material.dart';

/// Formats a rupee amount consistently across the app.
String formatRupees(double amount) {
  final whole = amount == amount.roundToDouble();
  final value = whole ? amount.toStringAsFixed(0) : amount.toStringAsFixed(2);
  return '₹$value';
}

class PriceText extends StatelessWidget {
  const PriceText(this.amount, {super.key, this.style});
  final double amount;
  final TextStyle? style;

  @override
  Widget build(BuildContext context) {
    return Text(
      formatRupees(amount),
      style: style ??
          Theme.of(context)
              .textTheme
              .titleMedium
              ?.copyWith(fontWeight: FontWeight.w700),
    );
  }
}

/// A price in a FIXED-WIDTH, right-aligned cell.
///
/// Use this anywhere a price shares a row with text that must not move when the
/// amount does. A bare [PriceText] takes its intrinsic width, so ₹90 and ₹1,290
/// produce different column widths — which is what made neighbouring controls
/// visibly jump from row to row down a list.
///
/// Overlong amounts SCALE DOWN rather than wrap or ellipsize: a truncated price
/// is a wrong price, and this is the one kind of text where losing a character
/// changes the meaning rather than just the reading.
class PriceSlot extends StatelessWidget {
  const PriceSlot(
    this.amount, {
    super.key,
    this.width = 92,
    this.style,
    this.alignment = Alignment.centerRight,
  });

  final double amount;
  final double width;
  final TextStyle? style;
  final Alignment alignment;

  @override
  Widget build(BuildContext context) {
    return SizedBox(
      width: width,
      child: FittedBox(
        fit: BoxFit.scaleDown,
        alignment: alignment,
        child: PriceText(amount, style: style),
      ),
    );
  }
}
