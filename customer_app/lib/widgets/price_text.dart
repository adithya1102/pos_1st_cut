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
