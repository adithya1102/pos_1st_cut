import 'package:flutter/material.dart';
import 'package:provider/provider.dart';
import 'package:url_launcher/url_launcher.dart';

import '../models/order.dart';
import '../state/orders_state.dart';
import 'notify_section.dart';
import 'verify_box.dart';

/// A single order in the queue. Anchored by order_id (short form shown).
/// Tapping the header expands the detail IN PLACE — no navigation.
class OrderCard extends StatefulWidget {
  final Order order;

  const OrderCard({super.key, required this.order});

  @override
  State<OrderCard> createState() => _OrderCardState();
}

/// "Collected just now" / "Collected 12m ago — clearing soon".
///
/// Deliberately vague about the exact removal moment: the server owns the
/// cutoff, and promising a precise countdown the app does not control would be
/// a number that drifts.
String _collectedLabel(Order order) {
  final mins = order.minutesSinceCollected;
  if (mins == null) return 'Collected — clearing soon';
  if (mins < 1) return 'Collected just now — clearing soon';
  return 'Collected ${mins}m ago — clearing soon';
}

class _OrderCardState extends State<OrderCard> {
  bool _expanded = false;

  @override
  Widget build(BuildContext context) {
    final order = widget.order;
    final theme = Theme.of(context);
    final itemCount = order.items.fold<int>(0, (sum, i) => sum + i.quantity);

    return Card(
      clipBehavior: Clip.antiAlias,
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.stretch,
        children: [
          // --- header row (tap to expand) ---
          InkWell(
            onTap: () => setState(() => _expanded = !_expanded),
            child: Padding(
              padding: const EdgeInsets.all(14),
              child: Row(
                children: [
                  Expanded(
                    child: Column(
                      crossAxisAlignment: CrossAxisAlignment.start,
                      children: [
                        Row(
                          children: [
                            Text(
                              '#${order.shortId}',
                              style: theme.textTheme.titleMedium
                                  ?.copyWith(fontWeight: FontWeight.w700),
                            ),
                            const SizedBox(width: 8),
                            _StatusChip(
                                status: order.status, locked: order.isLocked),
                            const SizedBox(width: 6),
                            _PayChip(paid: order.isPaid),
                          ],
                        ),
                        const SizedBox(height: 4),
                        Text(
                          '$itemCount item${itemCount == 1 ? '' : 's'}'
                          '  •  ₹${order.totalAmount.toStringAsFixed(0)}',
                          style: theme.textTheme.bodySmall,
                        ),
                        // Only ever visible during the 30-minute grace window:
                        // the server stops returning the order once it closes,
                        // so this row cannot linger past its own message.
                        if (order.isCollected) ...[
                          const SizedBox(height: 4),
                          Text(
                            _collectedLabel(order),
                            key: const Key('collected_grace_label'),
                            style: theme.textTheme.bodySmall?.copyWith(
                              color: theme.colorScheme.outline,
                              fontStyle: FontStyle.italic,
                            ),
                          ),
                        ],
                        // "Left X min ago" / "At the restaurant" — absent
                        // entirely when the server has no signal yet, which
                        // is every order until the customer taps or the
                        // geofence fires. Read straight off the same
                        // GET /pos/orders response the queue already polls;
                        // no new request, no new timer.
                        if (order.arrivalChipLabel != null) ...[
                          const SizedBox(height: 4),
                          _ArrivalChip(label: order.arrivalChipLabel!,
                              arrived: order.hasArrived),
                        ],
                      ],
                    ),
                  ),
                  Icon(_expanded ? Icons.expand_less : Icons.expand_more),
                ],
              ),
            ),
          ),

          // --- expanded detail ---
          AnimatedCrossFade(
            duration: const Duration(milliseconds: 180),
            crossFadeState: _expanded
                ? CrossFadeState.showSecond
                : CrossFadeState.showFirst,
            firstChild: const SizedBox(width: double.infinity),
            secondChild: _Detail(order: order),
          ),
        ],
      ),
    );
  }
}

class _Detail extends StatelessWidget {
  final Order order;

  const _Detail({required this.order});

