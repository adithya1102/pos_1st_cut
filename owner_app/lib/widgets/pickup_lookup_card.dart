import 'package:flutter/material.dart';
import 'package:flutter/services.dart';
import 'package:provider/provider.dart';

import '../models/order.dart';
import '../services/order_service.dart';
import '../state/orders_state.dart';

/// Counter-side pickup by code: staff type the code the customer shows, see
/// what the order contains, then confirm the handover.
///
/// ## Why the lookup and the confirm are two taps
///
/// Finding an order does NOT close it. A matched code shows the items and
/// stops there, waiting for an explicit "Confirm pickup". Auto-completing on
/// match would mean a mistyped code that happened to match a real order closed
/// someone else's order with nothing to notice it by — and the items list is
/// exactly what staff use to notice.
///
/// The code is the SAME one issued at payment and shown in the customer app.
/// Nothing here mints a second identifier.
class PickupLookupCard extends StatefulWidget {
  const PickupLookupCard({super.key});

  static const Key fieldKey = Key('pickup_lookup_field');
  static const Key findButtonKey = Key('pickup_lookup_find');
  static const Key confirmButtonKey = Key('pickup_lookup_confirm');
  static const Key notFoundKey = Key('pickup_lookup_not_found');
  static const Key resultKey = Key('pickup_lookup_result');

  @override
  State<PickupLookupCard> createState() => _PickupLookupCardState();
}

enum _Phase { idle, searching, found, notFound, confirming, done, failed }

class _PickupLookupCardState extends State<PickupLookupCard> {
  final _controller = TextEditingController();

  _Phase _phase = _Phase.idle;
  Order? _match;
  bool _locked = false;
  String? _message;

  /// The code that produced [_match]. Confirming re-sends exactly this, not
  /// whatever is in the field by then — staff editing the box after a match
  /// must not silently confirm against a different code.
  String _matchedCode = '';

  static const String _lockoutText =
      'This order is locked after 3 failed attempts. '
      'Ask the operator to unlock it.';

  @override
  void dispose() {
    _controller.dispose();
    super.dispose();
  }

  /// Forget the currently-matched order.
  ///
  /// [_match], [_locked] and [_matchedCode] all describe ONE order, so they
  /// must always move together — a stale `_locked` or `_matchedCode` beside a
  /// fresh match is the same class of bug as the stale panel this exists to
  /// prevent. Call this from every path that stops showing an order, rather
  /// than leaving one populated and relying on a render guard to hide it.
  ///
  /// Caller-scoped: assumes it is already inside a setState.
  void _clearMatch() {
    _match = null;
    _locked = false;
    _matchedCode = '';
  }

  void _reset() {
    setState(() {
      _phase = _Phase.idle;
      _message = null;
      _clearMatch();
    });
  }

  Future<void> _find() async {
    final code = _controller.text.trim();
    if (code.isEmpty) {
      setState(() {
        _phase = _Phase.failed;
        _message = 'Enter the pickup code.';
        // Leaving a previous match here put a COMPLETED order back on screen:
        // this branch moves the phase off `done` without going through the
        // clear below, which re-opened the build guard on the old order.
        _clearMatch();
      });
      return;
    }
    FocusScope.of(context).unfocus();
    setState(() {
      _phase = _Phase.searching;
      _message = null;
      // The previous order goes the moment a new search starts, so it is never
      // on screen while a different code is in flight.
      _clearMatch();
    });

    try {
      final PickupLookup result =
          await context.read<OrdersState>().lookupPickup(code);
      if (!mounted) return;
      setState(() {
        if (!result.found || result.order == null) {
          _phase = _Phase.notFound;
        } else {
          _phase = _Phase.found;
          _match = result.order;
          _locked = result.locked;
          _matchedCode = code;
        }
      });
    } catch (_) {
      if (!mounted) return;
      setState(() {
        _phase = _Phase.failed;
        _message = 'Could not search right now. Try again.';
      });
    }
  }

  Future<void> _confirm() async {
    final order = _match;
    if (order == null) return;
    setState(() {
      _phase = _Phase.confirming;
      _message = null;
    });

    try {
      final PickupResult result = await context
          .read<OrdersState>()
          .confirmPickup(order.orderId, _matchedCode);
      if (!mounted) return;
      setState(() {
        if (result.verified) {
          _phase = _Phase.done;
          _message = 'Pickup confirmed.';
          _controller.clear();
          // The handover is over, so the order is no longer this card's
          // subject. Relying on `_phase == done` to HIDE a still-populated
          // _match left it one phase change away from reappearing — which is
          // exactly how a completed order came back. The done screen renders
          // only the success banner above, never _match, so dropping it here
          // changes nothing on screen and removes the trap.
          _clearMatch();
        } else if (result.locked) {
          _phase = _Phase.failed;
          _message = _lockoutText;
        } else {
          // The code matched a moment ago, so this is the order moving out
          // from under us — collected on another device, or expired.
          _phase = _Phase.failed;
          _message = 'That order is no longer open. Refresh and check.';
        }
      });
    } catch (_) {
      if (!mounted) return;
      setState(() {
        _phase = _Phase.failed;
        _message = 'Could not confirm right now. Try again.';
      });
    }
  }

