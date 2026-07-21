import 'package:flutter/material.dart';
import 'package:google_fonts/google_fonts.dart';
import 'package:provider/provider.dart';

import '../config/app_config.dart';
import '../state/auth_state.dart';
import '../theme/app_colors.dart';
import '../theme/app_theme.dart';
import 'location_screen.dart';
import 'login_screen.dart';

/// Splash / theme-init gate. Decides the entry screen based on session.
class SplashScreen extends StatefulWidget {
  const SplashScreen({super.key});

  @override
  State<SplashScreen> createState() => _SplashScreenState();
}

class _SplashScreenState extends State<SplashScreen> {
  @override
  void initState() {
    super.initState();
    _boot();
  }

  Future<void> _boot() async {
    // Brief branded pause; theme + token are already loaded in main().
    await Future<void>.delayed(const Duration(milliseconds: 900));
    if (!mounted) return;
    final authed = context.read<AuthState>().isAuthenticated;
    Navigator.of(context).pushReplacement(
      MaterialPageRoute(
        builder: (_) => authed ? const LocationScreen() : const LoginScreen(),
      ),
    );
  }

  @override
  Widget build(BuildContext context) {
    final c = AppColors.of(context);
    return Scaffold(
      backgroundColor: c.primary,
      body: Center(
        child: Column(
          mainAxisSize: MainAxisSize.min,
          children: [
            Container(
              padding: const EdgeInsets.symmetric(horizontal: 26, vertical: 20),
              decoration: BoxDecoration(
                color: c.accent,
                borderRadius: BorderRadius.circular(AppTheme.radius),
                border: Border.all(color: c.border, width: AppTheme.borderWidth),
                boxShadow: [
                  BoxShadow(color: c.shadow, offset: const Offset(5, 5), blurRadius: 0),
                ],
              ),
              child: Text(
                'CareVo',
                style: GoogleFonts.bevan(color: c.onAccent, fontSize: 44),
              ),
            ),
            const SizedBox(height: 18),
            Text(
              'SKIP THE LINE',
              style: GoogleFonts.spaceGrotesk(
                color: c.onPrimary,
                fontSize: 16,
                fontWeight: FontWeight.w700,
                letterSpacing: 4,
              ),
            ),
            const SizedBox(height: 40),
            SizedBox(
              width: 28,
              height: 28,
              child: CircularProgressIndicator(color: c.onPrimary, strokeWidth: 3),
            ),
            const SizedBox(height: 40),
            Text(
              AppConfig.appName,
              style: GoogleFonts.spaceGrotesk(
                color: c.onPrimary.withValues(alpha: 0.7),
                fontSize: 12,
              ),
            ),
          ],
        ),
      ),
    );
  }
}