  @override
  Widget build(BuildContext context) {
    final theme = Theme.of(context);
    return Container(
      decoration: BoxDecoration(
        border: Border(top: BorderSide(color: theme.colorScheme.outlineVariant)),
      ),
      padding: const EdgeInsets.fromLTRB(14, 12, 14, 16),
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.stretch,
        children: [
          // The restaurant owes money back, directly. First, because it is the
          // only thing on this card that costs the owner something if missed.
          if (order.manualRefundDue) ...[
            _ManualRefundBanner(order: order),
            const Divider(height: 24),
          ],
          // Who to call, for the two modes that have a customer to reach.
          if (order.contactVisible) ...[
            _ContactRow(order: order),
            const Divider(height: 24),
          ],
          _PaymentAction(order: order),
          const Divider(height: 24),
          Text('Items', style: theme.textTheme.labelLarge),
          const SizedBox(height: 6),
          ...order.items.map(
            (item) => Padding(
              padding: const EdgeInsets.symmetric(vertical: 3),
              child: Row(
                children: [
                  Expanded(child: Text(item.name)),
                  Text('× ${item.quantity}',
                      style: theme.textTheme.bodyMedium),
                ],
              ),
            ),
          ),
          const Divider(height: 24),
          ItemUnavailableChecklist(order: order),
          const Divider(height: 24),
          VerifyBox(orderId: order.orderId),
          const Divider(height: 24),
          NotifySection(order: order),
        ],
      ),
    );
  }
}

/// Payment state + the one human gate on an order.
///
/// There is no "Mark Payment Received" any more, and no "Accept" either. The
/// gateway webhook confirms payment and the order moves to RECEIVED on its own,
/// so staff are never the thing an order waits on. What they get instead is the
/// ability to pull an order they cannot make — an opt-OUT, not an opt-in.
class _PaymentAction extends StatefulWidget {
  final Order order;
  const _PaymentAction({required this.order});

  @override
  State<_PaymentAction> createState() => _PaymentActionState();
}

class _PaymentActionState extends State<_PaymentAction> {
  bool _busy = false;

  /// Mirrors the server's REJECTABLE_STATUSES. Once the food is made and
  /// waiting on the counter, "we can't do this one" is no longer true.
  static const _rejectable = {'PAID', 'RECEIVED', 'PREPARING'};

  bool get _canReject =>
      widget.order.isPaid && _rejectable.contains(widget.order.status.toUpperCase());

  Future<void> _reject() async {
    final controller = TextEditingController();
    final confirmed = await showDialog<bool>(
      context: context,
      builder: (c) => AlertDialog(
        title: const Text('Reject this order?'),
        content: Column(
          mainAxisSize: MainAxisSize.min,
          crossAxisAlignment: CrossAxisAlignment.start,
          children: [
            const Text(
              'The customer has already paid. They will be told the order was '
              'cancelled and that a refund is being arranged.',
            ),
            const SizedBox(height: 12),
            TextField(
              controller: controller,
              maxLength: 300,
              decoration: const InputDecoration(
                labelText: 'Reason (optional, for your records)',
                hintText: 'Kitchen closed early',
              ),
            ),
          ],
        ),
        actions: [
          TextButton(onPressed: () => Navigator.pop(c, false), child: const Text('Keep it')),
          FilledButton(
            style: FilledButton.styleFrom(
              backgroundColor: Theme.of(c).colorScheme.error,
            ),
            onPressed: () => Navigator.pop(c, true),
            child: const Text('Reject order'),
          ),
        ],
      ),
    );
    if (confirmed != true || !mounted) return;

    setState(() => _busy = true);
    final err = await context
        .read<OrdersState>()
        .reject(widget.order.orderId, reason: controller.text);
    if (!mounted) return;
    setState(() => _busy = false);
    ScaffoldMessenger.of(context)
      ..hideCurrentSnackBar()
      ..showSnackBar(SnackBar(
        content: Text(err ?? 'Order rejected. The customer has been notified.'),
      ));
  }


