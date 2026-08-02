import 'package:flutter/foundation.dart' show kDebugMode;
import 'package:flutter/material.dart';
import 'package:flutter/services.dart';
import 'package:provider/provider.dart';

import '../config/app_config.dart';
import '../state/auth_state.dart';
import '../theme/app_colors.dart';
import '../theme/widgets/neo_button.dart';
import '../theme/widgets/neo_card.dart';
import '../theme/widgets/neo_text_field.dart';
import 'location_screen.dart';

/// Step 2b: OTP entry. Dev code is `000000` (see AppConfig.devOtpCode).
class OtpScreen extends StatefulWidget {
  const OtpScreen({super.key});

  @override
  State<OtpScreen> createState() => _OtpScreenState();
}

class _OtpScreenState extends State<OtpScreen> {
  final _controller = TextEditingController();
  bool get _valid => _controller.text.trim().length == 6;

  @override
  void dispose() {
    _controller.dispose();
    super.dispose();
  }

  /// DEBUG-ONLY shortcut: auto-fill the stub code and verify. Compiled out of
  /// release builds by the `kDebugMode` guards on its call sites.
  Future<void> _skipDev() async {
    _controller.text = AppConfig.devOtpCode;
    setState(() {});
    await _verify();
  }

  Future<void> _verify() async {
    FocusScope.of(context).unfocus();
    final auth = context.read<AuthState>();
    final ok = await auth.verifyOtp(_controller.text.trim());
    if (!mounted) return;
    if (ok) {
      Navigator.of(context).pushAndRemoveUntil(
        MaterialPageRoute(builder: (_) => const LocationScreen()),
        (route) => false,
      );
    } else {
      ScaffoldMessenger.of(context).showSnackBar(
        SnackBar(content: Text(auth.error ?? 'Invalid code.')),
      );
    }
  }

  @override
  Widget build(BuildContext context) {
    final c = AppColors.of(context);
    final auth = context.watch<AuthState>();
    final textTheme = Theme.of(context).textTheme;

    return Scaffold(
      appBar: AppBar(),
      body: SafeArea(
        child: SingleChildScrollView(
          padding: const EdgeInsets.fromLTRB(20, 8, 20, 24),
          child: Column(
            crossAxisAlignment: CrossAxisAlignment.start,
            children: [
              const SizedBox(height: 12),
              Text('Verify\ncode.', style: textTheme.displaySmall),
              const SizedBox(height: 12),
              Text.rich(
                TextSpan(
                  style: textTheme.bodyLarge?.copyWith(color: c.inkSoft),
                  children: [
                    const TextSpan(text: 'We sent a 6-digit code to '),
                    TextSpan(
                      text: auth.pendingPhone,
                      style: textTheme.bodyLarge?.copyWith(
                        fontWeight: FontWeight.w700,
                        color: c.ink,
                      ),
                    ),
                    const TextSpan(text: '.'),
                  ],
                ),
              ),
              const SizedBox(height: 28),
              NeoCard(
                child: Column(
                  crossAxisAlignment: CrossAxisAlignment.start,
                  children: [
                    NeoTextField(
                      controller: _controller,
                      hintText: '000000',
                      keyboardType: TextInputType.number,
                      maxLength: 6,
                      autofocus: true,
                      textAlign: TextAlign.center,
                      inputFormatters: [FilteringTextInputFormatter.digitsOnly],
                      style: textTheme.displaySmall?.copyWith(letterSpacing: 12),
                      onChanged: (v) {
                        setState(() {});
                        if (v.trim().length == 6) _verify();
                      },
                    ),
                    const SizedBox(height: 20),
                    NeoButton(
                      label: 'Verify & Continue',
                      icon: Icons.check_circle_outline,
                      loading: auth.busy,
                      onPressed: _valid ? _verify : null,
                    ),
                    // DEBUG-ONLY: skip straight through with the stub code.
                    // Absent from release builds, and from Firebase builds
                    // where the stub code is not accepted.
                    if (kDebugMode && !AppConfig.useFirebaseAuth) ...[
                      const SizedBox(height: 12),
                      OutlinedButton.icon(
                        onPressed: auth.busy ? null : _skipDev,
                        icon: const Icon(Icons.fast_forward),
                        label: Text('Skip (dev · ${AppConfig.devOtpCode})'),
                      ),
                    ],
                  ],
                ),
              ),
              if (kDebugMode && !AppConfig.useFirebaseAuth) ...[
                const SizedBox(height: 18),
                Container(
                  padding: const EdgeInsets.all(12),
                  decoration: BoxDecoration(
                    color: c.surfaceAlt,
                    borderRadius: BorderRadius.circular(12),
                    border: Border.all(color: c.border, width: 2),
                  ),
                  child: Row(
                    children: [
                      Icon(Icons.info_outline, size: 18, color: c.inkSoft),
                      const SizedBox(width: 8),
                      Expanded(
                        child: Text(
                          'Dev build: use code ${AppConfig.devOtpCode} to sign in.',
                          style: textTheme.bodySmall,
                        ),
                      ),
                    ],
                  ),
                ),
              ],
              const SizedBox(height: 12),
              Center(
                child: TextButton(
                  onPressed: auth.busy
                      ? null
                      : () => context.read<AuthState>().requestOtp(auth.pendingPhone),
                  child: Text(
                    'Resend code',
                    style: textTheme.labelLarge?.copyWith(color: c.primary),
                  ),
                ),
              ),
            ],
          ),
        ),
      ),
    );
  }
}
