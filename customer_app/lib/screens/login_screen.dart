import 'package:flutter/material.dart';
import 'package:flutter/services.dart';
import 'package:provider/provider.dart';

import '../state/auth_state.dart';
import '../theme/app_colors.dart';
import '../theme/app_theme.dart';
import '../theme/widgets/neo_button.dart';
import '../theme/widgets/neo_card.dart';
import '../theme/widgets/neo_text_field.dart';
import 'otp_screen.dart';
import 'post_auth_router.dart';

/// `98765 43210`, `+91 98765 43210`, `09876543210` -> `+919876543210`.
/// Returns null when [raw] is not a usable Indian mobile number.
///
/// Still accepts the prefixed forms even though the field carries a fixed `+91`
/// tag again: people paste numbers in whatever shape they already have them,
/// and silently rejecting a pasted `+91…` would look like the field is broken.
String? normalisePhone(String raw) {
  // Formatting characters people actually paste.
  var digits = raw.replaceAll(RegExp(r'[\s\-().]'), '');
  if (digits.startsWith('+91')) {
    digits = digits.substring(3);
  } else if (digits.length == 12 && digits.startsWith('91')) {
    digits = digits.substring(2);
  } else if (digits.length == 11 && digits.startsWith('0')) {
    digits = digits.substring(1);
  }
  if (!RegExp(r'^\d{10}$').hasMatch(digits)) return null;
  return '+91$digits';
}

/// Step 1 of the flow: sign in with a phone number, or with Google.
///
/// v2 layout (prototype screen 01): no app bar — the auth screens are the only
/// ones without the app chrome — a centred wordmark, then one card holding the
/// sign-in routes. The card is vertically centred so the whole screen reads as a
/// single object rather than a form pinned under a header.
///
/// ## Two options, and no name field
///
/// The screen previously carried an identifier box that accepted a phone number
/// OR an email, plus a mandatory name field. Both are gone:
///
///  * **Email entry removed.** Typing an email only ever routed into the Google
///    picker, which then decides the account itself — so the typed address was
///    a hint that Google was free to ignore. Two ways to reach one flow, one of
///    which could disagree with the outcome. "Continue with Google" is the
///    honest single door, and the field is now unambiguously a phone number.
///  * **Name entry moved OFF this screen.** It is asked once, after signup, by
///    [NameCaptureScreen] — see [routeAfterAuth]. Collecting it here meant
///    every returning customer retyped a name they had already set, and it
///    forced a guess about whether that value should overwrite the stored one.
///    Asking after signup removes the guess: the only account that is asked is
///    one that does not have a name yet.
class LoginScreen extends StatefulWidget {
  const LoginScreen({super.key});

  @override
  State<LoginScreen> createState() => _LoginScreenState();
}

class _LoginScreenState extends State<LoginScreen> {
  final _controller = TextEditingController();

  /// Valid when the typed digits normalise to an Indian mobile number.
  bool get _valid => normalisePhone(_controller.text) != null;

  @override
  void dispose() {
    _controller.dispose();
    super.dispose();
  }

  Future<void> _submitPhone() async {
    FocusScope.of(context).unfocus();
    final phone = normalisePhone(_controller.text);
    if (phone == null) return;
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
  /// wherever [routeAfterAuth] decides — the name screen on a signup, Home on a
  /// returning sign-in.
  Future<void> _google() async {
    FocusScope.of(context).unfocus();
    final auth = context.read<AuthState>();
    final ok = await auth.signInWithGoogle();
    if (!mounted) return;
    if (ok) {
      routeAfterAuth(context, isNewAccount: auth.lastSignInWasNewAccount);
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
                    'Gusto Skip',
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
                            // Permanent again now the field is phone-only. It
                            // was conditional while the box also took emails.
                            const _CountryTag(),
                            const SizedBox(width: 10),
                            Expanded(
                              child: NeoTextField(
                                // Stable driver target — see integration_test/.
                                key: const Key('login_phone_field'),
                                controller: _controller,
                                // Instructional, not a specimen. A realistic
                                // placeholder reads as a pre-filled value at a
                                // glance — people tap "continue" on it, or try
                                // to delete digits that were never there.
                                hintText: 'Phone number',
                                keyboardType: TextInputType.phone,
                                maxLength: 10,
                                inputFormatters: [
                                  FilteringTextInputFormatter.digitsOnly,
                                ],
                                onChanged: (_) => setState(() {}),
                                onSubmitted: (_) =>
                                    _valid ? _submitPhone() : null,
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
                          onPressed: _valid ? _submitPhone : null,
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
                          key: const Key('login_google'),
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
