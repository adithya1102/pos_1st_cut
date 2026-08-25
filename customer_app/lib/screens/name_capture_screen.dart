import 'package:flutter/material.dart';
import 'package:provider/provider.dart';

import '../services/api_client.dart';
import '../services/customer_service.dart';
import '../state/auth_state.dart';
import '../theme/app_colors.dart';
import '../theme/widgets/neo_button.dart';
import '../theme/widgets/neo_card.dart';
import '../theme/widgets/neo_text_field.dart';

/// One-time blocking prompt for an account that has no name.
///
/// ## Who sees this
///
/// Only accounts created BEFORE the name became mandatory at sign-in. Every
/// new sign-in now supplies one (see `LoginScreen`), so this is a backlog
/// catcher, not part of the normal flow — and it stops appearing for an
/// account the moment a name exists, because the condition it is gated on stops
/// being true. There is no "seen it already" flag to keep in sync: the absence
/// of a name IS the flag, which is why it cannot get stuck showing or stuck
/// hidden.
///
/// ## Why it is genuinely blocking
///
/// Rendered by [HomeScreen] IN PLACE OF the app, not pushed on top of it. A
/// pushed route can be escaped — the system back gesture, a stray `pop`, a
/// deep link — and each of those would need its own guard. Here there is
/// nothing underneath to go back to: while the name is missing, this is what
/// the authenticated app consists of. [PopScope] is belt-and-braces on top of
/// that, so a back gesture is swallowed rather than closing the app.
///
/// It carries NO app bar and NO account action, deliberately: both would be
/// exits, and the account screen in particular would let someone reach Log out
/// and wander off mid-prompt.
class NameCaptureScreen extends StatefulWidget {
  const NameCaptureScreen({super.key, required this.onSaved});

  /// Called after the name has been persisted and the session copy updated.
  final VoidCallback onSaved;

  @override
  State<NameCaptureScreen> createState() => _NameCaptureScreenState();
}

class _NameCaptureScreenState extends State<NameCaptureScreen> {
  final _controller = TextEditingController();
  bool _busy = false;
  String? _error;

  bool get _valid => _controller.text.trim().isNotEmpty;

  @override
  void dispose() {
    _controller.dispose();
    super.dispose();
  }

  Future<void> _save() async {
    if (!_valid || _busy) return;
    FocusScope.of(context).unfocus();
    final svc = context.read<CustomerService>();
    final auth = context.read<AuthState>();

    setState(() {
      _busy = true;
      _error = null;
    });
    try {
      final updated = await svc.updateName(_controller.text.trim());
      if (!mounted) return;
      // Update the session copy BEFORE handing back, so the gate that put this
      // screen up re-evaluates against the new name and lets the app through.
      auth.setCustomer(updated);
      setState(() => _busy = false);
      widget.onSaved();
    } on ApiException catch (e) {
      if (!mounted) return;
      setState(() {
        _busy = false;
        // Inline and persistent, not a SnackBar: the customer cannot leave this
        // screen, so a message that vanishes after four seconds leaves them
        // stuck with no stated reason.
        _error = e.message;
      });
    } catch (_) {
      if (!mounted) return;
      setState(() {
        _busy = false;
        _error = 'Could not reach the server. Please try again.';
      });
    }
  }

  @override
  Widget build(BuildContext context) {
    final c = AppColors.of(context);
    final textTheme = Theme.of(context).textTheme;

    return PopScope(
      // No dismissal, no skip. The only way out is a name.
      canPop: false,
      child: Scaffold(
        body: SafeArea(
          child: LayoutBuilder(
            builder: (context, constraints) => SingleChildScrollView(
              padding: const EdgeInsets.fromLTRB(20, 24, 20, 30),
              child: ConstrainedBox(
                constraints:
                    BoxConstraints(minHeight: constraints.maxHeight - 54),
                child: Column(
                  mainAxisAlignment: MainAxisAlignment.center,
                  crossAxisAlignment: CrossAxisAlignment.stretch,
                  children: [
                    Text(
                      'One last thing',
                      textAlign: TextAlign.center,
                      style: textTheme.headlineMedium?.copyWith(
                        color: AppColors.brand,
                        letterSpacing: -0.5,
                      ),
                    ),
                    const SizedBox(height: 28),
                    NeoCard(
                      padding: const EdgeInsets.all(22),
                      child: Column(
                        crossAxisAlignment: CrossAxisAlignment.start,
                        children: [
                          Text('How can we call you?',
                              style: textTheme.titleLarge),
                          const SizedBox(height: 8),
                          // Says WHY, because being stopped by a form with no
                          // stated reason is what makes a blocking screen feel
                          // arbitrary.
                          Text(
                            'Your orders are called out by name at the '
                            'counter, so we need one on your account.',
                            style:
                                textTheme.bodyMedium?.copyWith(color: c.inkSoft),
                          ),
                          const SizedBox(height: 18),
                          NeoTextField(
                            key: const Key('name_capture_field'),
                            controller: _controller,
                            hintText: 'Your name',
                            autofocus: true,
                            textCapitalization: TextCapitalization.words,
                            maxLength: 100,
                            onChanged: (_) => setState(() {
                              // Clear a stale failure as soon as the input
                              // changes, so it cannot hang over a fresh try.
                              _error = null;
                            }),
                            onSubmitted: (_) => _save(),
                          ),
                          if (_error != null) ...[
                            const SizedBox(height: 10),
                            Row(
                              crossAxisAlignment: CrossAxisAlignment.start,
                              children: [
                                Icon(Icons.error_outline,
                                    size: 16, color: AppColors.tomato),
                                const SizedBox(width: 8),
                                Expanded(
                                  child: Text(
                                    _error!,
                                    key: const Key('name_capture_error'),
                                    // Ink, not red: tomato is large-text-only
                                    // on this shell for contrast reasons, so
                                    // the icon carries the colour and the text
                                    // carries the weight.
                                    style: textTheme.bodySmall
                                        ?.copyWith(color: c.ink),
                                  ),
                                ),
                              ],
                            ),
                          ],
                          const SizedBox(height: 20),
                          NeoButton(
                            key: const Key('name_capture_save'),
                            label: 'Continue',
                            icon: Icons.arrow_forward,
                            loading: _busy,
                            onPressed: _valid && !_busy ? _save : null,
                          ),
                        ],
                      ),
                    ),
                    const SizedBox(height: 16),
                    Text(
                      'You can change this later in your account.',
                      textAlign: TextAlign.center,
                      style: textTheme.bodySmall?.copyWith(color: c.inkSoft),
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