  /// Accept. For a direct-UPI order this IS the payment confirmation, so it is
  /// behind a confirm dialog that names what the staff member is asserting.
  Future<void> _accept(BuildContext context) async {
    final order = widget.order;

    if (order.isUpiManual) {
      final sure = await showDialog<bool>(
        context: context,
        builder: (c) => AlertDialog(
          key: const Key('upi_accept_confirm'),
          title: const Text('Has the money arrived?'),
          content: Text(
            'Only accept if your UPI app shows exactly '
            '₹${order.totalAmount.toStringAsFixed(0)} from this customer. '
            'Accepting records the payment.',
          ),
          actions: [
            TextButton(
                onPressed: () => Navigator.pop(c, false),
                child: const Text('Not yet')),
            FilledButton(
                key: const Key('upi_accept_confirm_yes'),
                onPressed: () => Navigator.pop(c, true),
                child: const Text('Yes, received')),
          ],
        ),
      );
      if (sure != true || !mounted) return;
    }

    setState(() => _busy = true);
    // 15 minutes is the modal's own default and the commonest answer; the
    // acceptance modal is where a real estimate is chosen.
    final err = await context.read<OrdersState>().acceptPending(
        order.orderId, 15);
    if (!mounted) return;
    setState(() => _busy = false);
    if (err != null) {
      ScaffoldMessenger.of(context)
        ..hideCurrentSnackBar()
        ..showSnackBar(SnackBar(content: Text(err)));
    }
  }

  /// Reject a direct-UPI order, with WHICH kind of no it is.
  ///
  /// The two outcomes are opposites and the dialogs say so: one strikes the
  /// customer and owes nothing, the other obliges the restaurant to refund.
  Future<void> _rejectUpi(BuildContext context, String outcome) async {
    final order = widget.order;
    final notReceived = outcome == 'not_received';

    final sure = await showDialog<bool>(
      context: context,
      builder: (c) => AlertDialog(
        key: Key('upi_reject_confirm_$outcome'),
        title: Text(notReceived
            ? 'Payment not received?'
            : "Can't make this order?"),
        content: Text(notReceived
            ? 'Check your UPI app once more. If the money really is not '
              'there, the order is cancelled and the customer is told.'
            : 'The customer has paid '
              '₹${order.totalAmount.toStringAsFixed(0)}. You will need to '
              'refund them yourself from your UPI app.'),
        actions: [
          TextButton(
              onPressed: () => Navigator.pop(c, false),
              child: const Text('Go back')),
          FilledButton(
            style: FilledButton.styleFrom(
                backgroundColor: Theme.of(c).colorScheme.error),
            onPressed: () => Navigator.pop(c, true),
            child: Text(notReceived ? 'Not received' : 'Cancel and refund'),
          ),
        ],
      ),
    );
    if (sure != true || !mounted) return;

    setState(() => _busy = true);
    final err = await context.read<OrdersState>().reject(
          order.orderId,
          upiOutcome: outcome,
        );
    if (!mounted) return;
    setState(() => _busy = false);
    ScaffoldMessenger.of(context)
      ..hideCurrentSnackBar()
      ..showSnackBar(SnackBar(
        content: Text(err ??
            (notReceived
                ? 'Order cancelled. The customer has been told.'
                : 'Order cancelled. Please refund the customer.')),
      ));
  }

