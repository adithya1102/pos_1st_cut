import 'dart:async';

import 'package:flutter/material.dart';

import '../models/order.dart';

/// Why staff are refusing an order. Fixed options, plus free text.
///
/// Fixed because a typed reason at a busy counter is a reason nobody types —
/// the field gets left blank and the customer is told nothing. These four cover
/// what actually happens; "Other" keeps the escape hatch without making it the
/// default path.
enum RejectReason {
  outOfStock('Out of stock'),
  tooBusy('Too busy'),
  closingSoon('Closing soon'),
  other('Other');

  const RejectReason(this.label);
  final String label;
}

/// What the modal was closed with. Returned by [showOrderAcceptanceModal] so
/// the caller can report the outcome without the modal owning any networking.
sealed class AcceptanceDecision {
  const AcceptanceDecision();
}

class AcceptDecision extends AcceptanceDecision {
  const AcceptDecision(this.prepMinutes);
  final int prepMinutes;
}

class RejectDecision extends AcceptanceDecision {
  const RejectDecision(this.reason, {this.note});
  final RejectReason reason;
  final String? note;

  /// What the server stores. "Other" alone says nothing, so the free-text note
  /// replaces the label rather than being appended to it.
  String get serverReason =>
      (reason == RejectReason.other && (note?.trim().isNotEmpty ?? false))
          ? note!.trim()
          : reason.label;
}

/// Full-screen, non-dismissible decision sheet for one pending order.
///
/// NON-DISMISSIBLE (`barrierDismissible: false`, no close button, and
/// PopScope blocking the back gesture) and that is deliberate. A dismissable
/// alert is one a busy person swipes away without reading, and the cost here is
/// not a missed notification — it is a cancelled order and a refund. The only
/// ways out are Accept, Reject, or the deadline passing, all of which resolve
/// the order on the server.
///
/// It takes NO services. The caller does the networking and owns the alarm, so
/// this widget is pure UI and testable without a backend or an audio device.
Future<AcceptanceDecision?> showOrderAcceptanceModal(
  BuildContext context,
  Order order,
) {
  return showGeneralDialog<AcceptanceDecision>(
    context: context,
    barrierDismissible: false,
    barrierColor: Colors.black87,
    // Full-screen rather than a card: it has to be unmistakable from across a
    // kitchen, and a dialog competing with the order list behind it is not.
    pageBuilder: (_, _, _) => _AcceptanceSheet(order: order),
  );
}

class _AcceptanceSheet extends StatefulWidget {
  const _AcceptanceSheet({required this.order});
  final Order order;

  @override
  State<_AcceptanceSheet> createState() => _AcceptanceSheetState();
}

class _AcceptanceSheetState extends State<_AcceptanceSheet> {
  /// The four values that cover almost every real answer. A stepper handles
  /// the rest, so the common case is one tap and the uncommon case is still
  /// reachable — a bare stepper would mean four taps to say "20 minutes".
  static const List<int> presets = [10, 15, 20, 30];

  int _prep = 15;
  bool _rejecting = false;
  RejectReason? _reason;
  final _note = TextEditingController();
  Timer? _tick;

  @override
  void initState() {
    super.initState();
    // Rebuild once a second purely for the countdown. Cheap, and it is the
    // only thing on this screen that changes without input.
    _tick = Timer.periodic(const Duration(seconds: 1), (_) {
      if (mounted) setState(() {});
    });
  }

  @override
  void dispose() {
    _tick?.cancel();
    _note.dispose();
    super.dispose();
  }

