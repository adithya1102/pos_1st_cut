import 'package:flutter/material.dart';
import 'package:flutter/services.dart';
import 'package:google_fonts/google_fonts.dart';

import 'app_colors.dart';

/// Central theme factory. Bevan for display/headings, Space Grotesk for body.
/// Everything reads from [AppColors] so light + dark stay consistent.
class AppTheme {
  AppTheme._();

  // Neobrutalist geometry tokens.
  static const double radius = 14.0;
  static const double borderWidth = 3.0;
  static const Offset hardShadowOffset = Offset(4, 4);

  /// v2 is SINGLE-THEME and that theme is LIGHT. Both entry points build the
  /// same scheme at [Brightness.light], so the platform light/dark setting
  /// cannot produce a half-migrated look.
  static ThemeData light() => _build(AppColors.v2, Brightness.light);
  static ThemeData dark() => _build(AppColors.v2, Brightness.light);

  static ThemeData _build(AppColorScheme c, Brightness brightness) {
    final display = GoogleFonts.bevanTextTheme();
    final body = GoogleFonts.spaceGroteskTextTheme();

    final textTheme = TextTheme(
      displayLarge: display.displayLarge?.copyWith(color: c.ink, height: 1.05),
      displayMedium: display.displayMedium?.copyWith(color: c.ink, height: 1.05),
      displaySmall: display.displaySmall?.copyWith(color: c.ink, height: 1.1),
      headlineLarge: display.headlineLarge?.copyWith(color: c.ink),
      headlineMedium: display.headlineMedium?.copyWith(color: c.ink),
      headlineSmall: display.headlineSmall?.copyWith(color: c.ink),
      titleLarge: body.titleLarge?.copyWith(
        color: c.ink,
        fontWeight: FontWeight.w700,
      ),
      titleMedium: body.titleMedium?.copyWith(
        color: c.ink,
        fontWeight: FontWeight.w600,
      ),
      titleSmall: body.titleSmall?.copyWith(
        color: c.ink,
        fontWeight: FontWeight.w600,
      ),
      bodyLarge: body.bodyLarge?.copyWith(color: c.ink),
      bodyMedium: body.bodyMedium?.copyWith(color: c.ink),
      bodySmall: body.bodySmall?.copyWith(color: c.inkSoft),
      labelLarge: body.labelLarge?.copyWith(
        color: c.ink,
        fontWeight: FontWeight.w700,
        letterSpacing: 0.4,
      ),
    );

    final colorScheme = ColorScheme(
      brightness: brightness,
      primary: c.primary,
      onPrimary: c.onPrimary,
      secondary: c.accent,
      onSecondary: c.onAccent,
      // The prototype's error pair. Material's own error surfaces (form
      // validation, error icons) use these; the chunky danger BUTTON keeps
      // AppColors.tomato, see NeoButton.
      error: const Color(0xFF93000A),
      onError: const Color(0xFFFFFFFF),
      surface: c.surface,
      onSurface: c.ink,
    );

    return ThemeData(
      useMaterial3: true,
      brightness: brightness,
      colorScheme: colorScheme,
      scaffoldBackgroundColor: c.background,
      canvasColor: c.background,
      textTheme: textTheme,
      appBarTheme: AppBarTheme(
        backgroundColor: c.background,
        surfaceTintColor: Colors.transparent,
        elevation: 0,
        centerTitle: false,
        // Stated rather than inferred. Flutter would derive this from the app
        // bar's brightness, but OEM shells disagree about that derivation, and
        // guessing wrong paints white status-bar icons onto a warm-white bar.
        systemOverlayStyle: const SystemUiOverlayStyle(
          statusBarColor: Colors.transparent,
          statusBarIconBrightness: Brightness.dark,
          statusBarBrightness: Brightness.light,
        ),
        iconTheme: IconThemeData(color: c.ink),
        titleTextStyle: GoogleFonts.bevan(
          color: c.ink,
          fontSize: 20,
        ),
      ),
      dividerColor: c.border,
      iconTheme: IconThemeData(color: c.ink),
      snackBarTheme: SnackBarThemeData(
        backgroundColor: c.ink,
        contentTextStyle: GoogleFonts.spaceGrotesk(color: c.background),
        behavior: SnackBarBehavior.floating,
      ),
      progressIndicatorTheme: ProgressIndicatorThemeData(color: c.primary),
    );
  }
}
