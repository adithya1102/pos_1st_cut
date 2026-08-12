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

  // ---- Dark theme (v2) --------------------------------------------------
  // Replaces the old pale-brown dark surfaces, which read as a washed-out
  // version of the light theme rather than as a deliberate dark mode.
  //
  // paperCenter is the warm tan the ticket is printed on in dark mode;
  // contrastDark is the near-black surface/ink it sits against; contrastVibrant
  // is the single focal accent; contrastSlate is its complementary partner.
  static const Color paperCenter = Color(0xFFB5783A);
  static const Color contrastSlate = Color(0xFF3A77B5);
  static const Color contrastVibrant = Color(0xFF00D4FF);
  static const Color contrastDark = Color(0xFF0B1B2B);

  static const Color darkBg = contrastDark;
  static const Color darkSurface = Color(0xFF122436);
  static const Color darkInk = Color(0xFFEAF4FA);

  /// Resolve the role-based scheme for the active brightness.
  static AppColorScheme of(BuildContext context) {
    final isDark = Theme.of(context).brightness == Brightness.dark;
    return isDark ? dark : light;
  }

  /// THE app scheme. v2 is single-theme: the old pale/cream light values are
  /// gone, not toggled away from.
  ///
  /// Contrast, measured against the shell (#0B1B2B):
  ///   white on shell        17.41:1  -> body text
  ///   vibrant on shell       9.84:1  -> safe for text-weight accents
  ///   slate  on shell        3.72:1  -> LARGE / UI ONLY, never body text
  ///   shell  on paperCenter  4.74:1  -> ticket ink
  ///   vibrant on paperCenter 2.08:1  -> FAILS; never put vibrant on a ticket
  static const AppColorScheme v2 = AppColorScheme(
    background: contrastDark,
    surface: Color(0xFF122436),
    surfaceAlt: Color(0xFF1B3247),
    ink: Color(0xFFEAF4FA),
    // 7.4:1 on the shell — readable secondary text, unlike slate.
    inkSoft: Color(0xFF9FB8C9),
    // Vibrant is the SINGLE accent: active states and focal highlights only.
    // Dark text on it reads at 9.84:1, so it is safe as a button fill.
    primary: contrastVibrant,
    onPrimary: contrastDark,
    // Slate is the secondary, deliberately quieter so two accents never
    // compete. White on slate is 4.68:1, so filled slate can carry a label.
    accent: contrastSlate,
    onAccent: Color(0xFFFFFFFF),
    border: Color(0xFFEAF4FA),
    shadow: Color(0xFF000000),
  );

  /// Both aliases point at [v2]. Kept so existing `AppColors.light` /
  /// `AppColors.dark` call sites keep compiling while the app is single-theme —
  /// flipping the system toggle now changes nothing, by design.
  static const AppColorScheme light = v2;

  static const AppColorScheme dark = v2;
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
