import 'dart:async';

import 'package:flutter/material.dart';
import 'package:google_fonts/google_fonts.dart';
import 'package:provider/provider.dart';

import '../services/api_client.dart';
import '../services/customer_service.dart';
import '../state/auth_state.dart';
import '../state/cart_state.dart';
import '../theme/app_colors.dart';
import '../theme/app_theme.dart';
import '../theme/widgets/neo_button.dart';
import '../theme/widgets/neo_card.dart';
import '../theme/widgets/page_header.dart';
import '../widgets/account_button.dart';
import '../widgets/active_order_card.dart';
import 'cart_screen.dart';
import 'location_screen.dart';
import 'name_capture_screen.dart';
import 'order_history_screen.dart';
import 'pickup_screen.dart';

/// The authenticated app's front door.
///
/// ## Why this screen exists
///
/// Signing in used to land straight on the location/city picker. That made a
/// permission-and-geography question the first thing the app said to everyone,
/// including someone opening it to check a pickup code for an order they had
/// already placed — who had to answer "where are you?" before reaching
/// something they already owned.
///
/// Home is the landing surface; choosing a location is now one thing you can do
/// FROM it, behind an explicit "Find restaurants near you". See
/// [LocationScreen], which is that step and is titled Discover.
///
/// ## Location is not touched here
///
/// Deliberately, and not merely as a default. `LocationService` raises at most
/// one permission dialog per grant state, so whichever caller asks first spends
/// it. Every existing caller is explicitly user-triggered — "Near me" on
/// Discover, "Use my location" at checkout, the departure ping on the pickup
/// screen — and each asks at a moment where the customer can see what the
/// answer is for. Prompting on Home load would spend that one dialog on a
/// screen with nothing to show for it, and hand the later callers a refusal
/// they never earned. Home also has nothing to render from coordinates:
/// distance is computed server-side by `/customer/outlets`, which only Discover
/// calls.
///
/// ## Home does NOT gate on the name
///
/// It used to render [NameCaptureScreen] in place of itself whenever
/// `customer.name` was empty. That gate was removed: name capture now happens
/// once, straight after signup, in `routeAfterAuth`. Home renders Home.
///
class HomeScreen extends StatefulWidget {
  const HomeScreen({super.key});

  static const routeName = '/home';

  @override
  State<HomeScreen> createState() => _HomeScreenState();
}

class _HomeScreenState extends State<HomeScreen> {
  List<OrderHistoryEntry>? _orders;
  String? _error;

  @override
  void initState() {
    super.initState();
    _load();
  }

  /// Orders decide which Home this is, so they are fetched before the screen
  /// commits to a layout. The name is a nicety fetched alongside; a failure
  /// there costs the greeting a name and nothing else.
  Future<void> _load() async {
    final svc = context.read<CustomerService>();
    final auth = context.read<AuthState>();
    setState(() => _error = null);

    // Only requested when the session has no cached customer — the usual cold
    // start with a restored token. After a fresh sign-in it is already there.
    //
    // Not awaited, and its failure is swallowed: the greeting falls back to the
    // nameless form, which is not worth interrupting anyone about, and it must
    // never delay the orders lookup that actually decides this screen.
    if (auth.customer == null) {
      unawaited(svc.me().then(
        (customer) {
          if (mounted) auth.setCustomer(customer);
        },
        onError: (_) {},
      ));
    }

    try {
      final orders = await svc.orders(limit: 20);
      if (!mounted) return;
      setState(() => _orders = orders);
    } on ApiException catch (e) {
      if (!mounted) return;
      setState(() {
        _error = e.message;
        // An empty list, NOT the first-run screen: see the guard in build().
        _orders = const [];
      });
    } catch (_) {
      if (!mounted) return;
      setState(() {
        _error = 'Could not reach the server.';
        _orders = const [];
      });
    }
  }

  void _openDiscover() {
    Navigator.of(context)
        .push(MaterialPageRoute(builder: (_) => const LocationScreen()));
  }

  void _openHistory() {
    Navigator.of(context)
        .push(MaterialPageRoute(builder: (_) => const OrderHistoryScreen()))
        // History can complete an order, which changes what Home should show.
        .then((_) => _load());
  }