  @override
  Widget build(BuildContext context) {
    final theme = Theme.of(context);
    final busy = _phase == _Phase.searching || _phase == _Phase.confirming;

    return Card(
      margin: const EdgeInsets.fromLTRB(12, 12, 12, 4),
      child: Padding(
        padding: const EdgeInsets.all(12),
        child: Column(
          crossAxisAlignment: CrossAxisAlignment.stretch,
          children: [
            Text('Pickup by code', style: theme.textTheme.titleSmall),
            const SizedBox(height: 8),
            Row(
              children: [
                Expanded(
                  child: TextField(
                    key: PickupLookupCard.fieldKey,
                    controller: _controller,
                    enabled: !busy,
                    autocorrect: false,
                    keyboardType: TextInputType.number,
                    textInputAction: TextInputAction.search,
                    // Codes are digits 2-9 and six long; the keypad and the
                    // limit keep a mistyped letter from reaching the server.
                    inputFormatters: [
                      FilteringTextInputFormatter.digitsOnly,
                      LengthLimitingTextInputFormatter(8),
                    ],
                    onChanged: (_) {
                      // Editing after a match clears it — the items on screen
                      // must always belong to the code in the box.
                      if (_phase != _Phase.idle && _phase != _Phase.searching) {
                        _reset();
                      }
                    },
                    onSubmitted: (_) => _find(),
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
                    key: PickupLookupCard.findButtonKey,
                    onPressed: busy ? null : _find,
                    child: _phase == _Phase.searching
                        ? const SizedBox(
                            height: 18,
                            width: 18,
                            child: CircularProgressIndicator(strokeWidth: 2),
                          )
                        : const Text('Find'),
                  ),
                ),
              ],
            ),
            if (_phase == _Phase.notFound) ...[
              const SizedBox(height: 10),
              _Banner(
                key: PickupLookupCard.notFoundKey,
                icon: Icons.search_off,
                tone: _Tone.warn,
                text: 'No open order with that code at this outlet.',
              ),
            ],
            if (_message != null) ...[
              const SizedBox(height: 10),
              _Banner(
                icon: _phase == _Phase.done
                    ? Icons.check_circle_outline
                    : Icons.error_outline,
                tone: _phase == _Phase.done ? _Tone.success : _Tone.error,
                text: _message!,
              ),
            ],
            if (_match != null && _phase != _Phase.done) ...[
              const SizedBox(height: 12),
              _MatchedOrder(
                key: PickupLookupCard.resultKey,
                order: _match!,
                locked: _locked,
                busy: _phase == _Phase.confirming,
                onConfirm: _confirm,
              ),
            ],
          ],
        ),
      ),
    );
  }
}

/// The matched order: what is in the bag, then the confirm gate.
class _MatchedOrder extends StatelessWidget {
  final Order order;
  final bool locked;
  final bool busy;
  final VoidCallback onConfirm;

  const _MatchedOrder({
    super.key,
    required this.order,
    required this.locked,
    required this.busy,
    required this.onConfirm,
  });

  @override
  Widget build(BuildContext context) {
    final theme = Theme.of(context);

    return Container(
      padding: const EdgeInsets.all(12),
      decoration: BoxDecoration(
        border: Border.all(color: theme.dividerColor),
        borderRadius: BorderRadius.circular(8),
      ),
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.stretch,
        children: [
          Row(
            children: [
              Expanded(
                child: Text('Order ${order.shortId}',
                    style: theme.textTheme.titleSmall),
              ),
              Text(order.status, style: theme.textTheme.labelMedium),
            ],
          ),
          const SizedBox(height: 8),
          if (order.items.isEmpty)
            Text('No line items on this order.',
                style: theme.textTheme.bodySmall)
          else
            ...order.items.map(
              (it) => Padding(
                padding: const EdgeInsets.symmetric(vertical: 2),
                child: Row(
                  children: [
                    SizedBox(
                      width: 32,
                      child: Text('${it.quantity}x',
                          style: theme.textTheme.bodyMedium
                              ?.copyWith(fontWeight: FontWeight.w600)),
                    ),
                    Expanded(child: Text(it.name)),
                  ],
                ),
              ),
            ),
          const Divider(height: 20),
          if (locked)
            const _Banner(
              icon: Icons.lock_outline,
              tone: _Tone.error,
              text: 'This order is locked after 3 failed attempts. '
                  'Ask the operator to unlock it.',
            )
          else
            SizedBox(
              height: 48,
              child: FilledButton.icon(
                key: PickupLookupCard.confirmButtonKey,
                onPressed: busy ? null : onConfirm,
                icon: busy
                    ? const SizedBox(
                        height: 16,
                        width: 16,
                        child: CircularProgressIndicator(strokeWidth: 2),
                      )
                    : const Icon(Icons.check),
                label: const Text('Confirm pickup'),
              ),
            ),
        ],
      ),
    );
  }
}

enum _Tone { success, warn, error }

class _Banner extends StatelessWidget {
  final IconData icon;
  final _Tone tone;
  final String text;

  const _Banner({
    super.key,
    required this.icon,
    required this.tone,
    required this.text,
  });

  @override
  Widget build(BuildContext context) {
    final scheme = Theme.of(context).colorScheme;
    final Color fg = switch (tone) {
      _Tone.success => scheme.primary,
      _Tone.warn => const Color(0xFFB26A00),
      _Tone.error => scheme.error,
    };
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
            child: Text(text,
                style: TextStyle(color: fg, fontWeight: FontWeight.w500)),
          ),
        ],
      ),
    );
  }
}