  /// Take the money and hand the food over, in one action.
  ///
  /// The pickup code is required, exactly as it is for a prepaid handover:
  /// taking cash cannot be decoupled from checking this is the right order.
  Future<void> _collect(BuildContext context) async {
    final code = TextEditingController();
    String method = 'cash';

    final result = await showDialog<({String code, String method})?>(
      context: context,
      builder: (c) => StatefulBuilder(
        builder: (c, setLocal) => AlertDialog(
          key: const Key('collect_dialog'),
          title: const Text('Paid and handed over'),
          content: Column(
            mainAxisSize: MainAxisSize.min,
            crossAxisAlignment: CrossAxisAlignment.start,
            children: [
              Text('₹${widget.order.totalAmount.toStringAsFixed(0)} '
                  'from the customer.'),
              const SizedBox(height: 12),
              SegmentedButton<String>(
                key: const Key('collect_method'),
                segments: const [
                  ButtonSegment(value: 'cash', label: Text('Cash')),
                  ButtonSegment(value: 'upi', label: Text('UPI')),
                ],
                selected: {method},
                onSelectionChanged: (s) => setLocal(() => method = s.first),
              ),
              const SizedBox(height: 12),
              TextField(
                key: const Key('collect_code'),
                controller: code,
                keyboardType: TextInputType.number,
                decoration: const InputDecoration(
                  labelText: 'Pickup code',
                  hintText: '6 digits',
                ),
              ),
            ],
          ),
          actions: [
            TextButton(
                onPressed: () => Navigator.pop(c, null),
                child: const Text('Cancel')),
            FilledButton(
              key: const Key('collect_confirm'),
              onPressed: () => Navigator.pop(
                  c, (code: code.text.trim(), method: method)),
              child: const Text('Confirm'),
            ),
          ],
        ),
      ),
    );
    if (result == null || !mounted) return;

    setState(() => _busy = true);
    final res = await context
        .read<OrdersState>()
        .collect(widget.order.orderId, pickupCode: result.code,
            method: result.method);
    if (!mounted) return;
    setState(() => _busy = false);
    ScaffoldMessenger.of(context)
      ..hideCurrentSnackBar()
      ..showSnackBar(SnackBar(
        content: Text(res.verified
            ? 'Payment recorded and order closed.'
            : (res.message ??
                (res.locked
                    ? 'Too many wrong codes. This order is locked.'
                    : 'Wrong code. ${res.attemptsRemaining ?? 0} '
                      'attempts left.'))),
      ));
  }

  Future<void> _noShow(BuildContext context) async {
    final sure = await showDialog<bool>(
      context: context,
      builder: (c) => AlertDialog(
        key: const Key('no_show_confirm'),
        title: const Text('Customer never came?'),
        content: const Text(
            'The order is closed as a no-show and the customer gets a strike. '
            'The food is not returned to stock.'),
        actions: [
          TextButton(
              onPressed: () => Navigator.pop(c, false),
              child: const Text('Keep waiting')),
          FilledButton(
            style: FilledButton.styleFrom(
                backgroundColor: Theme.of(c).colorScheme.error),
            onPressed: () => Navigator.pop(c, true),
            child: const Text('No-show'),
          ),
        ],
      ),
    );
    if (sure != true || !mounted) return;

    setState(() => _busy = true);
    final err =
        await context.read<OrdersState>().noShow(widget.order.orderId);
    if (!mounted) return;
    setState(() => _busy = false);
    ScaffoldMessenger.of(context)
      ..hideCurrentSnackBar()
      ..showSnackBar(
          SnackBar(content: Text(err ?? 'Order closed as a no-show.')));
  }

  /// Pay-at-pickup: call, then decide. Direct UPI: check the app, then decide.
  ///
  /// Both are built here rather than in a separate widget because they share
  /// the reject path and the "too late" states with the prepaid card, and
  /// forking it would mean three copies of those drifting apart.
  Widget _nonGatewayActions(BuildContext context) {
    final theme = Theme.of(context);
    final order = widget.order;
    final status = order.status.toUpperCase();

    // Collected or cancelled: nothing left to do.
    if (status == 'COMPLETED' || status == 'CANCELLED' ||
        status == 'ABANDONED') {
      return Row(
        children: [
          Icon(
              status == 'COMPLETED'
                  ? Icons.check_circle_outline
                  : Icons.cancel_outlined,
              size: 18,
              color: status == 'COMPLETED'
                  ? theme.colorScheme.primary
                  : theme.colorScheme.error),
          const SizedBox(width: 8),
          Text(
            status == 'COMPLETED'
                ? 'Collected${order.collectedPaymentMethod != null ? ' · '
                    '${order.collectedPaymentMethod!.toUpperCase()}' : ''}'
                : (status == 'ABANDONED' ? 'No-show' : 'Cancelled'),
            style: theme.textTheme.labelLarge,
          ),
        ],
      );
    }