  /// Straight to the live pickup screen for one specific order.
  ///
  /// The same push [ActiveOrderCard] makes from the restaurant-list banner —
  /// deliberately identical, down to `fromHistory: true`, so an order opened
  /// from Home behaves exactly like the same order opened from anywhere else:
  /// it gets a back button, and "Order more" does not detonate the nav stack.
  void _openPickup(OrderHistoryEntry order) {
    Navigator.of(context)
        .push(MaterialPageRoute(
          builder: (_) => PickupScreen(
            orderId: order.orderId,
            amount: order.totalAmount,
            fromHistory: true,
          ),
        ))
        // It may have been collected in there, which moves it out of the
        // active section.
        .then((_) {
      if (mounted) _load();
    });
  }

  /// Straight to the cart — not via the restaurant's menu.
  ///
  /// The cart screen is self-contained (it reads CartState, which already
  /// knows its outlet), so there is no need to rebuild the menu stack
  /// underneath it. Back from here returns to Home, which is where the
  /// customer came from.
  void _openCart() {
    Navigator.of(context)
        .push(MaterialPageRoute(builder: (_) => const CartScreen()))
        .then((_) {
      // They may have checked out from in there, which turns a cart into an
      // order — both sections of Home need re-evaluating.
      if (mounted) _load();
    });
  }

  @override
  Widget build(BuildContext context) {
    // NO name gate here any more. It used to render NameCaptureScreen in place
    // of Home whenever `customer.name` was empty, which made two gates on two
    // different conditions — this one, and the post-signup one in
    // `routeAfterAuth`. A customer should meet exactly one name prompt, so the
    // routing gate is now the only one; see post_auth_router.dart for why that
    // is the better of the two conditions.
    final orders = _orders;

    return Scaffold(
      appBar: AppBar(
        title: const Text('Gusto Skip'),
        actions: careVoActions(),
      ),
      body: SafeArea(
        child: orders == null
            ? const Center(child: CircularProgressIndicator())
            : RefreshIndicator(
                onRefresh: _load,
                // A customer with NO orders and a FAILED lookup is not a
                // first-time customer — the app just doesn't know yet. Showing
                // the first-run screen on a network error would tell a regular
                // user their history had vanished, so an errored load keeps the
                // returning layout and shows the error inside it.
                child: (orders.isEmpty && _error == null)
                    ? _FirstRunHome(
                        onDiscover: _openDiscover,
                        onResumeCart: _openCart,
                      )
                    : _ReturningHome(
                        orders: orders,
                        error: _error,
                        onDiscover: _openDiscover,
                        onHistory: _openHistory,
                        onTrackOrder: _openPickup,
                        onResumeCart: _openCart,
                        onRefresh: _load,
                      ),
              ),
      ),
    );
  }
}

/// Greeting for someone who has ordered before.
///
/// Time-of-day rather than a static "Hello": this app is used at meal times and
/// the greeting is the one place the screen can acknowledge that cheaply.
String _greeting(String? name) => greetingFor(DateTime.now().hour, name);

/// The greeting text for a given local hour (0–23) and optional name.
///
/// Split out and made pure so the banding is testable — `DateTime.now()` cannot
/// be pinned to a specific hour in a widget test. The caller passes
/// `DateTime.now().hour`, which is the DEVICE's local time in Dart: the time
/// source was never the bug. The bug was the banding — `hour < 12` swept
/// 00:00–04:59 into "Good morning", so opening the app at midnight was greeted
/// as morning. Morning now starts at 05:00; the small hours fall through to
/// "Good evening", the conventional late catch-all.
@visibleForTesting
String greetingFor(int hour, String? name) {
  final String part;
  if (hour >= 5 && hour < 12) {
    part = 'Good morning';
  } else if (hour >= 12 && hour < 17) {
    part = 'Good afternoon';
  } else {
    part = 'Good evening';
  }
  final trimmed = name?.trim() ?? '';
  return trimmed.isEmpty ? part : '$part, $trimmed';
}

