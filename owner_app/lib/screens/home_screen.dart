import 'package:flutter/material.dart';
import 'package:provider/provider.dart';

import '../models/menu_item.dart';
import 'package:image_picker/image_picker.dart';

import '../models/outlet.dart';
import '../services/cloudinary_service.dart';
import '../services/staff_push_service.dart';
import '../state/auth_state.dart';
import '../state/home_state.dart';
import '../state/offers_state.dart';
import '../state/orders_state.dart';
import '../widgets/dish_row.dart';
import 'change_password_screen.dart';
import 'dish_edit_screen.dart';
import 'offers_screen.dart';
import 'orders_screen.dart';

class HomeScreen extends StatefulWidget {
  const HomeScreen({super.key});

  @override
  State<HomeScreen> createState() => _HomeScreenState();
}

class _HomeScreenState extends State<HomeScreen> {
  int _index = 0;

  @override
  void initState() {
    super.initState();
    WidgetsBinding.instance.addPostFrameCallback((_) {
      context.read<HomeState>().load();
      context.read<OrdersState>().load();
      context.read<OffersState>().load();

      // A tapped staff push (new order, or a train order due to start) lands
      // on the EXISTING Orders tab rather than a new screen.
      final push = context.read<StaffPushService>();
      push.attachTapRouting();
      push.openOrderId.addListener(_onPushTapped);
      // A cold start from a notification sets the value before this listener
      // exists, so check once on mount too.
      if (push.openOrderId.value != null) _onPushTapped();
    });
  }

  void _onPushTapped() {
    if (!mounted) return;
    setState(() => _index = 1);          // Orders tab
    context.read<OrdersState>().load();  // the pushed order may be brand new
    context.read<StaffPushService>().openOrderId.value = null;  // consume once
  }

  @override
  void dispose() {
    context.read<StaffPushService>().openOrderId.removeListener(_onPushTapped);
    super.dispose();
  }

  static const _titles = ['Menu & Outlet', 'Orders', 'Offers'];

  @override
  Widget build(BuildContext context) {
    final pages = const [_DishesTab(), OrdersScreen(), OffersScreen()];

    return Scaffold(
      appBar: AppBar(
        title: Text(_titles[_index]),
        actions: [
          if (_index == 0) const _OutletVisibilityToggle(),
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
              if (context.mounted) await context.read<AuthState>().logout();
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