    // -------------------- awaiting the human decision --------------------
    if (order.isPending) {
      return Column(
        crossAxisAlignment: CrossAxisAlignment.stretch,
        children: [
          if (order.isUpiManual)
            // THE SENTENCE THAT MATTERS. Staff must check their own UPI app
            // for the EXACT amount — not trust the customer's word, which is
            // all payment_claimed_at is.
            Padding(
              padding: const EdgeInsets.only(bottom: 10),
              child: Text(
                'Customer says paid ₹${order.totalAmount.toStringAsFixed(0)}. '
                'Check your UPI app for exactly '
                '₹${order.totalAmount.toStringAsFixed(0)}',
                key: const Key('upi_check_your_app'),
                style: theme.textTheme.titleSmall
                    ?.copyWith(color: theme.colorScheme.error),
              ),
            ),
          if (order.isPayAtPickup && order.needsCall)
            Padding(
              padding: const EdgeInsets.only(bottom: 10),
              child: Text(
                'Call the customer to confirm before you start cooking.',
                key: const Key('pickup_call_first'),
                style: theme.textTheme.bodySmall,
              ),
            ),
          Row(
            children: [
              Expanded(
                child: FilledButton.icon(
                  key: const Key('order_accept'),
                  onPressed: _busy ? null : () => _accept(context),
                  icon: const Icon(Icons.check, size: 18),
                  label: Text(order.isUpiManual
                      ? 'Accept — amount received'
                      : 'Accept'),
                ),
              ),
            ],
          ),
          const SizedBox(height: 8),
          if (order.isUpiManual)
            OutlinedButton.icon(
              key: const Key('order_payment_not_received'),
              onPressed: _busy ? null : () => _rejectUpi(context, 'not_received'),
              icon: Icon(Icons.money_off, size: 18,
                  color: theme.colorScheme.error),
              label: Text('Payment not received',
                  style: TextStyle(color: theme.colorScheme.error)),
            ),
          if (order.isUpiManual) const SizedBox(height: 8),
          OutlinedButton.icon(
            key: const Key('order_cannot_make'),
            onPressed: _busy
                ? null
                : () => order.isUpiManual
                    ? _rejectUpi(context, 'cannot_make')
                    : _reject(),
            icon: const Icon(Icons.block, size: 18),
            label: const Text("Can't make this"),
          ),
        ],
      );
    }

    // ------------------- accepted: cooking, then handover ----------------
    return Column(
      crossAxisAlignment: CrossAxisAlignment.stretch,
      children: [
        Row(
          children: [
            Icon(order.isPaid ? Icons.verified : Icons.payments_outlined,
                size: 18,
                color: order.isPaid
                    ? theme.colorScheme.primary
                    : const Color(0xFFB26A00)),
            const SizedBox(width: 8),
            Expanded(
              child: Text(
                order.isPaid
                    ? 'Paid${order.collectedPaymentMethod != null ? ' · '
                        '${order.collectedPaymentMethod!.toUpperCase()}' : ''}'
                    : '₹${order.amountDue.toStringAsFixed(0)} to collect',
                key: const Key('order_amount_due'),
                style: theme.textTheme.labelLarge,
              ),
            ),
          ],
        ),
        // Pay-at-pickup takes money at handover, so it gets the combined
        // "paid and handed over" action. A direct-UPI order is already paid by
        // this point and completes through the ordinary code box below.
        if (order.isPayAtPickup && !order.isPaid) ...[
          const SizedBox(height: 10),
          FilledButton.icon(
            key: const Key('order_paid_and_handed_over'),
            onPressed: _busy ? null : () => _collect(context),
            icon: const Icon(Icons.done_all, size: 18),
            label: const Text('Paid and handed over'),
          ),
        ],
        if (status == 'READY' || status == 'PREPARING') ...[
          const SizedBox(height: 8),
          OutlinedButton.icon(
            key: const Key('order_no_show'),
            onPressed: _busy ? null : () => _noShow(context),
            icon: const Icon(Icons.person_off_outlined, size: 18),
            label: const Text('No-show'),
          ),
        ],
      ],
    );
  }

  @override
  Widget build(BuildContext context) {
    final theme = Theme.of(context);
    final status = widget.order.status.toUpperCase();

    // Pay-at-pickup and direct UPI have their own action set: there is a human
    // decision to make, money to take at the counter, and a no-show to record.
    if (!widget.order.isPrepaid) return _nonGatewayActions(context);

    if (status == 'CANCELLED') {
      return Row(
        children: [
          Icon(Icons.cancel, size: 18, color: theme.colorScheme.error),
          const SizedBox(width: 8),
          Text('Rejected',
              style: theme.textTheme.labelLarge
                  ?.copyWith(color: theme.colorScheme.error)),
        ],
      );
    }

    if (!widget.order.isPaid) {
      // Unpaid orders are simply not actionable now: nothing here can make them
      // paid, and the gateway will say so when it happens.
      return Row(
        children: [
          Icon(Icons.hourglass_empty, size: 18, color: theme.colorScheme.outline),
          const SizedBox(width: 8),
          Expanded(
            child: Text('Awaiting payment — confirms automatically.',
                style: theme.textTheme.bodySmall),
          ),
        ],
      );
    }

    return Row(
      children: [
        Icon(Icons.verified, size: 18, color: theme.colorScheme.primary),
        const SizedBox(width: 8),
        Text('Paid',
            style: theme.textTheme.labelLarge
                ?.copyWith(color: theme.colorScheme.primary)),
        const Spacer(),
        if (_canReject)
          TextButton.icon(
            onPressed: _busy ? null : _reject,
            icon: _busy
                ? const SizedBox(
                    height: 16, width: 16,
                    child: CircularProgressIndicator(strokeWidth: 2))
                : Icon(Icons.block, size: 18, color: theme.colorScheme.error),
            label: Text('Reject',
                style: TextStyle(color: theme.colorScheme.error)),
          )
        else
          Text('Too late to reject', style: theme.textTheme.bodySmall),
      ],
    );
  }
}

