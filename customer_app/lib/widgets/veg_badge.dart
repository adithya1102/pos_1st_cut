import 'package:flutter/material.dart';

import '../theme/app_colors.dart';

/// The classic square veg / non-veg indicator (green dot / brown-red dot).
class VegBadge extends StatelessWidget {
  const VegBadge({super.key, required this.isVeg, this.size = 16});

  final bool isVeg;
  final double size;

  @override
  Widget build(BuildContext context) {
    final color = isVeg ? AppColors.mintDeep : AppColors.tomato;
    return Container(
      width: size,
      height: size,
      decoration: BoxDecoration(
        border: Border.all(color: color, width: 2),
        borderRadius: BorderRadius.circular(3),
      ),
      child: Center(
        child: Container(
          width: size * 0.5,
          height: size * 0.5,
          decoration: BoxDecoration(color: color, shape: BoxShape.circle),
        ),
      ),
    );
  }
}
