import 'package:flutter/material.dart';
import 'package:provider/provider.dart';

import '../state/auth_state.dart';

/// Completes the forgot-password flow: the owner types the code from the reset
/// email and chooses a new password.
///
/// ## Why a typed code rather than a tapped link
/// The reset mail carries the raw single-use token. Consuming it from a tapped
/// link would need either a web landing page or Android/iOS deep-link
/// association — neither exists, and both are deployment work rather than app
/// work. A typed code needs neither and works on a phone whose mail app opens
/// links in a browser that knows nothing about this account.
///
/// Until this screen existed there was NO caller of POST /auth/password/reset
/// anywhere in the app: the server minted tokens that nothing could redeem, so
/// forgot-password could not complete however the mail was delivered.
class ResetPasswordScreen extends StatefulWidget {
  const ResetPasswordScreen({super.key, this.emailHint});

  /// Masked address the code was sent to, carried over from the previous screen
  /// so the owner knows which inbox to open. Null when unknown.
  final String? emailHint;

  static const codeKey = Key('reset_code');
  static const passwordKey = Key('reset_new_password');
  static const confirmKey = Key('reset_confirm_password');
  static const submitKey = Key('reset_submit');

  @override
  State<ResetPasswordScreen> createState() => _ResetPasswordScreenState();
}

class _ResetPasswordScreenState extends State<ResetPasswordScreen> {
  final _formKey = GlobalKey<FormState>();
  final _code = TextEditingController();
  final _password = TextEditingController();
  final _confirm = TextEditingController();

  bool _submitting = false;
  bool _obscure = true;
  String? _error;

  /// Mirrors MIN_PASSWORD_LENGTH in the backend's AccountService. Checked here
  /// too so a too-short password is caught before a round trip.
  static const _minPasswordLength = 8;

  @override
  void dispose() {
    _code.dispose();
    _password.dispose();
    _confirm.dispose();
    super.dispose();
  }

  Future<void> _submit() async {
    FocusScope.of(context).unfocus();
    if (!(_formKey.currentState?.validate() ?? false)) return;

    setState(() {
      _submitting = true;
      _error = null;
    });

    final err = await context.read<AuthState>().resetPassword(
          token: _code.text,
          newPassword: _password.text,
        );

    if (!mounted) return;
    setState(() {
      _submitting = false;
      _error = err;
    });

    if (err != null) return;

    // Raised BEFORE popping, against MaterialApp's root ScaffoldMessenger, so
    // it survives this route going away.
    ScaffoldMessenger.of(context)
      ..hideCurrentSnackBar()
      ..showSnackBar(const SnackBar(
        content: Text('Password reset. Sign in with your new password.'),
      ));

    // Hands `true` back to ForgotPasswordScreen, which closes itself in turn so
    // the owner lands on login with a password that now works.
    //
    // maybePop, and one level only: popping a fixed number of routes assumed a
    // stack shape this screen cannot see. Pushed from anywhere else — or opened
    // as the first route — it must still not throw.
    await Navigator.of(context).maybePop(true);
  }

  @override
  Widget build(BuildContext context) {
    final theme = Theme.of(context);
    final hint = widget.emailHint;

    return Scaffold(
      appBar: AppBar(title: const Text('Enter reset code')),
      body: SafeArea(
        child: Center(
          child: SingleChildScrollView(
            padding: const EdgeInsets.all(24),
            child: ConstrainedBox(
              constraints: const BoxConstraints(maxWidth: 420),
              child: Form(
                key: _formKey,
                child: Column(
                  crossAxisAlignment: CrossAxisAlignment.stretch,
                  children: [
                    Text(
                      hint == null
                          ? 'Paste the code from the reset email, then choose a '
                              'new password.'
                          : 'Paste the code we sent to $hint, then choose a new '
                              'password.',
                      style: theme.textTheme.bodyMedium,
                    ),
                    const SizedBox(height: 4),
                    Text(
                      'The code expires in 30 minutes and works once.',
                      style: theme.textTheme.bodySmall
                          ?.copyWith(color: theme.colorScheme.outline),
                    ),
                    const SizedBox(height: 20),
                    TextFormField(
                      key: ResetPasswordScreen.codeKey,
                      controller: _code,
                      autocorrect: false,
                      enableSuggestions: false,
                      decoration: const InputDecoration(
                        labelText: 'Reset code',
                        prefixIcon: Icon(Icons.key_outlined),
                      ),
                      validator: (v) => (v == null || v.trim().isEmpty)
                          ? 'Paste the code from the email'
                          : null,
                    ),
                    const SizedBox(height: 16),
                    TextFormField(
                      key: ResetPasswordScreen.passwordKey,
                      controller: _password,
                      obscureText: _obscure,
                      decoration: InputDecoration(
                        labelText: 'New password',
                        prefixIcon: const Icon(Icons.lock_outline),
                        suffixIcon: IconButton(
                          icon: Icon(_obscure
                              ? Icons.visibility_outlined
                              : Icons.visibility_off_outlined),
                          onPressed: () =>
                              setState(() => _obscure = !_obscure),
                        ),
                      ),
                      validator: (v) => (v == null || v.length < _minPasswordLength)
                          ? 'At least $_minPasswordLength characters'
                          : null,
                    ),
                    const SizedBox(height: 16),
                    TextFormField(
                      key: ResetPasswordScreen.confirmKey,
                      controller: _confirm,
                      obscureText: _obscure,
                      decoration: const InputDecoration(
                        labelText: 'Confirm new password',
                        prefixIcon: Icon(Icons.lock_outline),
                      ),
                      validator: (v) =>
                          v == _password.text ? null : 'Passwords do not match',
                      onFieldSubmitted: (_) => _submit(),
                    ),
                    const SizedBox(height: 24),
                    FilledButton(
                      key: ResetPasswordScreen.submitKey,
                      onPressed: _submitting ? null : _submit,
                      child: _submitting
                          ? const SizedBox(
                              height: 18,
                              width: 18,
                              child: CircularProgressIndicator(strokeWidth: 2),
                            )
                          : const Text('Set new password'),
                    ),
                    if (_error != null) ...[
                      const SizedBox(height: 20),
                      Text(_error!,
                          style: TextStyle(color: theme.colorScheme.error)),
                    ],
                  ],
                ),
              ),
            ),
          ),
        ),
      ),
    );
  }
}
