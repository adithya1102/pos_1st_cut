import 'package:flutter/material.dart';
import 'package:provider/provider.dart';

import '../services/order_service.dart';
import '../state/orders_state.dart';

/// Pickup-code verification for a single order.
///
/// Surfaces the HTTP 423 lockout as plain, staff-readable text — never a raw
/// code or stack trace.
class VerifyBox extends StatefulWidget {
  final String orderId;

  const VerifyBox({super.key, required this.orderId});

  @override
  State<VerifyBox> createState() => _VerifyBoxState();
}

class _VerifyBoxState extends State<VerifyBox> {
  final _controller = TextEditingController();
  bool _busy = false;
  _Feedback? _feedback;

  static const String _lockoutText =
      'This order is locked after 3 failed attempts. '
      'Ask the operator to unlock it.';

  @override
  void dispose() {
    _controller.dispose();
    super.dispose();
  }

  Future<void> _verify() async {
    final code = _controller.text.trim();
    if (code.isEmpty) {
      setState(() => _feedback = _Feedback.warn('Enter the pickup code.'));
      return;
    }
    FocusScope.of(context).unfocus();
    setState(() {
      _busy = true;
      _feedback = null;
    });

    try {
      final PickupResult result =
          await context.read<OrdersState>().verifyPickup(widget.orderId, code);

      if (!mounted) return;
      setState(() {
        if (result.locked) {
          _feedback = _Feedback.error(_lockoutText);
        } else if (result.verified) {
          _feedback = _Feedback.success(
            result.status != null && result.status!.isNotEmpty
                ? 'Verified — ${result.status}.'
                : 'Verified — pickup confirmed.',
          );
          _controller.clear();
        } else {
          final remaining = result.attemptsRemaining;
          _feedback = _Feedback.warn(
            remaining != null
                ? 'Incorrect code. $remaining attempt'
                    '${remaining == 1 ? '' : 's'} remaining.'
                : 'Incorrect code. Try again.',
          );
        }
      });
    } catch (_) {
      if (!mounted) return;
      setState(() => _feedback =
          _Feedback.error('Could not verify right now. Try again.'));
    } finally {
      if (mounted) setState(() => _busy = false);
    }
  }

  @override
  Widget build(BuildContext context) {
    final theme = Theme.of(context);
    final verified = _feedback?.kind == _FeedbackKind.success;

    return Column(
      crossAxisAlignment: CrossAxisAlignment.stretch,
      children: [
        Text('Pickup verification', style: theme.textTheme.labelLarge),
        const SizedBox(height: 8),
        Row(
          crossAxisAlignment: CrossAxisAlignment.start,
          children: [
            Expanded(
              child: TextField(
                controller: _controller,
                enabled: !verified,
                textInputAction: TextInputAction.done,
                onSubmitted: (_) => _verify(),
                decoration: const InputDecoration(
                  labelText: 'Pickup code',
                  prefixIcon: Icon(Icons.pin_outlined),
                ),
              ),
            ),
            const SizedBox(width: 8),
            SizedBox(
              height: 48,
              child: FilledButton(
                onPressed: (_busy || verified) ? null : _verify,
                child: _busy
                    ? const SizedBox(
                        height: 18,
                        width: 18,
                        child: CircularProgressIndicator(strokeWidth: 2),
                      )
                    : Text(verified ? 'Done' : 'Verify'),
              ),
            ),
          ],
        ),
        if (_feedback != null) ...[
          const SizedBox(height: 8),
          _FeedbackBanner(feedback: _feedback!),
        ],
      ],
    );
  }
}

enum _FeedbackKind { success, warn, error }

class _Feedback {
  final _FeedbackKind kind;
  final String message;

  const _Feedback(this.kind, this.message);

  factory _Feedback.success(String m) => _Feedback(_FeedbackKind.success, m);
  factory _Feedback.warn(String m) => _Feedback(_FeedbackKind.warn, m);
  factory _Feedback.error(String m) => _Feedback(_FeedbackKind.error, m);
}

class _FeedbackBanner extends StatelessWidget {
  final _Feedback feedback;

  const _FeedbackBanner({required this.feedback});

  @override
  Widget build(BuildContext context) {
    final scheme = Theme.of(context).colorScheme;
    late final Color fg;
    late final IconData icon;
    switch (feedback.kind) {
      case _FeedbackKind.success:
        fg = scheme.primary;
        icon = Icons.check_circle_outline;
        break;
      case _FeedbackKind.warn:
        fg = const Color(0xFFB26A00);
        icon = Icons.error_outline;
        break;
      case _FeedbackKind.error:
        fg = scheme.error;
        icon = Icons.lock_outline;
        break;
    }
    return Container(
      padding: const EdgeInsets.all(10),
      decoration: BoxDecoration(
        color: fg.withValues(alpha: 0.08),
        borderRadius: BorderRadius.circular(8),
      ),
      child: Row(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          Icon(icon, size: 18, color: fg),
          const SizedBox(width: 8),
          Expanded(
            child: Text(
              feedback.message,
              style: TextStyle(color: fg, fontWeight: FontWeight.w500),
            ),
          ),
        ],
      ),
    );
  }
}