/// Tick several items, mark them all unavailable in one action.
///
/// The server writes one event and fires one push PER item, so the customer is
/// told exactly which dish is off. Does NOT change the order total — the paid
/// order stands, and the customer's remedy is a fresh order for replacements.
class ItemUnavailableChecklist extends StatefulWidget {
  final Order order;
  const ItemUnavailableChecklist({super.key, required this.order});

  @override
  State<ItemUnavailableChecklist> createState() => _ItemUnavailableChecklistState();
}

class _ItemUnavailableChecklistState extends State<ItemUnavailableChecklist> {
  final Set<String> _selected = {};
  bool _busy = false;

  Future<void> _submit() async {
    if (_selected.isEmpty) return;
    final n = _selected.length;
    setState(() => _busy = true);
    final err = await context
        .read<OrdersState>()
        .markItemsUnavailable(widget.order.orderId, _selected.toList());
    if (!mounted) return;
    setState(() {
      _busy = false;
      if (err == null) _selected.clear();
    });
    ScaffoldMessenger.of(context)
      ..hideCurrentSnackBar()
      ..showSnackBar(SnackBar(
        content: Text(err ??
            (n == 1
                ? 'Item marked unavailable. Customer notified.'
                : '$n items marked unavailable. Customer notified for each.')),
      ));
  }

  /// Mirrors the server's COMPOSITION_LOCKED_STATUSES. Once the food is made,
  /// telling the customer an item "won't be prepared" is false — it already
  /// was. The server rejects this with a 409 regardless; disabling here just
  /// stops staff tapping something that cannot work.
  static const _locked = {
    'READY', 'COMPLETED', 'PICKED_UP', 'CANCELLED', 'ABANDONED',
  };

  bool get _pastCutoff => _locked.contains(widget.order.status.toUpperCase());