// ---------------------------------------------------------------------------
// Returning customer
// ---------------------------------------------------------------------------

/// Home for a customer with order history: greeting, an unfinished cart, the
/// CTA, and links into live and past orders.
///
/// Order of the sections is the order of urgency: an in-progress CART is the
/// one thing here the customer was actively in the middle of, so it sits
/// closest to the top.
///
/// ## Two separate small elements, not one big card
///
/// The resume-cart banner and the order links are DIFFERENT things and both
/// belong here:
///
///  * **Resume cart** — items chosen but not paid for. Actionable right now,
///    and the state most easily lost (it survives cold start, but nothing on
///    Home used to point at it, so it was invisible until you navigated back
///    into a menu).
///  * **Order links** — orders already placed. The big per-order ticket cards
///    that used to sit here were replaced by a compact link: they took most of
///    the first screen, and Home is not where an order is tracked — the pickup
///    screen is, and history is one tap away.
class _ReturningHome extends StatelessWidget {
  const _ReturningHome({
    required this.orders,
    required this.error,
    required this.onDiscover,
    required this.onHistory,
    required this.onTrackOrder,
    required this.onResumeCart,
    required this.onRefresh,
  });

  final List<OrderHistoryEntry> orders;
  final String? error;
  final VoidCallback onDiscover;
  final VoidCallback onHistory;
  final void Function(OrderHistoryEntry) onTrackOrder;
  final VoidCallback onResumeCart;
  final Future<void> Function() onRefresh;

  @override
  Widget build(BuildContext context) {
    final c = AppColors.of(context);
    final textTheme = Theme.of(context).textTheme;
    final name = context.watch<AuthState>().customer?.name;
    final active = orders.where((o) => o.isActive).toList();
    final past = orders.where((o) => !o.isActive).toList();
    // Watched: adding to the cart elsewhere and coming back must light this up
    // without Home refetching anything.
    final cart = context.watch<CartState>();

    return ListView(
      padding: const EdgeInsets.fromLTRB(20, 8, 20, 32),
      children: [
        PageHeader(_greeting(name)),
        const SizedBox(height: 6),
        Text(
          active.isEmpty
              ? 'Ready when you are.'
              : '${active.length == 1 ? 'You have an order' : 'You have ${active.length} orders'} '
                  'in progress.',
          style: textTheme.bodyLarge?.copyWith(color: c.inkSoft),
        ),
        const SizedBox(height: 20),

        if (error != null) ...[
          _HomeErrorBanner(message: error!, onRetry: onRefresh),
          const SizedBox(height: 16),
        ],

        // ---- resume an unfinished cart ----
        // Rendered only when there is actually something to resume. An empty
        // cart gets no banner at all rather than a disabled one — there is
        // nothing to explain and nothing to come back to.
        if (!cart.isEmpty) ...[
          _ResumeCartBanner(cart: cart, onTap: onResumeCart),
          const SizedBox(height: 20),
        ],

        // ---- live orders: a LINK, not the full ticket cards ----
        if (active.isNotEmpty) ...[
          _ActiveOrdersLink(
            count: active.length,
            // ONE active order has an unambiguous destination — its own live
            // pickup screen — so it goes there directly. It used to be handed
            // `onHistory`, the SAME callback as the "Order history" row below
            // it, which made the two rows duplicates: a customer who tapped
            // "1 order in progress" wanting their code got the history list
            // and had to find and tap the order again.
            //
            // With SEVERAL live at once there is no single right order to
            // open, and guessing (newest? nearest? the one with a code?) would
            // be wrong often enough to be worse than the extra tap — so the
            // multi-order case keeps going to history, which floats the active
            // ones to the top and opens the same pickup screen per row.
            onTap: active.length == 1
                ? () => onTrackOrder(active.single)
                : onHistory,
          ),
          const SizedBox(height: 20),
        ],

        // ---- the CTA ----
        NeoButton(
          key: const Key('home_find_restaurants'),
          label: 'Find restaurants near you',
          icon: Icons.storefront,
          onPressed: onDiscover,
        ),
        const SizedBox(height: 20),

        // ---- history shortcut ----
        NeoCard(
          key: const Key('home_history_shortcut'),
          onTap: onHistory,
          child: Row(
            children: [
              Container(
                padding: const EdgeInsets.all(10),
                decoration: BoxDecoration(
                  color: c.surfaceAlt,
                  borderRadius: BorderRadius.circular(10),
                  border: Border.all(color: c.border, width: 2),
                ),
                child: Icon(Icons.receipt_long_outlined, color: c.ink),
              ),
              const SizedBox(width: 14),
              Expanded(
                child: Column(
                  crossAxisAlignment: CrossAxisAlignment.start,
                  children: [
                    Text('Order history', style: textTheme.titleMedium),
                    const SizedBox(height: 2),
                    Text(
                      // The most recent completed order, so the row carries a
                      // fact rather than only a label.
                      past.isEmpty
                          ? 'Your past orders'
                          : 'Last: ${past.first.outletName ?? 'an outlet'}',
                      style: textTheme.bodySmall?.copyWith(color: c.inkSoft),
                      maxLines: 1,
                      overflow: TextOverflow.ellipsis,
                    ),
                  ],
                ),
              ),
              Icon(Icons.chevron_right, color: c.inkSoft),
            ],
          ),
        ),
        const SizedBox(height: 18),
        Row(
          children: [
            Icon(Icons.storefront_outlined, size: 16, color: c.inkSoft),
            const SizedBox(width: 8),
            Expanded(
              child: Text(
                'All orders are self-pickup — no delivery, no waiting.',
                style: textTheme.bodySmall?.copyWith(color: c.inkSoft),
              ),
            ),
          ],
        ),
        // WalkingFooter unmounted with the Gusto rename: the walk-cycle art
        // carries a bag printed "Carevo". The widget, its tests and the GIF are
        // all still in the tree — remount here once the art is redrawn.
      ],
    );
  }
}

