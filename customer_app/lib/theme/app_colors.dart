import 'package:flutter/material.dart';

/// Neobrutalist + retro-diner palette for CareVo Skip.
///
/// Colors are exposed both as raw brand constants and as light/dark
/// role sets so widgets can pull the correct value for the active theme
/// via `AppColors.of(context)`.
class AppColors {
  AppColors._();

  // ---- Brand constants (fixed regardless of theme) ----
  static const Color purple = Color(0xFF6B2FB3);
  static const Color purpleDeep = Color(0xFF4C1D86);
  static const Color mint = Color(0xFF8FD6B0);
  static const Color mintDeep = Color(0xFF5FB98B);
  static const Color cream = Color(0xFFF6EFE2);
  static const Color creamDim = Color(0xFFEDE3CF);
  static const Color ink = Color(0xFF171512);
  static const Color paper = Color(0xFFFFFDF7);

  // Accents used for status / feedback.
  static const Color sunny = Color(0xFFF4C542);
  static const Color tomato = Color(0xFFE2603A);
  static const Color sky = Color(0xFF7FB3E8);

  // Dark theme surfaces.
  static const Color darkBg = Color(0xFF1C1A17);
  static const Color darkSurface = Color(0xFF262320);
  static const Color darkInk = Color(0xFFF6EFE2);

  /// Resolve the role-based scheme for the active brightness.
  static AppColorScheme of(BuildContext context) {
    final isDark = Theme.of(context).brightness == Brightness.dark;
    return isDark ? dark : light;
  }

  static const AppColorScheme light = AppColorScheme(
    background: cream,
    surface: paper,
    surfaceAlt: creamDim,
    ink: ink,
    inkSoft: Color(0xFF4A453D),
    primary: purple,
    onPrimary: cream,
    accent: mint,
    onAccent: ink,
    border: ink,
    shadow: ink,
  );

  static const AppColorScheme dark = AppColorScheme(
    background: darkBg,
    surface: darkSurface,
    surfaceAlt: Color(0xFF33302B),
    ink: darkInk,
    inkSoft: Color(0xFFC7BFB0),
    primary: mint,
    onPrimary: ink,
    accent: purple,
    onAccent: cream,
    border: darkInk,
    shadow: Color(0xFF000000),
  );
}

/// Role-based color set consumed by widgets so light/dark both look correct.
class AppColorScheme {
  const AppColorScheme({
    required this.background,
    required this.surface,
    required this.surfaceAlt,
    required this.ink,
    required this.inkSoft,
    required this.primary,
    required this.onPrimary,
    required this.accent,
    required this.onAccent,
    required this.border,
    required this.shadow,
  });

  final Color background;
  final Color surface;
  final Color surfaceAlt;
  final Color ink;
  final Color inkSoft;
  final Color primary;
  final Color onPrimary;
  final Color accent;
  final Color onAccent;
  final Color border;
  final Color shadow;
}
