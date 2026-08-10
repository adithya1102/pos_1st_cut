import 'package:flutter/material.dart';
import 'package:provider/provider.dart';

import '../config/app_config.dart';
import '../state/auth_state.dart';
import 'forgot_password_screen.dart';
import 'signup_screen.dart';

class LoginScreen extends StatefulWidget {
  const LoginScreen({super.key});

  @override
  State<LoginScreen> createState() => _LoginScreenState();
}

class _LoginScreenState extends State<LoginScreen> {
  final _usernameController = TextEditingController();
  final _passwordController = TextEditingController();
  final _formKey = GlobalKey<FormState>();
  bool _obscure = true;

  @override
  void dispose() {
    _usernameController.dispose();
    _passwordController.dispose();
    super.dispose();
  }

  Future<void> _submit() async {
    FocusScope.of(context).unfocus();
    if (!(_formKey.currentState?.validate() ?? false)) return;
    final auth = context.read<AuthState>();
    await auth.login(_usernameController.text, _passwordController.text);
    // Navigation is handled by the root widget reacting to loggedIn.
  }

  @override
  Widget build(BuildContext context) {
    final auth = context.watch<AuthState>();

    return Scaffold(
      body: SafeArea(
        child: Center(
          child: SingleChildScrollView(
            padding: const EdgeInsets.all(24),
            child: ConstrainedBox(
              constraints: const BoxConstraints(maxWidth: 420),
              child: Form(
                key: _formKey,
                child: Column(
                  mainAxisSize: MainAxisSize.min,
                  crossAxisAlignment: CrossAxisAlignment.stretch,
                  children: [
                    const _Brand(),
                    const SizedBox(height: 32),
                    TextFormField(
                      controller: _usernameController,
                      textInputAction: TextInputAction.next,
                      autocorrect: false,
                      enableSuggestions: false,
                      decoration: const InputDecoration(
                        labelText: 'Username',
                        prefixIcon: Icon(Icons.person_outline),
                      ),
                      validator: (v) => (v == null || v.trim().isEmpty)
                          ? 'Enter your username'
                          : null,
                    ),
                    const SizedBox(height: 16),
                    TextFormField(
                      controller: _passwordController,
                      obscureText: _obscure,
                      textInputAction: TextInputAction.done,
                      onFieldSubmitted: (_) => _submit(),
                      decoration: InputDecoration(
                        labelText: 'Password',
                        prefixIcon: const Icon(Icons.lock_outline),
                        suffixIcon: IconButton(
                          icon: Icon(_obscure
                              ? Icons.visibility_outlined
                              : Icons.visibility_off_outlined),
                          onPressed: () =>
                              setState(() => _obscure = !_obscure),
                        ),
                      ),
                      validator: (v) => (v == null || v.isEmpty)
                          ? 'Enter your password'
                          : null,
                    ),
                    // Shown DURING the wait, not after it fails: a free-tier
                    // cold start takes 40-80s, and silence for that long reads
                    // as a broken app.
                    if (auth.loading && auth.wakingUp) ...[
                      const SizedBox(height: 16),
                      _Notice(
                        icon: Icons.hourglass_bottom,
                        color: Theme.of(context).colorScheme.tertiary,
                        text: 'Waking up the server — this can take up to a '
                            'minute on the first sign-in of the day.',
                      ),
                    ],
                    if (!auth.loading && auth.error != null) ...[
                      const SizedBox(height: 16),
                      _Notice(
                        // A wrong password and an unreachable server should not
                        // look alike at a glance, let alone read alike.
                        icon: switch (auth.failure) {
                          LoginFailure.badCredentials => Icons.lock_outline,
                          LoginFailure.network => Icons.wifi_off,
                          LoginFailure.timeout => Icons.hourglass_bottom,
                          _ => Icons.error_outline,
                        },
                        color: auth.failure == LoginFailure.timeout
                            ? Theme.of(context).colorScheme.tertiary
                            : Theme.of(context).colorScheme.error,
                        text: auth.error!,
                      ),
                    ],
                    const SizedBox(height: 24),
                    FilledButton(
                      onPressed: auth.loading ? null : _submit,
                      style: FilledButton.styleFrom(
                        padding: const EdgeInsets.symmetric(vertical: 16),
                      ),
                      child: auth.loading
                          ? const SizedBox(
                              height: 20,
                              width: 20,
                              child: CircularProgressIndicator(strokeWidth: 2),
                            )
                          : const Text('Log in'),
                    ),
                    const SizedBox(height: 4),
                    TextButton(
                      onPressed: auth.loading
                          ? null
                          : () => Navigator.of(context).push(
                                MaterialPageRoute(
                                    builder: (_) => const ForgotPasswordScreen()),
                              ),
                      child: const Text('Forgot password?'),
                    ),
                    const SizedBox(height: 4),
                    TextButton(
                      onPressed: auth.loading
                          ? null
                          : () => Navigator.of(context).push(
                                MaterialPageRoute(
                                    builder: (_) => const SignupScreen()),
                              ),
                      child: const Text('Register your restaurant'),
                    ),
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

/// One inline message with an icon that matches its cause.
class _Notice extends StatelessWidget {
  const _Notice({required this.icon, required this.color, required this.text});

  final IconData icon;
  final Color color;
  final String text;

  @override
  Widget build(BuildContext context) {
    return Row(
      crossAxisAlignment: CrossAxisAlignment.start,
      children: [
        Icon(icon, size: 18, color: color),
        const SizedBox(width: 8),
        Expanded(
          child: Text(
            text,
            style: Theme.of(context).textTheme.bodyMedium?.copyWith(color: color),
          ),
        ),
      ],
    );
  }
}

class _Brand extends StatelessWidget {
  const _Brand();

  @override
  Widget build(BuildContext context) {
    return Column(
      children: [
        Container(
          height: 64,
          width: 64,
          decoration: BoxDecoration(
            color: const Color(AppConfig.brandPurple),
            borderRadius: BorderRadius.circular(16),
          ),
          child: const Icon(Icons.storefront, color: Colors.white, size: 34),
        ),
        const SizedBox(height: 16),
        const Text(
          'Gusto Owner',
          style: TextStyle(fontSize: 24, fontWeight: FontWeight.w700),
        ),
        const SizedBox(height: 4),
        Text(
          'Staff sign in',
          style: TextStyle(color: Theme.of(context).colorScheme.outline),
        ),
      ],
    );
  }
}