/// "Continue where you left off" — an unpaid cart, surfaced on Home.
///
/// The cart already survived navigation and cold start (that was the previous
/// batch's persistence fix); what it did not have was anywhere to be SEEN from.
/// Reaching it meant navigating back into the right restaurant's menu, so a
/// basket someone had already built was effectively invisible from the front
/// door. This is display only — it adds no state and changes none.
///
/// Names the restaurant, because a cart belongs to exactly one outlet and
/// "continue your order" without saying whose is a question, not a prompt.
class _ResumeCartBanner extends StatelessWidget {
  const _ResumeCartBanner({required this.cart, required this.onTap});

  final CartState cart;
  final VoidCallback onTap;

  @override
  Widget build(BuildContext context) {
    final c = AppColors.of(context);
    final textTheme = Theme.of(context).textTheme;
    final count = cart.totalQuantity;
    final outletName = cart.outlet?.name;

    return NeoCard(
      key: const Key('home_resume_cart'),
      color: c.accent,
      onTap: onTap,
      child: Row(
        children: [
          Container(
            padding: const EdgeInsets.all(10),
            decoration: BoxDecoration(
              color: c.surface,
              borderRadius: BorderRadius.circular(10),
              border: Border.all(color: c.border, width: 2),
            ),
            child: Icon(Icons.shopping_bag_outlined, color: c.primary),
          ),
          const SizedBox(width: 14),
          Expanded(
            child: Column(
              crossAxisAlignment: CrossAxisAlignment.start,
              children: [
                Text(
                  'Continue where you left off',
                  style: textTheme.titleMedium?.copyWith(color: c.onAccent),
                ),
                const SizedBox(height: 2),
                Text(
                  outletName == null
                      ? '$count ${count == 1 ? 'item' : 'items'} in your cart'
                      : '$count ${count == 1 ? 'item' : 'items'} from '
                          '$outletName',
                  style: textTheme.bodySmall?.copyWith(color: c.onAccent),
                  maxLines: 1,
                  overflow: TextOverflow.ellipsis,
                ),
              ],
            ),
          ),
          Icon(Icons.arrow_forward, color: c.onAccent),
        ],
      ),
    );
  }
}