  @override
  Widget build(BuildContext context) {
    final theme = Theme.of(context);
    final items = widget.order.items;
    if (items.isEmpty) return const SizedBox.shrink();

    if (_pastCutoff) {
      return Row(
        children: [
          Icon(Icons.lock_clock, size: 16, color: theme.colorScheme.outline),
          const SizedBox(width: 8),
          Expanded(
            child: Text(
              'Too late to mark items unavailable — this order is already '
              '${widget.order.status.toLowerCase()}.',
              style: theme.textTheme.bodySmall,
            ),
          ),
        ],
      );
    }

    return Column(
      crossAxisAlignment: CrossAxisAlignment.start,
      children: [
        Text("Can't make something?", style: theme.textTheme.titleSmall),
        const SizedBox(height: 2),
        Text(
          'Tick the items you cannot prepare. The customer is told which ones, '
          'and can reorder separately.',
          style: theme.textTheme.bodySmall,
        ),
        const SizedBox(height: 4),
        ...items.map((it) => CheckboxListTile(
              dense: true,
              contentPadding: EdgeInsets.zero,
              controlAffinity: ListTileControlAffinity.leading,
              value: _selected.contains(it.id),
              onChanged: _busy
                  ? null
                  : (v) => setState(() {
                        if (v == true) {
                          _selected.add(it.id);
                        } else {
                          _selected.remove(it.id);
                        }
                      }),
              title: Text('${it.quantity}x  ${it.name}'),
            )),
        Align(
          alignment: Alignment.centerRight,
          child: FilledButton.tonalIcon(
            onPressed: (_busy || _selected.isEmpty) ? null : _submit,
            icon: _busy
                ? const SizedBox(
                    height: 16, width: 16,
                    child: CircularProgressIndicator(strokeWidth: 2))
                : const Icon(Icons.remove_shopping_cart_outlined, size: 18),
            label: Text(_selected.isEmpty
                ? 'Mark unavailable'
                : 'Mark ${_selected.length} unavailable'),
          ),
        ),
      ],
    );
  }
}

/// Small PAID/UNPAID indicator in the card header.
class _PayChip extends StatelessWidget {
  final bool paid;
  const _PayChip({required this.paid});

  @override
  Widget build(BuildContext context) {
    final theme = Theme.of(context);
    final color = paid ? theme.colorScheme.primary : const Color(0xFFB26A00);
    return Container(
      padding: const EdgeInsets.symmetric(horizontal: 8, vertical: 2),
      decoration: BoxDecoration(
        color: color.withValues(alpha: 0.10),
        borderRadius: BorderRadius.circular(6),
      ),
      child: Text(
        paid ? 'PAID' : 'UNPAID',
        style: theme.textTheme.labelSmall
            ?.copyWith(color: color, fontWeight: FontWeight.w700),
      ),
    );
  }
}

/// "Left X min ago" / "At the restaurant" — whether the customer has left
/// home and whether they have reached the outlet, read straight off server
/// timestamps already carried on the order.
class _ArrivalChip extends StatelessWidget {
  final String label;
  final bool arrived;

  const _ArrivalChip({required this.label, required this.arrived});

  @override
  Widget build(BuildContext context) {
    final theme = Theme.of(context);
    final color = arrived ? theme.colorScheme.primary : theme.colorScheme.outline;
    return Row(
      mainAxisSize: MainAxisSize.min,
      children: [
        Icon(arrived ? Icons.storefront : Icons.directions_walk,
            size: 14, color: color),
        const SizedBox(width: 4),
        Text(
          label,
          key: const Key('order_arrival_chip'),
          style: theme.textTheme.bodySmall?.copyWith(color: color),
        ),
      ],
    );
  }
}

class _StatusChip extends StatelessWidget {
  final String status;
  final bool locked;

  const _StatusChip({required this.status, required this.locked});

  @override
  Widget build(BuildContext context) {
    final theme = Theme.of(context);
    final label = locked ? 'LOCKED' : status.toUpperCase();
    final color = locked
        ? theme.colorScheme.error
        : theme.colorScheme.primary;
    return Container(
      padding: const EdgeInsets.symmetric(horizontal: 8, vertical: 2),
      decoration: BoxDecoration(
        color: color.withValues(alpha: 0.10),
        borderRadius: BorderRadius.circular(6),
      ),
      child: Text(
        label,
        style: theme.textTheme.labelSmall?.copyWith(
          color: color,
          fontWeight: FontWeight.w700,
        ),
      ),
    );
  }
}

/// Who to call, and the button that calls them.
///
/// Rendered only when the server is still returning the contact — it
/// suppresses it once the visibility window closes and nulls it for good on
/// redaction, so this widget never has to decide. [Order.contactVisible] is
/// that answer.
class _ContactRow extends StatelessWidget {
  const _ContactRow({required this.order});

  final Order order;

