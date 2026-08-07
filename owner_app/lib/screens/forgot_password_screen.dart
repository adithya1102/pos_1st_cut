import 'package:flutter/material.dart';
import 'package:provider/provider.dart';

import '../services/auth_service.dart';
import '../state/auth_state.dart';

/// Forgot password: the owner enters a username, the server looks up the email
/// on file and sends reset instructions.
///
/// ## What this screen deliberately does NOT do
/// It never says whether the username exists. The backend returns an identical
/// message either way, and this screen shows that message verbatim — so no
/// branching here can leak the difference. The masked hint ("a*****a@g***l.com")
/// appears only when the server supplies one, which it does only for a real
/// account with an email on file.
class ForgotPasswordScreen extends StatefulWidget {
  const ForgotPasswordScreen({super.key});

  @override
  State<ForgotPasswordScreen> createState() => _ForgotPasswordScreenState();
}

class _ForgotPasswordScreenState extends State<ForgotPasswordScreen> {
  final _formKey = GlobalKey<FormState>();
  final _username = TextEditingController();

  bool _submitting = false;
  ForgotPasswordResult? _result;
  String? _error;

  @override
  void dispose() {
    _username.dispose();
    super.dispose();
  }

  Future<void> _submit() async {
    FocusScope.of(context).unfocus();
    if (!(_formKey.currentState?.validate() ?? false)) return;

    setState(() {
      _submitting = true;
      _error = null;
      _result = null;
    });
    final res = await context.read<AuthState>().forgotPassword(_username.text);
    if (!mounted) return;
    setState(() {
      _submitting = false;
      _result = res;
      if (res == null) _error = 'Could not reach the server. Try again.';
    });
  }

  @override
  Widget build(BuildContext context) {
    final theme = Theme.of(context);
    final result = _result;

    return Scaffold(
      appBar: AppBar(title: const Text('Forgot password')),
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
                      'Enter your username and we\'ll send reset instructions '
                      'to the email on file.',
                      style: theme.textTheme.bodyMedium,
                    ),
                    const SizedBox(height: 20),
                    TextFormField(
                      controller: _username,
                      autocorrect: false,
                      enableSuggestions: false,
                      decoration: const InputDecoration(
                        labelText: 'Username',
                        prefixIcon: Icon(Icons.person_outline),
                      ),
                      validator: (v) => (v == null || v.trim().isEmpty)
                          ? 'Enter your username'
                          : null,
                      onFieldSubmitted: (_) => _submit(),
                    ),
                    const SizedBox(height: 24),
                    FilledButton(
                      onPressed: _submitting ? null : _submit,
                      child: _submitting
                          ? const SizedBox(
                              height: 18,
                              width: 18,
                              child: CircularProgressIndicator(strokeWidth: 2),
                            )
                          : const Text('Send reset instructions'),
                    ),

                    if (_error != null) ...[
                      const SizedBox(height: 20),
                      Text(_error!,
                          style: TextStyle(color: theme.colorScheme.error)),
                    ],

                    // The server's message, shown verbatim. It is identical for
                    // a real and a non-existent username.
                    if (result != null) ...[
                      const SizedBox(height: 24),
                      Container(
                        padding: const EdgeInsets.all(14),
                        decoration: BoxDecoration(
                          color: theme.colorScheme.surfaceContainerHighest,
                          borderRadius: BorderRadius.circular(10),
                        ),
                        child: Column(
                          crossAxisAlignment: CrossAxisAlignment.start,
                          children: [
                            Row(
                              children: [
                                Icon(Icons.mark_email_read_outlined,
                                    size: 20, color: theme.colorScheme.primary),
                                const SizedBox(width: 8),
                                Expanded(
                                  child: Text(result.message,
                                      style: theme.textTheme.bodyMedium),
                                ),
                              ],
                            ),
                            // Only present when there is a real address on
                            // file — enough to recognise, not to learn.
                            if (result.maskedEmail != null) ...[
                              const SizedBox(height: 12),
                              Text('Sent to', style: theme.textTheme.labelSmall),
                              const SizedBox(height: 2),
                              SelectableText(
                                result.maskedEmail!,
                                style: const TextStyle(
                                  fontFamily: 'monospace',
                                  fontWeight: FontWeight.bold,
                                ),
                              ),
                            ],
                            // Legacy account with no email: the humans are the
                            // fallback, via the existing admin queue.
                            if (result.needsAdminHelp) ...[
                              const SizedBox(height: 12),
                              Row(
                                crossAxisAlignment: CrossAxisAlignment.start,
                                children: [
                                  Icon(Icons.support_agent_outlined,
                                      size: 18, color: theme.colorScheme.tertiary),
                                  const SizedBox(width: 8),
                                  Expanded(
                                    child: Text(
                                      'Older accounts may have no email on file. '
                                      'Your CareVo admin can recover it from the '
                                      'admin dashboard.',
                                      style: theme.textTheme.bodySmall,
                                    ),
                                  ),
                                ],
                              ),
                            ],
                          ],
                        ),
                      ),
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