/// Compact link to in-progress orders.
///
/// Replaced the stack of full-size [ActiveOrderCard] tickets that used to sit
/// here. Those were the right thing on the restaurant list — where someone
/// scanning for a counter needs the code visible without tapping — but on Home
/// they consumed most of the first screen, pushing the actual purpose of the
/// screen below the fold. Home says an order EXISTS; the pickup screen is
/// where it is tracked.
///
/// The trailing text names the actual destination and therefore CHANGES with
/// [count]: one order opens that order's live screen ("Track order"), several
/// open the history list ("View order history"). It was hard-coded to the
/// history wording while both cases went there; leaving it that way after the
/// single-order case was rerouted would have made the row lie about where it
/// goes.
class _ActiveOrdersLink extends StatelessWidget {
  const _ActiveOrdersLink({required this.count, required this.onTap});

  final int count;
  final VoidCallback onTap;

  @override
  Widget build(BuildContext context) {
    final c = AppColors.of(context);
    final textTheme = Theme.of(context).textTheme;

    return NeoCard(
      key: const Key('home_active_orders_link'),
      padding: const EdgeInsets.symmetric(horizontal: 14, vertical: 12),
      onTap: onTap,
      child: Row(
        children: [
          Icon(Icons.receipt_long_outlined, size: 20, color: c.primary),
          const SizedBox(width: 12),
          Expanded(
            child: Text(
              count == 1
                  ? '1 order in progress'
                  : '$count orders in progress',
              style: textTheme.titleSmall,
            ),
          ),
          Text(count == 1 ? 'Track order' : 'View order history',
              style: textTheme.bodySmall?.copyWith(color: c.primary)),
          Icon(Icons.chevron_right, size: 18, color: c.primary),
        ],
      ),
    );
  }
}

// ---------------------------------------------------------------------------
// First run
// ---------------------------------------------------------------------------

/// Home for a customer who has never ordered.
///
/// A DIFFERENT screen, not the returning layout with its sections blanked out.
/// The returning layout is a status board — greeting, what's live, where to go
/// back to — and none of those mean anything on the first run. "You have no
/// orders in progress" and "no past orders" are two pieces of furniture whose
/// only content is the absence of content.
///
/// What a first-time customer actually needs is to know what this app does,
/// because "self-pickup, order ahead, show a code" is not guessable from a
/// restaurant list. So the space the status board would occupy is spent on a
/// three-step explanation, and there is exactly one thing to tap.
class _FirstRunHome extends StatelessWidget {
  const _FirstRunHome({required this.onDiscover, required this.onResumeCart});

  final VoidCallback onDiscover;
  final VoidCallback onResumeCart;

