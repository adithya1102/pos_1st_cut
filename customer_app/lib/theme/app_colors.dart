import 'package:flutter/material.dart';

/// Neobrutalist + retro-diner palette for CareVo Skip.
///
/// The app is SINGLE-THEME and that single theme is LIGHT. The v2 prototype
/// (`design/CareVo Skip v2.dc.html`) is drawn entirely in light values — warm
/// white screens, white cards, near-black borders with hard offset shadows —
/// and the app now matches it rather than re-interpreting it.
///
/// An earlier iteration shipped a dark shell (navy #0B1B2B + cyan accent). It
/// was rejected on review: it is gone, not toggled away from. `AppColors.light`
/// and `AppColors.dark` are both aliases of the one scheme so every existing
/// call site keeps compiling, and flipping the platform toggle changes nothing.
class AppColors {
  AppColors._();

  // ---- Brand constants --------------------------------------------------
  /// Wordmark / link purple. Deeper than [purple] so it stays legible as TEXT
  /// on the warm-white shell (10.65:1); [purple] is the button FILL.
  static const Color brand = Color(0xFF53089B);
  static const Color purple = Color(0xFF6B2FB3);
  static const Color purpleDeep = Color(0xFF4C1D86);

  /// Mint pair: [mint] fills chips and secondary buttons, [mintDeep] the
  /// stronger "View menu" / status pills.
  static const Color mint = Color(0xFFAAF2CA);
  static const Color mintDeep = Color(0xFF8FD6B0);

  /// Green used for text ON mint (the prototype's chip label colour).
  static const Color mintInk = Color(0xFF2A7151);

  static const Color cream = Color(0xFFF6EFE2);
  static const Color creamDim = Color(0xFFEDE3CF);

  /// Border/shadow ink. Every hard shadow and 2-3px border in the system.
  static const Color ink = Color(0xFF171512);

  /// Warm white the screens are painted on, and the white of a card.
  static const Color paper = Color(0xFFFFF8F3);
  static const Color paperCool = Color(0xFFF9F9F7);

  // Accents used for status / feedback.
  static const Color sunny = Color(0xFFF4C542);
  static const Color tomato = Color(0xFFE2603A);
  static const Color sky = Color(0xFF7FB3E8);

  /// Resolve the role-based scheme for the active brightness.
  ///
  /// Single-theme, so this always returns [v2]. Kept as a lookup so call sites
  /// read uniformly and a future variant needs no screen-level edits.
  static AppColorScheme of(BuildContext context) => v2;

  /// THE app scheme.
  ///
  /// Contrast, measured against the shell (#FFF8F3):
  ///   ink      on shell   16.34:1  -> body text
  ///   inkSoft  on shell    8.87:1  -> secondary text
  ///   brand    on shell   10.65:1  -> links, wordmark
  ///   white    on primary  7.83:1  -> primary button label
  ///   ink      on accent  13.31:1  -> mint chips and secondary buttons
  static const AppColorScheme v2 = AppColorScheme(
    // Warm white, not pure white: pure white next to the cream ticket stock
    // reads as two different kinds of "unpainted" rather than one surface.
    background: paper,
    surface: Color(0xFFFFFFFF),
    // The muted band behind +91 tags, image placeholders and inset rows.
    surfaceAlt: Color(0xFFEDE7E2),
    ink: Color(0xFF1D1B18),
    inkSoft: Color(0xFF4B4453),
    // Purple is the primary FILL; white on it reads at 7.83:1.
    primary: purple,
    onPrimary: Color(0xFFFFFFFF),
    // Mint is the secondary fill. It is deliberately never a text colour —
    // mint type on any pale surface is unreadable (see palette_test).
    accent: mint,
    onAccent: Color(0xFF1D1B18),
    border: ink,
    shadow: ink,
  );

  /// Both aliases point at [v2]. Kept so existing `AppColors.light` /
  /// `AppColors.dark` call sites keep compiling while the app is single-theme.
  static const AppColorScheme light = v2;

  static const AppColorScheme dark = v2;
}

/// Role-based color set consumed by widgets so every screen pulls the same
/// values rather than hard-coding hexes.
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
