import 'package:flutter/material.dart';
import 'package:provider/provider.dart';
import 'package:url_launcher/url_launcher.dart';

import '../models/menu.dart';
import '../models/outlet.dart';
import '../services/api_client.dart';
import '../services/catalog_service.dart';
import '../state/cart_state.dart';
import '../theme/app_colors.dart';
import '../theme/widgets/neo_button.dart';
import '../theme/widgets/neo_chip.dart';
import '../widgets/cart_bar.dart';
import '../widgets/menu_item_card.dart';
import 'cart_screen.dart';
import 'dish_detail_screen.dart';
import '../widgets/account_button.dart';

/// Step 5: menu browse with horizontal category chips + item list.
class MenuScreen extends StatefulWidget {
  const MenuScreen({super.key, required this.outlet});
  final Outlet outlet;

  @override
  State<MenuScreen> createState() => _MenuScreenState();
}

/// Veg/non-veg filter applied within the selected category.
enum VegFilter {
  all,
  veg,
  nonVeg;

  bool matches(bool isVeg) => switch (this) {
        VegFilter.all => true,
        VegFilter.veg => isVeg,
        VegFilter.nonVeg => !isVeg,
      };

  String get label => switch (this) {
        VegFilter.all => 'All',
        VegFilter.veg => 'Veg',
        VegFilter.nonVeg => 'Non-veg',
      };
}

class _MenuScreenState extends State<MenuScreen> {
  late Future<MenuResponse> _future;
  // -1 = the cumulative "All" view; 0..n-1 = a specific category.
  int _selectedCategory = -1;
  VegFilter _vegFilter = VegFilter.all;

  @override
  void initState() {
    super.initState();
    _future = _load();

    // Bind only when it costs nothing. Browsing a different restaurant must NOT
    // silently discard a basket — if it would, the cart stays bound to the old
    // outlet and _confirmOutletSwitch() asks first, on the add-to-cart attempt.
    //
    // Deferred to after the first frame, NOT called inline. Binding notifies
    // CartState's listeners, and this screen is built during the Navigator's
    // build pass while the provider holding CartState — which lives above
    // MaterialApp — has already been built this frame. Marking an
    // already-built ancestor dirty is exactly the "setState() called during
    // build" error, and it fired on every menu open in debug.
    //
    // Deferring by one frame is safe: nothing can be added to the cart before
    // the customer has seen the screen, and _confirmOutletSwitch re-checks the
    // binding on the add anyway.
    WidgetsBinding.instance.addPostFrameCallback((_) {
      if (!mounted) return;
      context.read<CartState>().bindOutletIfSafe(widget.outlet);
    });
  }

  /// Gate for adding an item while the cart belongs to another restaurant.
  /// Returns true when the caller may proceed with the add.
  Future<bool> _confirmOutletSwitch() async {
    final cart = context.read<CartState>();
    if (!cart.wouldDiscardCart(widget.outlet)) {
      // Same outlet (or empty cart): bind and add with no interruption.
      cart.bindOutletIfSafe(widget.outlet);
      return true;
    }

    final previous = cart.outlet?.name ?? 'another restaurant';
    final confirmed = await showDialog<bool>(
      context: context,
      builder: (c) => AlertDialog(
        title: const Text('Start a new order?'),
        content: Text(
          'Your cart has items from $previous. Adding this will empty that '
          'cart and start a new one at ${widget.outlet.name}.',
        ),
        actions: [
          TextButton(
            onPressed: () => Navigator.pop(c, false),
            child: const Text('Keep my cart'),
          ),
          FilledButton(
            onPressed: () => Navigator.pop(c, true),
            child: const Text('Start new order'),
          ),
        ],
      ),
    );
    if (confirmed != true) return false;
    // setOutlet clears, which is exactly what the customer just agreed to.
    cart.setOutlet(widget.outlet);
    return true;
  }

  Future<MenuResponse> _load() =>
      context.read<CatalogService>().fetchMenu(widget.outlet.id);

  void _retry() => setState(() => _future = _load());

  Future<void> _openItem(MenuItem item) async {
    // Sold-out items are LISTED (the API now returns them with
    // `is_available: false` instead of hiding them) and are tappable, but they
    // do not open the dish screen — that screen's entire purpose is building an
    // order line, and there is nothing to build.
    //
    // Answering the tap matters: a greyed row that silently ignores presses is
    // indistinguishable from a frozen screen. This says which item and why, and
    // it does so BEFORE the outlet-switch prompt below, so an unavailable item
    // can never be the reason someone is asked to discard their cart.
    if (!item.isAvailable) {
      ScaffoldMessenger.of(context)
        ..hideCurrentSnackBar()
        ..showSnackBar(SnackBar(
          key: const Key('item_unavailable_notice'),
          content: Text('${item.name} — not available'),
        ));
      return;
    }

    // Confirm the outlet switch BEFORE the dish opens, so the cart is already
    // bound to this restaurant by the time "Add to cart" is tapped.
    if (!await _confirmOutletSwitch()) return;
    if (!mounted) return;
    Navigator.of(context).push(
      MaterialPageRoute(builder: (_) => DishDetailScreen(item: item)),
    );
  }

