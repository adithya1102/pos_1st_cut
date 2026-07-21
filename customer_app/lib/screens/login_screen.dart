import 'package:flutter/material.dart';
import 'package:flutter/services.dart';
import 'package:provider/provider.dart';

import '../state/auth_state.dart';
import '../theme/app_colors.dart';
import '../theme/widgets/neo_button.dart';
import '../theme/widgets/neo_card.dart';
import '../theme/widgets/neo_text_field.dart';
import '../widgets/theme_toggle_button.dart';
import 'otp_screen.dart';

/// Step 2 of the flow: mobile number entry to request an OTP.
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

  @override
  Widget build(BuildContext context) {
    final c = AppColors.of(context);
    final auth = context.watch<AuthState>();
    final textTheme = Theme.of(context).textTheme;

    return Scaffold(
      appBar: AppBar(
        actions: const [
          Padding(padding: EdgeInsets.only(right: 16), child: ThemeToggleButton()),
        ],
      ),
      body: SafeArea(
        child: SingleChildScrollView(
          padding: const EdgeInsets.fromLTRB(20, 8, 20, 24),
          child: Column(
            crossAxisAlignment: CrossAxisAlignment.start,
            children: [
              const SizedBox(height: 12),
              Text('Skip the\nline.', style: textTheme.displaySmall),
              const SizedBox(height: 12),
              Text(
                'Order ahead, pay online, and pick up your food without waiting.',
                style: textTheme.bodyLarge?.copyWith(color: c.inkSoft),
              ),
              const SizedBox(height: 32),
              NeoCard(
                child: Column(
                  crossAxisAlignment: CrossAxisAlignment.start,
                  children: [
                    Text('Enter your mobile number', style: textTheme.titleMedium),
                    const SizedBox(height: 16),
                    Row(
                      children: [
                        _CountryTag(color: c.surfaceAlt, border: c.border),
                        const SizedBox(width: 10),
                        Expanded(
                          child: NeoTextField(
                            controller: _controller,
                            hintText: '98765 43210',
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
                      label: 'Send OTP',
                      icon: Icons.sms_outlined,
                      loading: auth.busy,
                      onPressed: _valid ? _submit : null,
                    ),
                  ],
                ),
              ),
              const SizedBox(height: 20),
              Text(
                'By continuing you agree to receive a one-time verification code.',
                style: textTheme.bodySmall,
              ),
            ],
          ),
        ),
      ),
    );
  }
}

class _CountryTag extends StatelessWidget {
  const _CountryTag({required this.color, required this.border});
  final Color color;
  final Color border;

  @override
  Widget build(BuildContext context) {
    return Container(
      padding: const EdgeInsets.symmetric(horizontal: 14, vertical: 18),
      decoration: BoxDecoration(
        color: color,
        borderRadius: BorderRadius.circular(14),
        border: Border.all(color: border, width: 3),
        boxShadow: [
          BoxShadow(color: border, offset: const Offset(3, 3), blurRadius: 0),
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