  @override
  Widget build(BuildContext context) {
    final theme = Theme.of(context);
    final left = widget.order.secondsToDeadline;

    return PopScope(
      // Back must not dismiss an undecided order — see the function docstring.
      canPop: false,
      child: Scaffold(
        backgroundColor: theme.colorScheme.surface,
        body: SafeArea(
          child: Padding(
            padding: const EdgeInsets.all(20),
            child: Column(
              crossAxisAlignment: CrossAxisAlignment.stretch,
              children: [
                Text('New order',
                    style: theme.textTheme.headlineMedium
                        ?.copyWith(fontWeight: FontWeight.w700)),
                const SizedBox(height: 4),
                if (left != null)
                  Text(
                    key: const Key('acceptance_countdown'),
                    left > 0
                        ? '$left seconds to accept'
                        // Said plainly. A "0 seconds" countdown that still
                        // offers Accept would be lying — the server has almost
                        // certainly expired it already.
                        : 'Time is up — this order may already be cancelled.',
                    style: theme.textTheme.titleMedium?.copyWith(
                      color: left > 30
                          ? theme.colorScheme.onSurfaceVariant
                          : theme.colorScheme.error,
                      fontWeight: FontWeight.w600,
                    ),
                  ),
                const SizedBox(height: 16),
                Text('₹${widget.order.totalAmount.toStringAsFixed(0)}',
                    style: theme.textTheme.headlineSmall),
                const SizedBox(height: 12),
                Expanded(
                  child: ListView(
                    children: [
                      for (final it in widget.order.items)
                        Padding(
                          padding: const EdgeInsets.symmetric(vertical: 4),
                          child: Text('${it.quantity}× ${it.name}',
                              style: theme.textTheme.bodyLarge),
                        ),
                    ],
                  ),
                ),
                if (_rejecting) ..._rejectBody(theme) else ..._acceptBody(theme),
              ],
            ),
          ),
        ),
      ),
    );
  }

  List<Widget> _acceptBody(ThemeData theme) => [
        Text('How long will it take?', style: theme.textTheme.titleSmall),
        const SizedBox(height: 8),
        Wrap(
          spacing: 8,
          children: [
            for (final m in presets)
              ChoiceChip(
                key: Key('prep_chip_$m'),
                label: Text('$m min'),
                selected: _prep == m,
                onSelected: (_) => setState(() => _prep = m),
              ),
          ],
        ),
        const SizedBox(height: 8),
        Row(
          mainAxisAlignment: MainAxisAlignment.center,
          children: [
            IconButton(
              key: const Key('prep_minus'),
              icon: const Icon(Icons.remove_circle_outline),
              // Floored at 5, not 1: a sub-5-minute promise is not credible
              // and would only ever be a mis-tap.
              onPressed: _prep > 5 ? () => setState(() => _prep -= 5) : null,
            ),
            Text('$_prep min',
                key: const Key('prep_value'),
                style: theme.textTheme.titleLarge),
            IconButton(
              key: const Key('prep_plus'),
              icon: const Icon(Icons.add_circle_outline),
              onPressed: _prep < 120 ? () => setState(() => _prep += 5) : null,
            ),
          ],
        ),
        const SizedBox(height: 12),
        FilledButton(
          key: const Key('acceptance_accept'),
          onPressed: () =>
              Navigator.of(context).pop(AcceptDecision(_prep)),
          child: Text('Accept — $_prep min'),
        ),
        const SizedBox(height: 8),
        // Visually quieter than Accept. Both are one tap, but the destructive
        // one should not be the one a thumb lands on by accident.
        OutlinedButton(
          key: const Key('acceptance_reject_open'),
          onPressed: () => setState(() => _rejecting = true),
          child: const Text('Can\'t make this'),
        ),
      ];

  List<Widget> _rejectBody(ThemeData theme) => [
        Text('Why not?', style: theme.textTheme.titleSmall),
        const SizedBox(height: 8),
        Wrap(
          spacing: 8,
          children: [
            for (final r in RejectReason.values)
              ChoiceChip(
                key: Key('reject_reason_${r.name}'),
                label: Text(r.label),
                selected: _reason == r,
                onSelected: (_) => setState(() => _reason = r),
              ),
          ],
        ),
        if (_reason == RejectReason.other) ...[
          const SizedBox(height: 8),
          TextField(
            key: const Key('reject_note'),
            controller: _note,
            decoration: const InputDecoration(
              labelText: 'What happened? (optional)',
            ),
            maxLength: 120,
          ),
        ],
        const SizedBox(height: 8),
        FilledButton(
          key: const Key('acceptance_reject_confirm'),
          style: FilledButton.styleFrom(
            backgroundColor: theme.colorScheme.error,
            foregroundColor: theme.colorScheme.onError,
          ),
          // A reason is REQUIRED before the button works. The customer is
          // about to be told their order was refused, and "no reason given" is
          // the one thing that makes that unanswerable for them.
          onPressed: _reason == null
              ? null
              : () => Navigator.of(context).pop(
                  RejectDecision(_reason!, note: _note.text)),
          child: const Text('Reject and refund'),
        ),
        const SizedBox(height: 8),
        TextButton(
          key: const Key('acceptance_reject_back'),
          onPressed: () => setState(() {
            _rejecting = false;
            _reason = null;
          }),
          child: const Text('Back'),
        ),
      ];
}
