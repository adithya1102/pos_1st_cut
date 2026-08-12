import 'package:flutter/foundation.dart' show kDebugMode;
import 'package:flutter/material.dart';
import 'package:flutter/services.dart';
import 'package:provider/provider.dart';

import '../config/app_config.dart';
import '../state/auth_state.dart';
import '../theme/app_colors.dart';
import '../theme/app_theme.dart';
import '../theme/widgets/neo_button.dart';
import '../theme/widgets/neo_icon_button.dart';
import 'location_screen.dart';

/// Step 2b: OTP entry. Dev code is `000000` (see AppConfig.devOtpCode).
///
/// v2 layout (prototype screen 02): no app bar, a back chip, and the code shown
/// as six bordered cells.
///
/// DELIBERATELY NOT BUILT: the prototype's in-app numeric keypad. It was
/// rejected — Android's system keyboard is what carries SMS one-time-code
/// autofill, and a custom keypad forfeits it, making the OTP step slower rather
/// than faster. The six cells here are a PRESENTATION of a real, focusable
/// TextField (transparent, sitting under the cells) so the system keyboard and
/// [AutofillHints.oneTimeCode] keep working exactly as before.
class OtpScreen extends StatefulWidget {
  const OtpScreen({super.key});

  @override
  State<OtpScreen> createState() => _OtpScreenState();
}

class _OtpScreenState extends State<OtpScreen> {
  final _controller = TextEditingController();
  final _focus = FocusNode();
  bool get _valid => _controller.text.trim().length == 6;

  @override
  void dispose() {
    _controller.dispose();
    _focus.dispose();
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
      body: SafeArea(
        child: SingleChildScrollView(
          padding: const EdgeInsets.fromLTRB(20, 20, 20, 24),
          child: Column(
            crossAxisAlignment: CrossAxisAlignment.start,
            children: [
              NeoIconButton(
                icon: Icons.arrow_back,
                tooltip: 'Back',
                onPressed: () => Navigator.of(context).maybePop(),
              ),
              const SizedBox(height: 18),
              Text('Verify your number', style: textTheme.headlineSmall),
              const SizedBox(height: 6),
              Text.rich(
                TextSpan(
                  style: textTheme.bodyLarge?.copyWith(color: c.inkSoft),
                  children: [
                    const TextSpan(text: '6-digit code sent to '),
                    TextSpan(
                      text: auth.pendingPhone,
                      style: textTheme.bodyLarge?.copyWith(
                        fontWeight: FontWeight.w700,
                        color: c.ink,
                      ),
                    ),
                  ],
                ),
              ),
              const SizedBox(height: 22),
              _OtpCells(
                controller: _controller,
                focusNode: _focus,
                onChanged: (v) {
                  setState(() {});
                  if (v.trim().length == 6) _verify();
                },
              ),
              const SizedBox(height: 22),
              NeoButton(
                key: const Key('otp_verify'),
                label: 'Verify & continue',
                icon: Icons.check_circle_outline,
                loading: auth.busy,
                onPressed: _valid ? _verify : null,
              ),
              // DEBUG-ONLY: skip straight through with the stub code. Absent
              // from release builds, and from Firebase builds where the stub
              // code is not accepted.
              if (kDebugMode && !AppConfig.useFirebaseAuth) ...[
                const SizedBox(height: 12),
                OutlinedButton.icon(
                  onPressed: auth.busy ? null : _skipDev,
                  icon: const Icon(Icons.fast_forward),
                  label: Text('Skip (dev · ${AppConfig.devOtpCode})'),
                ),
                const SizedBox(height: 12),
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
              const SizedBox(height: 14),
              Center(
                child: TextButton(
                  onPressed: auth.busy
                      ? null
                      : () =>
                          context.read<AuthState>().requestOtp(auth.pendingPhone),
                  child: Text(
                    'Resend code',
                    style: textTheme.labelLarge?.copyWith(color: AppColors.brand),
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

/// Six bordered cells that display a real TextField's value.
///
/// The field itself is transparent and stretched across the cells rather than
/// hidden off-screen: it stays hit-testable, so a tap anywhere on the row opens
/// the system keyboard, and it stays a genuine autofill target for the incoming
/// SMS. Six separate one-character fields — the other common approach — break
/// one-time-code autofill, which fills a single field.
class _OtpCells extends StatelessWidget {
  const _OtpCells({
    required this.controller,
    required this.focusNode,
    required this.onChanged,
  });

  final TextEditingController controller;
  final FocusNode focusNode;
  final ValueChanged<String> onChanged;

  static const int _length = 6;

  @override
  Widget build(BuildContext context) {
    final c = AppColors.of(context);
    final textTheme = Theme.of(context).textTheme;

    return AutofillGroup(
      child: Stack(
        children: [
          AnimatedBuilder(
            animation: Listenable.merge([controller, focusNode]),
            builder: (context, _) {
              final value = controller.text;
              return Row(
                children: List.generate(_length, (i) {
                  final filled = i < value.length;
                  // The cell the next character lands in, highlighted only
                  // while the keyboard is actually up.
                  final isNext = focusNode.hasFocus && i == value.length;
                  return Expanded(
                    child: Padding(
                      padding: EdgeInsets.only(right: i == _length - 1 ? 0 : 8),
                      child: Container(
                        height: 58,
                        alignment: Alignment.center,
                        decoration: BoxDecoration(
                          color: isNext ? c.accent : c.surface,
                          borderRadius:
                              BorderRadius.circular(AppTheme.radius - 4),
                          border: Border.all(
                            color: c.border,
                            width: AppTheme.borderWidth,
                          ),
                          boxShadow: [
                            BoxShadow(
                              color: c.shadow,
                              offset: const Offset(3, 3),
                              blurRadius: 0,
                            ),
                          ],
                        ),
                        child: Text(
                          filled ? value[i] : '',
                          style: textTheme.titleLarge?.copyWith(
                            fontSize: 24,
                            fontWeight: FontWeight.w800,
                          ),
                        ),
                      ),
                    ),
                  );
                }),
              );
            },
          ),
          Positioned.fill(
            child: TextField(
              key: const Key('otp_code_field'),
              controller: controller,
              focusNode: focusNode,
              autofocus: true,
              keyboardType: TextInputType.number,
              autofillHints: const [AutofillHints.oneTimeCode],
              maxLength: _length,
              inputFormatters: [FilteringTextInputFormatter.digitsOnly],
              onChanged: onChanged,
              showCursor: false,
              enableInteractiveSelection: false,
              // Invisible, but present: the cells above are the visible
              // rendering of this field's value.
              style: const TextStyle(color: Colors.transparent, fontSize: 24),
              decoration: const InputDecoration(
                counterText: '',
                border: InputBorder.none,
                focusedBorder: InputBorder.none,
                enabledBorder: InputBorder.none,
                contentPadding: EdgeInsets.zero,
              ),
            ),
          ),
        ],
      ),
    );
  }
}