  @override
  Widget build(BuildContext context) {
    final c = AppColors.of(context);
    final textTheme = Theme.of(context).textTheme;
    final name = context.watch<AuthState>().customer?.name.trim() ?? '';
    // First-run means zero ORDERS, which says nothing about the cart: someone
    // who browsed, added items and closed the app before paying is still a
    // first-run customer, and is exactly who most needs the way back.
    final cart = context.watch<CartState>();

    return ListView(
      key: const Key('home_first_run'),
      padding: const EdgeInsets.fromLTRB(20, 16, 20, 32),
      children: [
        // The wordmark as a hero. The returning screen does not have this —
        // a customer on their fifth order does not need to be introduced to
        // the product, and the space is better spent on their pickup code.
        Center(
          child: Container(
            padding: const EdgeInsets.symmetric(horizontal: 22, vertical: 16),
            decoration: BoxDecoration(
              color: c.accent,
              borderRadius: BorderRadius.circular(AppTheme.radius),
              border: Border.all(color: c.border, width: AppTheme.borderWidth),
              boxShadow: [
                BoxShadow(
                    color: c.shadow, offset: const Offset(5, 5), blurRadius: 0),
              ],
            ),
            child: Text(
              'Gusto',
              style: GoogleFonts.bevan(color: c.onAccent, fontSize: 34),
            ),
          ),
        ),
        const SizedBox(height: 24),
        Text(
          name.isEmpty ? 'Welcome' : 'Welcome, $name',
          textAlign: TextAlign.center,
          style: textTheme.headlineSmall,
        ),
        const SizedBox(height: 8),
        Text(
          'Order ahead, then walk in and collect. No queue, no delivery '
          'charge, no waiting for a table.',
          textAlign: TextAlign.center,
          style: textTheme.bodyLarge?.copyWith(color: c.inkSoft),
        ),
        const SizedBox(height: 28),

        // An unfinished cart outranks the explanation: someone with items
        // already chosen has stopped needing to be told how this works.
        if (!cart.isEmpty) ...[
          _ResumeCartBanner(cart: cart, onTap: onResumeCart),
          const SizedBox(height: 28),
        ],

        // The explanation that earns this screen its existence.
        const _HowItWorksStep(
          number: '1',
          title: 'Pick a restaurant',
          body: 'Find one near you, or choose your city.',
        ),
        const SizedBox(height: 12),
        const _HowItWorksStep(
          number: '2',
          title: 'Order and pay',
          body: 'Build your order in the app and pay for it there.',
        ),
        const SizedBox(height: 12),
        const _HowItWorksStep(
          number: '3',
          title: 'Show your code',
          body: 'Collect at the counter with your pickup code. That is it.',
        ),

        const SizedBox(height: 32),
        NeoButton(
          key: const Key('home_find_restaurants'),
          label: 'Find restaurants near you',
          icon: Icons.storefront,
          onPressed: onDiscover,
        ),
        const SizedBox(height: 14),
        Text(
          'Your first order takes about a minute.',
          textAlign: TextAlign.center,
          style: textTheme.bodySmall?.copyWith(color: c.inkSoft),
        ),
        // WalkingFooter unmounted — see the note at the other mount point.
      ],
    );
  }
}

/// One numbered step in the first-run explanation.
class _HowItWorksStep extends StatelessWidget {
  const _HowItWorksStep({
    required this.number,
    required this.title,
    required this.body,
  });

  final String number;
  final String title;
  final String body;

  @override
  Widget build(BuildContext context) {
    final c = AppColors.of(context);
    final textTheme = Theme.of(context).textTheme;

    return Row(
      crossAxisAlignment: CrossAxisAlignment.start,
      children: [
        // Fixed-size numeral box, so all three titles start on the same line
        // regardless of the digit — the same fixed-column rule the menu rows
        // now follow.
        Container(
          width: 36,
          height: 36,
          alignment: Alignment.center,
          decoration: BoxDecoration(
            color: c.primary,
            borderRadius: BorderRadius.circular(10),
            border: Border.all(color: c.border, width: 2.5),
          ),
          child: Text(
            number,
            style: textTheme.titleMedium?.copyWith(
              color: c.onPrimary,
              fontWeight: FontWeight.w800,
            ),
          ),
        ),
        const SizedBox(width: 14),
        Expanded(
          child: Column(
            crossAxisAlignment: CrossAxisAlignment.start,
            children: [
              Text(title, style: textTheme.titleMedium),
              const SizedBox(height: 2),
              Text(
                body,
                style: textTheme.bodyMedium?.copyWith(color: c.inkSoft),
              ),
            ],
          ),
        ),
      ],
    );
  }
}

/// Inline failure notice for the orders lookup.
class _HomeErrorBanner extends StatelessWidget {
  const _HomeErrorBanner({required this.message, required this.onRetry});
  final String message;
  final Future<void> Function() onRetry;

  @override
  Widget build(BuildContext context) {
    final c = AppColors.of(context);
    return Container(
      padding: const EdgeInsets.all(12),
      decoration: BoxDecoration(
        color: c.surfaceAlt,
        borderRadius: BorderRadius.circular(AppTheme.radius),
        border: Border.all(color: c.border, width: 2),
      ),
      child: Row(
        children: [
          Icon(Icons.cloud_off_outlined, size: 18, color: c.inkSoft),
          const SizedBox(width: 10),
          Expanded(
            child: Text(
              "Couldn't load your orders. $message",
              style: Theme.of(context).textTheme.bodySmall,
            ),
          ),
          TextButton(onPressed: onRetry, child: const Text('Retry')),
        ],
      ),
    );
  }
}