  void _openCart() {
    Navigator.of(context)
        .push(MaterialPageRoute(builder: (_) => const CartScreen()));
  }

  @override
  Widget build(BuildContext context) {
    final textTheme = Theme.of(context).textTheme;

    return Scaffold(
      appBar: AppBar(
        // Name · locality, so a chain's branches stay distinguishable here too.
        title: Text(widget.outlet.displayName),
        actions: [
          // Direct call (v2 §3.6). Only when the outlet actually has a number —
          // most do not, and a permanently dead icon in the app bar would be
          // worse than no icon.
          if (widget.outlet.canCall)
            IconButton(
              key: Key('call_outlet_${widget.outlet.id}'),
              icon: const Icon(Icons.call),
              tooltip: 'Call ${widget.outlet.name}',
              onPressed: () async {
                final uri = Uri(scheme: 'tel', path: widget.outlet.phoneNumber);
                final ok = await launchUrl(uri);
                if (!ok && context.mounted) {
                  ScaffoldMessenger.of(context).showSnackBar(
                    const SnackBar(content: Text('Could not start a call.')),
                  );
                }
              },
            ),
          ...careVoActions(),
        ],
      ),
      bottomNavigationBar: CartBar(onView: _openCart),
      body: SafeArea(
        bottom: false,
        child: FutureBuilder<MenuResponse>(
          future: _future,
          builder: (context, snap) {
            if (snap.connectionState == ConnectionState.waiting) {
              return const Center(child: CircularProgressIndicator());
            }
            if (snap.hasError) {
              return _MenuError(
                message: snap.error is ApiException
                    ? (snap.error as ApiException).message
                    : 'Could not load the menu.',
                onRetry: _retry,
              );
            }
            final menu = snap.data!;
            final categories = menu.categories;
            if (categories.isEmpty) {
              return const _MenuError(message: 'This menu is empty right now.');
            }
            final isAll =
                _selectedCategory < 0 || _selectedCategory >= categories.length;
            final sourceItems = isAll
                ? categories.expand((cat) => cat.items).toList()
                : categories[_selectedCategory].items;
            final visibleItems = sourceItems
                .where((it) => _vegFilter.matches(it.isVeg))
                .toList();
            final sectionTitle = isAll ? 'All items' : categories[_selectedCategory].name;
            // Whether ANY visible row has a photo. Drives the thumbnail gutter
            // on every row so a mixed list still aligns — see MenuItemCard.
            final anyThumbnail = visibleItems.any((it) => it.imageUrl != null);

            return Column(
              crossAxisAlignment: CrossAxisAlignment.start,
              children: [
                SizedBox(
                  height: 58,
                  child: ListView.separated(
                    scrollDirection: Axis.horizontal,
                    padding: const EdgeInsets.symmetric(horizontal: 16, vertical: 8),
                    // +1 for the leading cumulative "All" chip.
                    itemCount: categories.length + 1,
                    separatorBuilder: (_, _) => const SizedBox(width: 10),
                    itemBuilder: (_, i) {
                      if (i == 0) {
                        return NeoChip(
                          label: 'All',
                          selected: isAll,
                          onTap: () => setState(() => _selectedCategory = -1),
                        );
                      }
                      final ci = i - 1;
                      return NeoChip(
                        label: categories[ci].name,
                        selected: !isAll && ci == _selectedCategory,
                        onTap: () => setState(() => _selectedCategory = ci),
                      );
                    },
                  ),
                ),
                SizedBox(
                  height: 50,
                  child: ListView(
                    scrollDirection: Axis.horizontal,
                    padding: const EdgeInsets.symmetric(horizontal: 16),
                    children: [
                      for (final f in VegFilter.values) ...[
                        NeoChip(
                          label: f.label,
                          selected: f == _vegFilter,
                          onTap: () => setState(() => _vegFilter = f),
                        ),
                        const SizedBox(width: 10),
                      ],
                    ],
                  ),
                ),
                Padding(
                  padding: const EdgeInsets.fromLTRB(20, 8, 20, 4),
                  child: Text(sectionTitle, style: textTheme.headlineSmall),
                ),
                Expanded(
                  child: visibleItems.isEmpty
                      ? _EmptySection(
                          source: sourceItems,
                          filter: _vegFilter,
                          sectionTitle: sectionTitle,
                          isAll: isAll,
                          onClearFilter: () =>
                              setState(() => _vegFilter = VegFilter.all),
                        )
                      : ListView.separated(
                          padding: const EdgeInsets.fromLTRB(20, 8, 20, 24),
                          itemCount: visibleItems.length,
                          separatorBuilder: (_, _) => const SizedBox(height: 14),
                          itemBuilder: (_, i) => MenuItemCard(
                            item: visibleItems[i],
                            // Decided by the LIST, not the item: only the list
                            // knows whether a photoless row has siblings with
                            // photos to line up against.
                            reserveThumbnail: anyThumbnail,
                            onTap: () => _openItem(visibleItems[i]),
                          ),
                        ),
                ),
              ],
            );
          },
        ),
      ),
    );
  }
}

