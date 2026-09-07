import 'package:flutter/material.dart';
import 'package:provider/provider.dart';

import '../services/api_client.dart';
import '../services/auth_service.dart';
import '../state/auth_state.dart';
import 'reset_password_screen.dart';

/// Forgot password: the owner enters a username, the server looks up the email
/// on file and sends a single-use reset code.
///
/// ## The flow only completes because of the second step
/// Requesting the mail is half of it. [ResetPasswordScreen], reachable from the
/// panel below, is what redeems the code — without it the server was minting
/// tokens nothing could spend.
///
/// ## It does not promise mail the server cannot send
/// `emailConfigured` reports whether THIS DEPLOY has a mail transport at all.
/// When it is false the panel says so and offers the admin route instead of
/// claiming a send. That flag describes the server, not the account, so
/// branching on it reveals nothing about the username.
class ForgotPasswordScreen extends StatefulWidget {
  const ForgotPasswordScreen({super.key});

  static const submitKey = Key('forgot_submit');
  static const resultKey = Key('forgot_result');
  static const enterCodeKey = Key('forgot_enter_code');

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

    // Same three-way split as login: a dead connection, a cold start and a
    // server refusal are different problems and get different words. The one
    // thing NOT treated as an error is "no email on file" — that is a
    // successful 200 whose message the panel below renders verbatim, along
    // with the admin-recovery route.
    ForgotPasswordResult? res;
    String? err;
    try {
      res = await context.read<AuthState>().forgotPassword(_username.text);
    } on NetworkException catch (e) {
      err = e.timedOut
          ? 'The server is waking up — this can take up to a minute. '
              'Try again in a few seconds.'
          : 'Could not reach the server. Check your internet connection.';
    } on ApiException catch (e) {
      err = switch (e.statusCode) {
        429 => 'Too many requests. Wait a minute and try again.',
        >= 500 => 'The server hit an error (${e.statusCode}). Try again shortly.',
        _ => 'Could not send reset instructions (${e.statusCode}): ${e.message}',
      };
    } catch (_) {
      err = 'Something went wrong. Please try again.';
    }

    if (!mounted) return;
    setState(() {
      _submitting = false;
      _result = res;
      _error = err;
    });
  }

  /// Opens the redeem step and, if it succeeded, closes this screen too so the
  /// owner is returned to login rather than to a stale "we've sent it" panel.
  Future<void> _openReset(String? emailHint) async {
    final done = await Navigator.of(context).push<bool>(
      MaterialPageRoute(
        builder: (_) => ResetPasswordScreen(emailHint: emailHint),
      ),
    );
    if (!mounted || done != true) return;
    await Navigator.of(context).maybePop();
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
                      key: ForgotPasswordScreen.submitKey,
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
                        key: ForgotPasswordScreen.resultKey,
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
                            // The step that finishes the job. Offered whenever
                            // the server can actually send, INCLUDING when
                            // email_hint is null — that case covers both an
                            // unknown username and a rate-limited real one, and
                            // hiding the button for it would tell the caller
                            // which they were looking at.
                            if (result.emailConfigured) ...[
                              const SizedBox(height: 12),
                              const Divider(height: 1),
                              const SizedBox(height: 4),
                              TextButton.icon(
                                key: ForgotPasswordScreen.enterCodeKey,
                                icon: const Icon(Icons.key_outlined, size: 18),
                                label: const Text('I have a code'),
                                onPressed: () => _openReset(result.maskedEmail),
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
                                      result.emailConfigured
                                          ? 'Older accounts may have no email on '
                                              'file. Your CareVo admin can '
                                              'recover it from the admin '
                                              'dashboard.'
                                          // No transport on this deploy: the
                                          // admin queue is the ONLY route, and
                                          // saying "check your email" would
                                          // send the owner to wait for mail
                                          // that is never coming.
                                          : 'This server cannot send reset '
                                              'email yet. Your CareVo admin can '
                                              'recover the account from the '
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
