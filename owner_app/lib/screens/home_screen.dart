import 'package:flutter/material.dart';
import 'package:provider/provider.dart';

import '../models/menu_item.dart';
import 'package:image_picker/image_picker.dart';

import '../models/outlet.dart';
import '../services/alert_feedback.dart';
import '../services/cloudinary_service.dart';
import '../services/staff_push_service.dart';
import '../state/auth_state.dart';
import '../state/home_state.dart';
import '../state/offers_state.dart';
import '../state/orders_state.dart';
import '../widgets/dish_row.dart';
import 'change_password_screen.dart';
import 'outlet_settings_screen.dart';
import 'dish_edit_screen.dart';
import 'offers_screen.dart';
import 'orders_screen.dart';

class HomeScreen extends StatefulWidget {
  /// Injectable so a test can watch the chime/buzz without a real device.
  const HomeScreen({super.key, this.feedback = const AlertFeedback()});

  final AlertFeedback feedback;

  /// The signed-in outlet's name in the app bar. Keyed because "which
  /// restaurant is this phone?" is the whole point of it being there, and a
  /// test asserting on loose text could pass on some other label.
  static const outletNameKey = Key('home_outlet_name');

  /// The in-app new-order alert.
  static const newOrderBannerKey = Key('home_new_order_banner');

  @override
  State<HomeScreen> createState() => _HomeScreenState();
}

class _HomeScreenState extends State<HomeScreen> with WidgetsBindingObserver {
  int _index = 0;

  /// Held rather than read from `context` on demand, because both are torn down
  /// in [dispose] and an ancestor lookup there is not safe — by then the element
  /// tree is unmounting and the providers may already be gone.
  late OrdersState _orders;
  late StaffPushService _push;

  @override
  void didChangeDependencies() {
    super.didChangeDependencies();
    _orders = context.read<OrdersState>();
    _push = context.read<StaffPushService>();
  }

  @override
  void initState() {
    super.initState();
    WidgetsBinding.instance.addObserver(this);
    WidgetsBinding.instance.addPostFrameCallback((_) {
      if (!mounted) return;
      context.read<HomeState>().load();
      context.read<OffersState>().load();

      // The orders feed refreshes itself from here on: the first load takes the
      // alert baseline (the queue already on the counter is not news) and the
      // poll started after it is what makes an arrival audible.
      _orders.newOrderAlert.addListener(_onNewOrder);
      _orders.load();
      _orders.startPolling();

      // A tapped staff push (new order, or a train order due to start) lands
      // on the EXISTING Orders tab rather than a new screen.
      _push.attachTapRouting();
      _push.openOrderId.addListener(_onPushTapped);
      // A cold start from a notification sets the value before this listener
      // exists, so check once on mount too.
      if (_push.openOrderId.value != null) _onPushTapped();
    });
  }

  /// Polling follows the foreground, because the alert does.
  ///
  /// This alert is in-app only by design. Once the app is backgrounded there is
  /// no banner to show and no one watching, so continuing to poll would spend
  /// battery and Render quota for nothing. Delivery to a backgrounded app is a
  /// separate decision and is deliberately not made here.
  @override
  void didChangeAppLifecycleState(AppLifecycleState state) {
    if (!mounted) return;
    if (state == AppLifecycleState.resumed) {
      // Catch up first, then resume the cadence — an order that landed while
      // the phone was in a pocket should be on screen immediately, though it
      // stays silent: it is no longer "just arrived" by the time anyone looks.
      _orders.load(silent: true);
      _orders.startPolling();
    } else {
      _orders.stopPolling();
    }
  }

  void _onPushTapped() {
    if (!mounted) return;
    setState(() => _index = 1);           // Orders tab
    _orders.load();                       // the pushed order may be brand new
    _push.openOrderId.value = null;       // consume once
  }