/// The "nothing to show" state for a section, worded from WHY it is empty.
///
/// "No items found" is technically true of every empty result and useful for
/// none of them. The three reasons a section can come up empty need three
/// different messages, because they imply three different next actions:
///
///  * the section genuinely has nothing in it — nothing to do here;
///  * the section has items but the veg filter excludes ALL of them, which is
///    the definitionally-empty case (Beverages + Non-veg). Telling someone "no
///    items found" here reads as a loading failure or an outage. What is
///    actually true is that every drink on this menu is vegetarian, and saying
///    so answers the question instead of restating the symptom;
///  * a mix — some items exist under the other filter, so clearing it helps.
///
/// The claim is derived from the loaded data, never assumed: [source] is the
/// section's real contents, so "every item here is vegetarian" is checked
/// against the items rather than inferred from the category's name. A category
/// called Beverages that happens to contain a chicken soup will not be told it
/// is all-veg.
class _EmptySection extends StatelessWidget {
  const _EmptySection({
    required this.source,
    required this.filter,
    required this.sectionTitle,
    required this.isAll,
    required this.onClearFilter,
  });

  final List<MenuItem> source;
  final VegFilter filter;
  final String sectionTitle;
  final bool isAll;
  final VoidCallback onClearFilter;

  /// Where the items are, for the copy: "this menu" reads better than the
  /// pseudo-category "All items" when the cumulative view is selected.
  String get _where => isAll ? 'this menu' : sectionTitle;

  @override
  Widget build(BuildContext context) {
    final c = AppColors.of(context);
    final textTheme = Theme.of(context).textTheme;

    final String headline;
    final String? detail;
    // Only offered when clearing the filter would actually reveal something.
    var offerClear = false;

    if (source.isEmpty) {
      headline = isAll
          ? 'This menu is empty right now.'
          : 'Nothing in $sectionTitle right now.';
      detail = 'The restaurant may still be setting things up.';
    } else if (filter == VegFilter.nonVeg && source.every((i) => i.isVeg)) {
      // Definitionally empty: the filter and the section cannot both be
      // satisfied, and that is a fact about the menu, not a failure.
      headline = 'Everything in $_where is vegetarian.';
      detail = 'There are no non-veg items here to show.';
      offerClear = true;
    } else if (filter == VegFilter.veg && source.every((i) => !i.isVeg)) {
      headline = 'Everything in $_where is non-veg.';
      detail = 'There are no vegetarian items here to show.';
      offerClear = true;
    } else {
      // Shouldn't be reachable — a mixed section always has a match for the
      // active filter — but an accurate fallback beats an assertion.
      headline = 'No ${filter.label.toLowerCase()} items in $_where.';
      detail = null;
      offerClear = filter != VegFilter.all;
    }

    return Center(
      child: Padding(
        padding: const EdgeInsets.all(28),
        child: Column(
          mainAxisSize: MainAxisSize.min,
          children: [
            Icon(
              filter == VegFilter.all
                  ? Icons.restaurant_menu
                  : Icons.filter_alt_off_outlined,
              size: 44,
              color: c.inkSoft,
            ),
            const SizedBox(height: 12),
            Text(headline,
                textAlign: TextAlign.center, style: textTheme.titleMedium),
            if (detail != null) ...[
              const SizedBox(height: 6),
              Text(
                detail,
                textAlign: TextAlign.center,
                style: textTheme.bodyMedium?.copyWith(color: c.inkSoft),
              ),
            ],
            if (offerClear) ...[
              const SizedBox(height: 18),
              NeoButton(
                key: const Key('clear_veg_filter'),
                label: 'Show all items',
                icon: Icons.filter_alt_off_outlined,
                expand: false,
                variant: NeoButtonVariant.neutral,
                onPressed: onClearFilter,
              ),
            ],
          ],
        ),
      ),
    );
  }
}

class _MenuError extends StatelessWidget {
  const _MenuError({required this.message, this.onRetry});
  final String message;
  final VoidCallback? onRetry;

  @override
  Widget build(BuildContext context) {
    return Center(
      child: Padding(
        padding: const EdgeInsets.all(28),
        child: Column(
          mainAxisSize: MainAxisSize.min,
          children: [
            const Icon(Icons.restaurant_menu, size: 48),
            const SizedBox(height: 12),
            Text(message,
                textAlign: TextAlign.center,
                style: Theme.of(context).textTheme.titleMedium),
            if (onRetry != null) ...[
              const SizedBox(height: 18),
              NeoButton(
                label: 'Try again',
                icon: Icons.refresh,
                expand: false,
                variant: NeoButtonVariant.neutral,
                onPressed: onRetry,
              ),
            ],
          ],
        ),
      ),
    );
  }
}