  Future<void> _call(BuildContext context) async {
    final uri = order.telUri;
    if (uri == null) return;
    final ok = await launchUrl(uri);
    if (!ok && context.mounted) {
      ScaffoldMessenger.of(context).showSnackBar(
        const SnackBar(content: Text('Could not open the dialer.')),
      );
    }
    if (context.mounted) {
      // Record the attempt so the queue stops nagging and the customer-facing
      // state moves to CALLED. Best-effort: a failed log must not stop a call
      // that has already been placed.
      await context.read<OrdersState>().logCall(order.orderId);
    }
  }

  @override
  Widget build(BuildContext context) {
    final theme = Theme.of(context);
    final name = order.contactFirstName?.trim();
    final phone = order.contactPhone?.trim();

    return Row(
      children: [
        Icon(Icons.person_outline, size: 18, color: theme.colorScheme.primary),
        const SizedBox(width: 8),
        Expanded(
          child: Column(
            crossAxisAlignment: CrossAxisAlignment.start,
            children: [
              Text(
                (name == null || name.isEmpty) ? 'Customer' : name,
                key: const Key('order_contact_name'),
                style: theme.textTheme.titleSmall,
              ),
              if (phone != null && phone.isNotEmpty)
                Text(phone,
                    key: const Key('order_contact_phone'),
                    style: theme.textTheme.bodySmall),
            ],
          ),
        ),
        if (order.telUri != null)
          FilledButton.tonalIcon(
            key: const Key('order_call_button'),
            onPressed: () => _call(context),
            icon: const Icon(Icons.call, size: 18),
            label: Text(order.callAttempts > 0
                ? 'Call again (${order.callAttempts})'
                : 'Call'),
          ),
      ],
    );
  }
}

/// "Refund ₹X to the customer yourself."
///
/// The wording is the point. CareVo was never in the path of a direct-UPI
/// payment and cannot reverse it, so a banner saying "a refund is being
/// arranged" — the gateway copy — would promise something nobody can send. It
/// names the amount and puts the action on the person who holds the money.
class _ManualRefundBanner extends StatelessWidget {
  const _ManualRefundBanner({required this.order});

  final Order order;

  @override
  Widget build(BuildContext context) {
    final theme = Theme.of(context);
    return Container(
      key: const Key('manual_refund_banner'),
      padding: const EdgeInsets.all(12),
      decoration: BoxDecoration(
        color: theme.colorScheme.errorContainer,
        borderRadius: BorderRadius.circular(8),
      ),
      child: Row(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          Icon(Icons.currency_rupee,
              size: 18, color: theme.colorScheme.onErrorContainer),
          const SizedBox(width: 8),
          Expanded(
            child: Column(
              crossAxisAlignment: CrossAxisAlignment.start,
              children: [
                Text(
                  'Refund ₹${order.totalAmount.toStringAsFixed(0)} to the '
                  'customer yourself',
                  key: const Key('manual_refund_text'),
                  style: theme.textTheme.titleSmall?.copyWith(
                      color: theme.colorScheme.onErrorContainer),
                ),
                const SizedBox(height: 2),
                Text(
                  'They paid you directly by UPI, so CareVo cannot refund it. '
                  'Send it back from your UPI app.',
                  style: theme.textTheme.bodySmall?.copyWith(
                      color: theme.colorScheme.onErrorContainer),
                ),
                // THE EXPIRY CASE ONLY. The claim was never checked, so unlike
                // a 'cannot_make' refund the owner does not yet know whether
                // the money arrived — and the first useful thing they can do
                // is look. An order they themselves cancelled after
                // confirming the payment gets the plain banner above and
                // nothing extra, because there is nothing left to check.
                if (order.refundFromMissedClaim) ...[
                  const SizedBox(height: 8),
                  Text(
                    'The customer said they paid but you did not confirm in '
                    'time. Check your UPI app.',
                    key: const Key('manual_refund_missed_claim_text'),
                    style: theme.textTheme.bodySmall?.copyWith(
                        color: theme.colorScheme.onErrorContainer,
                        fontWeight: FontWeight.w600),
                  ),
                ],
              ],
            ),
          ),
        ],
      ),
    );
  }
}