  /// A paid order just appeared in the feed: chime, buzz, and say which one.
  void _onNewOrder() {
    if (!mounted) return;
    final alert = _orders.newOrderAlert.value;
    if (alert == null) return;
    _orders.consumeAlert();  // one-shot: a rebuild must not re-fire it

    widget.feedback.newOrder();

    final order = alert.order;
    final count = order.items.fold<int>(0, (sum, i) => sum + i.quantity);
    final extra = alert.alsoArrived;
    final label = 'New order #${order.shortId} — $count '
        'item${count == 1 ? '' : 's'}, ₹${order.totalAmount.toStringAsFixed(0)}'
        '${extra > 0 ? '  (+$extra more just in)' : ''}';

    ScaffoldMessenger.of(context)
      ..hideCurrentSnackBar()
      ..showSnackBar(SnackBar(
        key: HomeScreen.newOrderBannerKey,
        content: Row(
          children: [
            const Icon(Icons.notifications_active, size: 20),
            const SizedBox(width: 10),
            Expanded(child: Text(label)),
          ],
        ),
        // Long enough to survive a glance across a counter, short enough that
        // a second arrival is not stuck behind it.
        duration: const Duration(seconds: 8),
        action: SnackBarAction(
          label: 'View',
          onPressed: () => setState(() => _index = 1),
        ),
      ));
  }

  @override
  void dispose() {
    WidgetsBinding.instance.removeObserver(this);
    _orders.newOrderAlert.removeListener(_onNewOrder);
    // Leaving this running would keep hitting the server from a screen that no
    // longer exists — and, on logout, for an outlet nobody is signed into.
    _orders.stopPolling();
    _push.openOrderId.removeListener(_onPushTapped);
    super.dispose();
  }

  static const _titles = ['Menu & Outlet', 'Orders', 'Offers'];

  @override
  Widget build(BuildContext context) {
    final pages = const [_DishesTab(), OrdersScreen(), OffersScreen()];

    return Scaffold(
      appBar: AppBar(
        title: _AppBarTitle(section: _titles[_index]),
        actions: [
          if (_index == 0) const _OutletVisibilityToggle(),
          IconButton(
            key: const Key('open_outlet_settings'),
            tooltip: 'Hours & availability',
            icon: const Icon(Icons.schedule_outlined),
            onPressed: () => Navigator.of(context).push(
              MaterialPageRoute(builder: (_) => const OutletSettingsScreen()),
            ),
          ),
          IconButton(
            tooltip: 'Change password',
            icon: const Icon(Icons.password_outlined),
            onPressed: () => Navigator.of(context).push(
              MaterialPageRoute(builder: (_) => const ChangePasswordScreen()),
            ),
          ),
          IconButton(
            tooltip: 'Log out',
            icon: const Icon(Icons.logout),
            onPressed: () async {
              // Drop this device's push token first: once signed out it must
              // stop buzzing for an outlet whose staff member has left.
              await context.read<StaffPushService>().clear();
              if (!context.mounted) return;
              // Same reasoning for the in-app alert: stop polling and drop the
              // queue, so the next outlet on this phone starts from its own
              // orders rather than inheriting these.
              context.read<OrdersState>().reset();
              await context.read<AuthState>().logout();
            },
          ),
        ],
      ),
      body: IndexedStack(index: _index, children: pages),
      floatingActionButton: switch (_index) {
        0 => FloatingActionButton.extended(
            onPressed: () => _openDishEditor(context, null),
            icon: const Icon(Icons.add),
            label: const Text('Add dish'),
          ),
        // "Create offer", never "create coupon": the owner is choosing a
        // discount their restaurant funds, not minting a code.
        2 => FloatingActionButton.extended(
            onPressed: () => openOfferEditor(context, null),
            icon: const Icon(Icons.local_offer_outlined),
            label: const Text('Create offer'),
          ),
        _ => null,
      },
      bottomNavigationBar: NavigationBar(
        selectedIndex: _index,
        onDestinationSelected: (i) => setState(() => _index = i),
        destinations: const [
          NavigationDestination(
            icon: Icon(Icons.restaurant_menu_outlined),
            selectedIcon: Icon(Icons.restaurant_menu),
            label: 'Menu',
          ),
          NavigationDestination(
            icon: Icon(Icons.receipt_long_outlined),
            selectedIcon: Icon(Icons.receipt_long),
            label: 'Orders',
          ),
          NavigationDestination(
            icon: Icon(Icons.local_offer_outlined),
            selectedIcon: Icon(Icons.local_offer),
            label: 'Offers',
          ),
        ],
      ),
    );
  }
}

