import 'package:flutter/material.dart';
import 'package:provider/provider.dart';

import '../models/order.dart';
import '../state/auth_state.dart';
import '../state/orders_state.dart';
import '../widgets/order_card.dart';
import '../widgets/pickup_lookup_card.dart';

/// The Pickup screen: the code entry for handover, above the live prep queue.
///
/// ## What is NOT on this screen
///
/// The pickup code appears in exactly one place in this app — the box staff
/// type it INTO. It is never rendered in a row, never in a detail panel, and
/// never logged. The backend holds the same line: `GET /pos/orders` does not
/// return the field at all (`OwnerOrderOut`, schema.py:603), so there is no
/// value here to accidentally print. A row that displayed the code would turn
/// the handover check into theatre — anyone glancing at the counter tablet
/// could read it off and collect someone else's order.
class OrdersScreen extends StatelessWidget {
  const OrdersScreen({super.key});

  @override
  Widget build(BuildContext context) {
    // The code lookup sits above the queue and outside its loading/error
    // branches: staff at the counter with a customer in front of them need it
    // even when the feed is mid-refresh or failed to load, and it does not
    // read the queue to do its job.
    return Column(
      children: [
        const PickupLookupCard(),
        Expanded(child: _Queue()),
      ],
    );
  }
}

class _Queue extends StatelessWidget {
  static const Key emptyKey = Key('orders_queue_empty');
  static const Key errorKey = Key('orders_queue_error');
  static const Key retryKey = Key('orders_queue_retry');
  static const Key listKey = Key('orders_queue_list');

  @override
  Widget build(BuildContext context) {
    final state = context.watch<OrdersState>();

    // An expired token routes to login instead of offering a Retry that cannot
    // work. Deferred to after this frame because logout() notifies listeners,
    // and flipping the auth gate during a build of the widget it would replace
    // throws. _Root watches AuthState.loggedIn, so clearing it is all that is
    // needed — there is no Navigator call to make.
    if (state.sessionExpired) {
      WidgetsBinding.instance.addPostFrameCallback((_) {
        if (!context.mounted) return;
        final orders = context.read<OrdersState>();
        if (!orders.sessionExpired) return; // already handled
        orders.clearSessionExpired();
        orders.reset();
        context.read<AuthState>().logout();
      });
      return const Center(
        key: Key('orders_queue_session_expired'),
        child: Padding(
          padding: EdgeInsets.all(24),
          child: Column(
            mainAxisSize: MainAxisSize.min,
            children: [
              Icon(Icons.lock_clock, size: 40),
              SizedBox(height: 12),
              Text(
                'Your session has expired. Signing you in again…',
                textAlign: TextAlign.center,
              ),
            ],
          ),
        ),
      );
    }

    final orders = state.activeOrders;

    if (state.loading && orders.isEmpty) {
      return const Center(child: CircularProgressIndicator());
    }

    if (state.error != null && orders.isEmpty) {
      return Center(
        key: errorKey,
        child: Padding(
          padding: const EdgeInsets.all(24),
          child: Column(
            mainAxisSize: MainAxisSize.min,
            children: [
              const Icon(Icons.cloud_off, size: 40),
              const SizedBox(height: 12),
              Text(state.error!, textAlign: TextAlign.center),
              const SizedBox(height: 16),
              FilledButton.tonal(
                key: retryKey,
                onPressed: () => context.read<OrdersState>().load(),
                child: const Text('Retry'),
              ),
            ],
          ),
        ),
      );
    }

    return RefreshIndicator(
      onRefresh: () => context.read<OrdersState>().load(),
      child: orders.isEmpty
          ? ListView(
              key: emptyKey,
              children: const [
                SizedBox(height: 100),
                Icon(Icons.restaurant_outlined, size: 40),
                SizedBox(height: 12),
                Center(
                  child: Padding(
                    padding: EdgeInsets.symmetric(horizontal: 32),
                    child: Text(
                      'Nothing to prepare right now.\n'
                      'New paid orders appear here automatically.',
                      textAlign: TextAlign.center,
                    ),
                  ),
                ),
              ],
            )
          : ListView.builder(
              key: listKey,
              padding: const EdgeInsets.symmetric(vertical: 8),
              itemCount: orders.length,
              // Oldest first: the queue is a work order, and the customer who
              // has waited longest is the next thing to make.
              itemBuilder: (context, i) => _QueueEntry(order: orders[i]),
            ),
    );
  }
}

/// One row: the at-a-glance summary line, then the existing [OrderCard], which
/// owns tap-to-expand and the code-gated handover.
///
/// The summary is a SEPARATE widget rather than more fields inside OrderCard so
/// the Orders tab's card is untouched — this screen adds a line above it, it
/// does not fork the card.
class _QueueEntry extends StatelessWidget {
  final Order order;

  const _QueueEntry({required this.order});

  static Key summaryKeyFor(String orderId) => Key('queue_summary_$orderId');

  @override
  Widget build(BuildContext context) {
    final theme = Theme.of(context);
    final placed = order.placedLabel;
    final waited = order.minutesSincePlaced;

    return Column(
      crossAxisAlignment: CrossAxisAlignment.stretch,
      children: [
        Padding(
          key: summaryKeyFor(order.orderId),
          padding: const EdgeInsets.fromLTRB(26, 10, 26, 0),
          child: Row(
            children: [
              Icon(Icons.schedule, size: 14, color: theme.colorScheme.outline),
              const SizedBox(width: 6),
              Expanded(
                child: Text(
                  _summaryLine(placed, waited),
                  style: theme.textTheme.bodySmall
                      ?.copyWith(color: theme.colorScheme.outline),
                ),
              ),
            ],
          ),
        ),
        OrderCard(order: order),
      ],
    );
  }

  /// "Placed 14:32 · waiting 7m · pickup time not sent by server".
  ///
  /// The pickup-time clause is explicit rather than a bare "—" because a dash
  /// reads as "no pickup time was requested", which would be a claim this app
  /// cannot make: `GET /pos/orders` does not return `requested_pickup_at` at
  /// all, so an ASAP order and a 7:30pm scheduled order are indistinguishable
  /// from here. Saying so is the honest version. Customer first name is absent
  /// for the same reason — the endpoint is deliberately name-free.
  static String _summaryLine(String? placed, int? waited) {
    final parts = <String>[
      placed == null ? 'Placed time unavailable' : 'Placed $placed',
      if (waited != null) 'waiting ${waited}m',
      'pickup time not sent by server',
    ];
    return parts.join('  ·  ');
  }
}
