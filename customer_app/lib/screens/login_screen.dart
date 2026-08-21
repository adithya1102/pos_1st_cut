import 'package:flutter/material.dart';
import 'package:flutter/services.dart';
import 'package:provider/provider.dart';

import '../state/auth_state.dart';
import '../theme/app_colors.dart';
import '../theme/app_theme.dart';
import '../theme/widgets/neo_button.dart';
import '../theme/widgets/neo_card.dart';
import '../theme/widgets/neo_text_field.dart';
import 'location_screen.dart';
import 'otp_screen.dart';

/// Step 2 of the flow: mobile number entry to request an OTP.
///
/// v2 layout (prototype screen 01): no app bar — the auth screens are the only
/// ones without the app chrome — a centred wordmark, then one card holding both
/// sign-in routes. The card is vertically centred so the whole screen reads as a
/// single object rather than a form pinned under a header.
class LoginScreen extends StatefulWidget {
  const LoginScreen({super.key});

  @override
  State<LoginScreen> createState() => _LoginScreenState();
}

class _LoginScreenState extends State<LoginScreen> {
  final _controller = TextEditingController();
  bool get _valid => _controller.text.trim().length == 10;

  @override
  void dispose() {
    _controller.dispose();
    super.dispose();
  }

  Future<void> _submit() async {
    FocusScope.of(context).unfocus();
    final phone = '+91${_controller.text.trim()}';
    final auth = context.read<AuthState>();
    final ok = await auth.requestOtp(phone);
    if (!mounted) return;
    if (ok) {
      Navigator.of(context).push(
        MaterialPageRoute(builder: (_) => const OtpScreen()),
      );
    } else {
      ScaffoldMessenger.of(context).showSnackBar(
        SnackBar(content: Text(auth.error ?? 'Could not send OTP.')),
      );
    }
  }

  /// Google is a standalone identity: it skips the OTP step entirely and lands
  /// straight on the location screen, exactly where a verified OTP lands.
  Future<void> _google() async {
    FocusScope.of(context).unfocus();
    final auth = context.read<AuthState>();
    final ok = await auth.signInWithGoogle();
    if (!mounted) return;
    if (ok) {
      Navigator.of(context).pushAndRemoveUntil(
        MaterialPageRoute(builder: (_) => const LocationScreen()),
        (route) => false,
      );
    } else if (auth.error != null) {
      // A plain cancel leaves error null and should stay silent.
      ScaffoldMessenger.of(context).showSnackBar(
        SnackBar(content: Text(auth.error!)),
      );
    }
  }

  @override
  Widget build(BuildContext context) {
    final c = AppColors.of(context);
    final auth = context.watch<AuthState>();
    final textTheme = Theme.of(context).textTheme;

    return Scaffold(
      body: SafeArea(
        child: LayoutBuilder(
          builder: (context, constraints) => SingleChildScrollView(
            padding: const EdgeInsets.fromLTRB(20, 24, 20, 30),
            child: ConstrainedBox(
              // Centres the card on a tall screen but lets it scroll normally
              // once the keyboard is up, instead of overflowing.
              constraints: BoxConstraints(minHeight: constraints.maxHeight - 54),
              child: Column(
                mainAxisAlignment: MainAxisAlignment.center,
                crossAxisAlignment: CrossAxisAlignment.stretch,
                children: [
                  Text(
                    'CareVo Skip',
                    textAlign: TextAlign.center,
                    style: textTheme.headlineMedium?.copyWith(
                      color: AppColors.brand,
                      letterSpacing: -0.5,
                    ),
                  ),
                  const SizedBox(height: 8),
                  Text(
                    'Skip the queue.',
                    textAlign: TextAlign.center,
                    style: textTheme.titleMedium?.copyWith(color: c.inkSoft),
                  ),
                  const SizedBox(height: 28),
                  NeoCard(
                    padding: const EdgeInsets.all(22),
                    child: Column(
                      crossAxisAlignment: CrossAxisAlignment.start,
                      children: [
                        Text('Welcome back', style: textTheme.titleLarge),
                        const SizedBox(height: 18),
                        Text(
                          'Phone number',
                          style: textTheme.labelLarge?.copyWith(color: c.ink),
                        ),
                        const SizedBox(height: 6),
                        Row(
                          children: [
                            const _CountryTag(),
                            const SizedBox(width: 10),
                            Expanded(
                              child: NeoTextField(
                                // Stable driver target — see integration_test/.
                                key: const Key('login_phone_field'),
                                controller: _controller,
                                // Instructional, not a specimen number. A
                                // realistic-looking placeholder reads as a
                                // pre-filled value at a glance — people tap
                                // "continue" on it, or try to delete digits
                                // that were never there.
                                hintText: 'Enter mobile number',
                                keyboardType: TextInputType.phone,
                                maxLength: 10,
                                inputFormatters: [
                                  FilteringTextInputFormatter.digitsOnly,
                                ],
                                onChanged: (_) => setState(() {}),
                                onSubmitted: (_) => _valid ? _submit() : null,
                              ),
                            ),
                          ],
                        ),
                        const SizedBox(height: 20),
                        NeoButton(
                          key: const Key('login_send_otp'),
                          label: 'Send OTP',
                          icon: Icons.send,
                          loading: auth.busy,
                          onPressed: _valid ? _submit : null,
                        ),
                        const SizedBox(height: 20),
                        Row(
                          children: [
                            Expanded(child: _Rule(color: c.border)),
                            Padding(
                              padding: const EdgeInsets.symmetric(horizontal: 14),
                              child: Text(
                                'OR',
                                style: textTheme.labelLarge
                                    ?.copyWith(color: c.inkSoft),
                              ),
                            ),
                            Expanded(child: _Rule(color: c.border)),
                          ],
                        ),
                        const SizedBox(height: 20),
                        NeoButton(
                          label: 'Continue with Google',
                          icon: Icons.account_circle_outlined,
                          // Mint, not the purple primary: the prototype gives
                          // phone entry the single loud action and keeps Google
                          // visually secondary to it.
                          variant: NeoButtonVariant.accent,
                          loading: auth.busy,
                          onPressed: auth.busy ? null : _google,
                        ),
                        const SizedBox(height: 18),
                        Text(
                          'We use your number only to hold your order and show '
                          'your pickup code.',
                          textAlign: TextAlign.center,
                          style: textTheme.bodySmall?.copyWith(color: c.inkSoft),
                        ),
                      ],
                    ),
                  ),
                ],
              ),
            ),
          ),
        ),
      ),
    );
  }
}

/// The fixed "+91" prefix. Butts against the number field with a shared border
/// so the two read as one control, the way the prototype draws it.
class _CountryTag extends StatelessWidget {
  const _CountryTag();

  @override
  Widget build(BuildContext context) {
    final c = AppColors.of(context);
    return Container(
      padding: const EdgeInsets.symmetric(horizontal: 14, vertical: 18),
      decoration: BoxDecoration(
        color: c.surfaceAlt,
        borderRadius: BorderRadius.circular(AppTheme.radius),
        border: Border.all(color: c.border, width: AppTheme.borderWidth),
        boxShadow: [
          BoxShadow(color: c.shadow, offset: const Offset(3, 3), blurRadius: 0),
        ],
      ),
      child: Text(
        '+91',
        style: Theme.of(context)
            .textTheme
            .titleMedium
            ?.copyWith(fontWeight: FontWeight.w700),
      ),
    );
  }
}

/// The solid 2px rule either side of "OR".
class _Rule extends StatelessWidget {
  const _Rule({required this.color});
  final Color color;

  @override
  Widget build(BuildContext context) => Container(height: 2, color: color);
}