/// App bar title: WHICH restaurant, then which section of it.
///
/// The outlet name leads and the section label sits under it, because the
/// question this answers is asked across several phones at once — "which
/// account is this device signed into?" — and it has to be answerable at a
/// glance, without opening a tab. Reads the outlet HomeState already fetched
/// after login; no extra request exists for this.
///
/// Falls back to the section title alone until that load lands, rather than
/// showing a placeholder name that could be mistaken for a real outlet.
class _AppBarTitle extends StatelessWidget {
  const _AppBarTitle({required this.section});

  final String section;

  @override
  Widget build(BuildContext context) {
    final theme = Theme.of(context);
    final name = context.select<HomeState, String?>((s) {
      final n = s.outlet?.locationName.trim();
      return (n == null || n.isEmpty) ? null : n;
    });

    if (name == null) return Text(section);

    return Column(
      crossAxisAlignment: CrossAxisAlignment.start,
      mainAxisSize: MainAxisSize.min,
      children: [
        Text(
          name,
          key: HomeScreen.outletNameKey,
          overflow: TextOverflow.ellipsis,
          style: theme.textTheme.titleMedium?.copyWith(
            fontWeight: FontWeight.w700,
            height: 1.1,
          ),
        ),
        Text(
          section,
          style: theme.textTheme.labelSmall?.copyWith(
            color: theme.colorScheme.outline,
            height: 1.2,
          ),
        ),
      ],
    );
  }
}

/// Top-right outlet visibility switch, bound to GET /pos/outlet.is_visible.
class _OutletVisibilityToggle extends StatelessWidget {
  const _OutletVisibilityToggle();

  @override
  Widget build(BuildContext context) {
    final Outlet? outlet = context.select<HomeState, Outlet?>((s) => s.outlet);
    if (outlet == null) {
      return const SizedBox.shrink();
    }
    return Row(
      children: [
        const _OutletImageButton(),
        Text(
          outlet.isVisible ? 'Open' : 'Hidden',
          style: Theme.of(context).textTheme.labelMedium,
        ),
        Switch(
          value: outlet.isVisible,
          onChanged: (v) async {
            final ok = await context.read<HomeState>().toggleVisibility(v);
            if (!ok && context.mounted) {
              _showError(context, 'Could not update outlet visibility.');
            }
          },
        ),
      ],
    );
  }
}

class _DishesTab extends StatelessWidget {
  const _DishesTab();

  @override
  Widget build(BuildContext context) {
    final state = context.watch<HomeState>();

    if (state.loading && state.items.isEmpty) {
      return const Center(child: CircularProgressIndicator());
    }

    if (state.error != null && state.items.isEmpty) {
      return _ErrorRetry(
        message: state.error!,
        onRetry: () => context.read<HomeState>().load(),
      );
    }

    return RefreshIndicator(
      onRefresh: () => context.read<HomeState>().load(),
      child: ListView(
        padding: const EdgeInsets.symmetric(vertical: 8),
        children: [
          Padding(
            padding: const EdgeInsets.fromLTRB(16, 8, 16, 8),
            child: Text(
              'Dishes',
              style: Theme.of(context).textTheme.titleMedium,
            ),
          ),
          if (state.items.isEmpty)
            const Padding(
              padding: EdgeInsets.all(32),
              child: Center(child: Text('No dishes found.')),
            )
          else
            // FLAT list — deliberately no categories.
            ...state.items.map(
              (item) => DishRow(
                item: item,
                onTap: () => _openDishEditor(context, item),
                onChanged: (next) async {
                  final ok = await context
                      .read<HomeState>()
                      .toggleItemAvailability(item.id, next);
                  if (!ok && context.mounted) {
                    _showError(context, 'Could not update "${item.name}".');
                  }
                },
              ),
            ),
        ],
      ),
    );
  }
}

class _ErrorRetry extends StatelessWidget {
  final String message;
  final VoidCallback onRetry;

  const _ErrorRetry({required this.message, required this.onRetry});

  @override
  Widget build(BuildContext context) {
    return Center(
      child: Padding(
        padding: const EdgeInsets.all(24),
        child: Column(
          mainAxisSize: MainAxisSize.min,
          children: [
            const Icon(Icons.cloud_off, size: 40),
            const SizedBox(height: 12),
            Text(message, textAlign: TextAlign.center),
            const SizedBox(height: 16),
            FilledButton.tonal(onPressed: onRetry, child: const Text('Retry')),
          ],
        ),
      ),
    );
  }
}

void _showError(BuildContext context, String message) {
  ScaffoldMessenger.of(context)
    ..hideCurrentSnackBar()
    ..showSnackBar(SnackBar(content: Text(message)));
}

/// Opens the add (item == null) / edit dish screen. HomeState reloads itself
/// on a successful save, so no extra refresh is needed here.
Future<void> _openDishEditor(BuildContext context, MenuItem? item) async {
  await Navigator.of(context).push<bool>(
    MaterialPageRoute(builder: (_) => DishEditScreen(item: item)),
  );
}

/// Storefront photo control for the outlet, shown beside the visibility switch.
///
/// Reuses [CloudinaryService] — the exact unsigned-upload pipeline dish images
/// already use (same cloud name, same preset, no API secret in the app). No
/// second upload path was built for this.
class _OutletImageButton extends StatefulWidget {
  const _OutletImageButton();

  @override
  State<_OutletImageButton> createState() => _OutletImageButtonState();
}

class _OutletImageButtonState extends State<_OutletImageButton> {
  final _cloudinary = CloudinaryService();
  bool _busy = false;

  Future<void> _pick() async {
    if (!_cloudinary.configured) {
      _snack('Image upload is not configured.');
      return;
    }
    // Resolved before the picker opens: reading a provider off `context` after
    // that await is an async-gap use of BuildContext.
    final home = context.read<HomeState>();
    final picked = await ImagePicker().pickImage(
      source: ImageSource.gallery,
      // Storefront photo renders at 52x52 on the customer card; capping here
      // keeps the upload small rather than shipping a full-resolution photo.
      maxWidth: 1200,
      imageQuality: 85,
    );
    if (picked == null) return;

    setState(() => _busy = true);
    try {
      // Throws on failure rather than returning null — the catch below is the
      // failure path.
      final url = await _cloudinary.uploadImage(picked.path);
      final ok = await home.setOutletImage(url);
      if (mounted) _snack(ok ? 'Storefront photo updated.' : 'Could not save the photo.');
    } catch (_) {
      if (mounted) _snack('Image upload failed.');
    } finally {
      if (mounted) setState(() => _busy = false);
    }
  }

  void _snack(String m) => ScaffoldMessenger.of(context)
      .showSnackBar(SnackBar(content: Text(m)));

  @override
  Widget build(BuildContext context) {
    final outlet = context.select<HomeState, Outlet?>((s) => s.outlet);
    if (_busy) {
      return const Padding(
        padding: EdgeInsets.symmetric(horizontal: 12),
        child: SizedBox(
          width: 18, height: 18,
          child: CircularProgressIndicator(strokeWidth: 2),
        ),
      );
    }
    return IconButton(
      tooltip: outlet?.imageUrl == null
          ? 'Add storefront photo'
          : 'Change storefront photo',
      icon: outlet?.imageUrl == null
          ? const Icon(Icons.add_photo_alternate_outlined)
          : ClipRRect(
              borderRadius: BorderRadius.circular(4),
              child: Image.network(
                outlet!.imageUrl!,
                width: 24, height: 24, fit: BoxFit.cover,
                errorBuilder: (_, _, _) =>
                    const Icon(Icons.add_photo_alternate_outlined),
              ),
            ),
      onPressed: _pick,
    );
  }
}
