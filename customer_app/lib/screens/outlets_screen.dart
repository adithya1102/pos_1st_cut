import 'package:flutter/material.dart';
import 'package:provider/provider.dart';
import 'package:url_launcher/url_launcher.dart';

import '../models/outlet.dart';
import '../models/outlet_sort.dart';
import '../services/api_client.dart';
import '../services/catalog_service.dart';
import '../services/customer_service.dart';
import '../services/location_service.dart';
import '../theme/app_colors.dart';
import '../theme/widgets/page_header.dart';
import '../theme/app_theme.dart';
import '../theme/widgets/neo_button.dart';
import '../theme/widgets/neo_card.dart';
import '../theme/widgets/neo_chip.dart';
import '../theme/widgets/neo_text_field.dart';
import 'menu_screen.dart';
import '../widgets/account_button.dart';
import '../widgets/active_order_card.dart';
import '../widgets/location_permission_dialog.dart';
import '../widgets/offer_sheet.dart';

/// How far out the list reaches, when the customer is browsing by distance.
///
/// Both send a real server-side radius — the query filters in its WHERE
/// clause, so an outlet outside the circle is not returned at all rather than
/// returned and sorted to the bottom. Before this there was no distance cap
/// anywhere: a Bengaluru origin returned a Kolkata outlet 1566km away.
enum RadiusMode {
  /// Everyday use: the city and what is realistically reachable around it.
  nearMe('Near Me', 65),

  /// Planning a trip — wide enough to reach neighbouring cities without
  /// becoming "everywhere", which is the state this feature exists to end.
  travel('Travel', 300);

  const RadiusMode(this.label, this.radiusKm);
  final String label;
  final double radiusKm;
}

/// Step 4: nearby restaurant discovery.
class OutletsScreen extends StatefulWidget {
  const OutletsScreen({
    super.key,
    this.lat,
    this.lng,
    this.cities = const {},
  });

  final double? lat;
  final double? lng;

  /// Cities chosen on Discover. Multi-select, so this is a set — empty means
  /// no city filter (the "Near me" path, which filters by coordinates instead).
  final Set<String> cities;

  @override
  State<OutletsScreen> createState() => _OutletsScreenState();
}

class _OutletsScreenState extends State<OutletsScreen> {
  late Future<List<Outlet>> _future;

  /// Cities actually applied to the query. Seeded from the caller (the picker
  /// on [LocationScreen]) but MUTABLE, because choosing a radius mode clears
  /// them — the two are mutually exclusive by product decision.
  late Set<String> _cities;

  /// Active radius mode, or null when browsing by city instead.
  ///
  /// Near Me is the default, but ONLY when the customer did not arrive having
  /// picked cities. Overriding an explicit choice with a default would throw
  /// away the thing they just told us.
  RadiusMode? _radiusMode;

  /// Switch to browsing by distance. Clears any city filter.
  ///
  /// Exclusivity is enforced HERE, in the app, not by the server: the API
  /// accepts city and radius together and answers coherently ("in Chennai,
  /// within 20km"). This is a UI decision about what the two controls mean to
  /// each other, so it belongs on this side.
  ///
  /// A radius needs an ORIGIN, so this owns the same permission dance the
  /// Nearest sort does — and for the same reason. Without it, tapping a chip
  /// with no location silently sent no radius while the chip lit up and the
  /// label read "within 65 km": the control would have been claiming a filter
  /// that was not applied, over a list that was still the whole country.
  ///
  /// The selected state moves ONLY once the radius is really in effect.
  Future<void> _setRadiusMode(RadiusMode mode) async {
    // Already have an origin — no permission is needed, so none is asked for.
    // Checking the coordinates rather than how we got them means re-tapping a
    // chip never re-prompts for something already granted.
    if (_lat != null && _lng != null) {
      setState(() {
        _radiusMode = mode;
        _cities = const {};
        _future = _load();
      });
      return;
    }

    setState(() => _locating = true);
    final service = context.read<LocationService>();
    // userInitiated: tapping the chip IS the request, so it re-checks the OS
    // status and re-prompts on every tap — the same reasoning as the Nearest
    // sort, and the same shared one-prompt latch it exists to defeat.
    final result = await service.getCurrentLocation(userInitiated: true);
    if (!mounted) return;
    setState(() => _locating = false);

    if (result.hasCoordinates) {
      setState(() {
        _lat = result.latitude;
        _lng = result.longitude;
        _radiusMode = mode;
        _cities = const {};
        _future = _load();
      });
      return;
    }

    // Refused or unavailable: the chip does NOT become selected, rather than
    // showing a radius as active over a list it was never applied to.

    if (result.outcome == LocationOutcome.deniedForever) {
      await showLocationBlockedDialog(
        context,
        service: service,
        purpose: 'show restaurants within a distance of you',
      );
      return;
    }

    final message = switch (result.outcome) {
      LocationOutcome.serviceDisabled =>
        'Turn on location services to search by distance.',
      LocationOutcome.denied =>
        'Searching by distance needs your location. Showing everywhere for now.',
      _ => 'Could not get your location, so distance search is unavailable.',
    };
    ScaffoldMessenger.of(context)
        .showSnackBar(SnackBar(content: Text(message)));
  }

  // v2 §1 screen 5 — search + filter chips over the already-fetched list.
  //
  // Filtering client-side, not server-side: the list is one small page the app
  // already holds, so a round trip per keystroke would add latency and offline
  // fragility for no benefit.
  final _search = TextEditingController();
  bool _offersOnly = false;

  /// Active sort. Replaced the old boolean "Nearest first" toggle — see
  /// [OutletSort] for which options are real and which are declared-but-blocked.
  OutletSort _sort = OutletSort.initial;
  // NO _openOnly / "Open now" filter. It shipped as a v2 filter chip but
  // `is_open` is hardcoded `true` for every outlet on the backend
  // (carevo_customer/service.py) — a filter chip that "selects" and removes
  // nothing is not a working filter, it is a control that LOOKS like one. See
  // Outlet.isOpen and _OutletCard for the matching removal of the OPEN pill.

  /// The origin distances are measured from. Seeded from the constructor (the
  /// customer arrived via "Near me") but MUTABLE, because selecting the
  /// Nearest sort can acquire an origin for a list that was opened by city —
  /// see [_selectSort].
  double? _lat;
  double? _lng;

  /// True while the Nearest sort is waiting on a GPS fix.
  bool _locating = false;

  @override
  void initState() {
    super.initState();
    _lat = widget.lat;
    _lng = widget.lng;
    _cities = Set<String>.of(widget.cities);
    // Near Me is the default, but only when it can actually be APPLIED.
    //
    // Two things disqualify it, for the same underlying reason — the control
    // must never show a filter the list is not under:
    //   * cities picked upstream: defaulting over an explicit choice would
    //     discard what the customer just told us on the previous screen;
    //   * no origin: a radius needs coordinates, so with none the chip would
    //     light up and read "within 65 km" over an unfiltered list.
    // In either case the chips start unselected and a tap resolves it.
    _radiusMode = (_cities.isEmpty && _lat != null && _lng != null)
        ? RadiusMode.nearMe
        : null;
    _future = _load();
  }

  @override
  void dispose() {
    _search.dispose();
    super.dispose();
  }

  /// Select a sort option.
  ///
  /// Only [OutletSort.nearest] can need anything it does not already have.
  /// Choosing it without an origin used to be a silent no-op: the control lit
  /// up, the order did not change, and no distance appeared on any card —
  /// because `distance_km` is computed server-side from a `lat`/`lng` the
  /// request never carried. Arriving by city (rather than by "Near me") is the
  /// common way to end up in exactly that state.
  ///
  /// So picking it ACQUIRES the origin it needs, and re-fetches. This is also
  /// the right moment to ask for the permission: the customer has just tapped
  /// a control whose entire meaning is distance, so what the prompt is for is
  /// obvious from what they did.
  Future<void> _selectSort(OutletSort sort, List<Outlet> loaded) async {
    // Belt-and-braces. The UI does not attach a tap handler to a blocked
    // option, so this should be unreachable — but a "sort" that silently does
    // nothing is the exact failure this whole design avoids, so it is refused
    // here too rather than trusted to the widget layer.
    if (!sort.available) return;

    if (sort != OutletSort.nearest) {
      setState(() => _sort = sort);
      return;
    }

    // The precondition for sorting by distance is DISTANCES, not an origin.
    // The list already carries them whenever it was fetched with a lat/lng, so
    // checking the data rather than how we got it means this never asks for a
    // permission it does not need — including on a re-select after the origin
    // has already been used once.
    if (loaded.any((o) => o.distanceKm != null)) {
      setState(() => _sort = sort);
      return;
    }

    setState(() => _locating = true);
    final service = context.read<LocationService>();
    // userInitiated: tapping the Nearest chip IS the request, so it re-checks
    // the OS status and re-prompts on every tap. Without this the service's
    // one-prompt latch — shared app-wide, so an earlier "Near me" denial set
    // it too — left this chip doing nothing at all on the second press.
    final result = await service.getCurrentLocation(userInitiated: true);
    if (!mounted) return;
    setState(() => _locating = false);

    if (result.hasCoordinates) {
      setState(() {
        _lat = result.latitude;
        _lng = result.longitude;
        _sort = sort;
        // Re-fetch: distance comes from the server, so sorting locally on the
        // list we already hold would sort a column that is still all-null.
        _future = _load();
      });
      return;
    }

    // Refused or unavailable: the selection does NOT move to Nearest, rather
    // than showing it as active over a sort that cannot happen.

    // A permanent denial cannot be re-asked, so it gets the explanation dialog
    // with a Settings route rather than a SnackBar that times out.
    if (result.outcome == LocationOutcome.deniedForever) {
      await showLocationBlockedDialog(
        context,
        service: service,
        purpose: 'sort restaurants by how close they are',
      );
      return;
    }

    final message = switch (result.outcome) {
      LocationOutcome.serviceDisabled =>
        'Turn on location services to sort by distance.',
      LocationOutcome.denied =>
        'Distances need your location. The list is unsorted for now.',
      _ => 'Could not get your location, so distances are unavailable.',
    };
    ScaffoldMessenger.of(context)
        .showSnackBar(SnackBar(content: Text(message)));
  }

  /// Open the collapsed sort options.
  ///
  /// The sheet returns the chosen option and closes ITSELF on tap, so "closes
  /// after a selection" is a property of the sheet rather than something every
  /// caller has to remember. A dismissal (tap outside / back) returns null and
  /// leaves the sort exactly as it was.
  ///
  /// Selection still goes through [_selectSort], so the Nearest option keeps
  /// its permission-and-refetch behaviour unchanged — collapsing the control
  /// moved where it is tapped, not what tapping it does.
  Future<void> _openSortSheet(List<Outlet> loaded) async {
    final chosen = await showModalBottomSheet<OutletSort>(
      context: context,
      backgroundColor: Colors.transparent,
      isScrollControlled: true,
      builder: (_) => _SortSheet(active: _sort),
    );
    if (chosen == null || !mounted) return;
    await _selectSort(chosen, loaded);
  }

  /// Apply search + filters, then the active sort. Kept pure and separate from
  /// build so the ordering rules are readable in one place.
  List<Outlet> _apply(List<Outlet> all) {
    final q = _search.text.trim().toLowerCase();
    final out = all.where((o) {
      if (_offersOnly && !o.hasOffers) return false;
      if (q.isEmpty) return true;
      return o.name.toLowerCase().contains(q) ||
          (o.locality ?? '').toLowerCase().contains(q) ||
          o.address.toLowerCase().contains(q);
    }).toList();

    // The ordering rules live on the enum, next to the declaration of which
    // options are real — so "what does this sort do" and "does this sort work"
    // cannot drift apart.
    return _sort.apply(out);
  }

  Future<List<Outlet>> _load() {
    return context.read<CatalogService>().fetchOutlets(
          lat: _lat,
          lng: _lng,
          // The chosen cities ARE the filter. They previously only fed the
          // subtitle, so every area showed the identical full outlet list.
          cities: _cities,
          // Only with an origin. Without coordinates a radius has nothing to
          // measure from, so the mode stays selected in the UI but sends
          // nothing — the list is then simply unfiltered rather than empty.
          radiusKm: (_lat != null && _lng != null) ? _radiusMode?.radiusKm : null,
        );
  }

  void _retry() => setState(() => _future = _load());

  @override
  Widget build(BuildContext context) {
    final c = AppColors.of(context);
    final textTheme = Theme.of(context).textTheme;
    // Names the cities while there are few enough to read, then falls back to
    // a count — the same rule the Discover CTA uses.
    final picked = _cities.toList()..sort();
    final subtitle = picked.isEmpty
        ? (_lat != null ? 'Closest to you' : 'All restaurants')
        : (picked.length <= 2
            ? 'In ${picked.join(' & ')}'
            : 'In ${picked.length} cities');

    return Scaffold(
      appBar: AppBar(
        title: const Text('Nearby'),
        actions: careVoActions(),
      ),
      body: SafeArea(
        // The FutureBuilder wraps the WHOLE column, not just the list, so the
        // result count can sit under the search box — it needs the filtered
        // length, which only exists inside the builder.
        child: FutureBuilder<List<Outlet>>(
          future: _future,
          builder: (context, snap) {
            final loading = snap.connectionState == ConnectionState.waiting;
            final all = snap.data ?? const <Outlet>[];
            final outlets = _apply(all);
            final searching = _search.text.trim().isNotEmpty;
            final filtering = searching || _offersOnly;

            return Column(
              crossAxisAlignment: CrossAxisAlignment.start,
              children: [
                Padding(
                  padding: const EdgeInsets.fromLTRB(20, 4, 20, 12),
                  child: Column(
                    crossAxisAlignment: CrossAxisAlignment.start,
                    children: [
                      const PageHeader('Pick a spot'),
                      const SizedBox(height: 8),
                      Row(
                        children: [
                          Icon(Icons.place, size: 16, color: c.primary),
                          const SizedBox(width: 4),
                          Text(subtitle,
                              style: textTheme.titleSmall
                                  ?.copyWith(color: c.inkSoft)),
                        ],
                      ),
                      const SizedBox(height: 10),
                      // How far the list reaches. Sits under the location line
                      // because it qualifies it: "closest to you" is only
                      // meaningful once "how close" has an answer.
                      _RadiusToggle(
                        selected: _radiusMode,
                        onSelect: _setRadiusMode,
                      ),
                    ],
                  ),
                ),
                const _ActiveOrderBanner(),
                // ---- search + filters (v2) ----
                // Search + the collapsed filter control, on ONE row.
                //
                // The filter lives here rather than under the search box
                // because collapsing the sort bar was about reclaiming
                // vertical space — putting the replacement on its own row
                // would have given most of it straight back.
                Padding(
                  padding: const EdgeInsets.fromLTRB(20, 0, 20, 8),
                  child: Row(
                    crossAxisAlignment: CrossAxisAlignment.center,
                    children: [
                      Expanded(
                        child: NeoTextField(
                          key: const Key('outlet_search'),
                          controller: _search,
                          hintText: 'Search restaurants or areas',
                          prefixIcon: Icons.search,
                          onChanged: (_) => setState(() {}),
                        ),
                      ),
                      const SizedBox(width: 10),
                      _FilterButton(
                        // The badge is driven by "is a non-default sort
                        // applied", which is the only thing the collapsed
                        // control can no longer show by being visible.
                        active: _sort != OutletSort.initial,
                        busy: _locating,
                        onTap: () => _openSortSheet(all),
                      ),
                    ],
                  ),
                ),
                // Result count, DIRECTLY under the search box.
                //
                // Position is the whole point. A count at the foot of the list
                // is under the raised keyboard at exactly the moment it is
                // wanted — while typing — so it is pinned here instead, in the
                // top third of the screen where nothing covers it.
                //
                // Only while a filter is active: "6 restaurants" over an
                // unfiltered list is a number nobody asked for.
                if (filtering && !loading)
                  Padding(
                    padding: const EdgeInsets.fromLTRB(20, 0, 20, 8),
                    child: Text(
                      key: const Key('outlet_result_count'),
                      outlets.length == 1
                          ? '1 restaurant'
                          : '${outlets.length} restaurants',
                      style: textTheme.bodySmall?.copyWith(color: c.inkSoft),
                    ),
                  ),
                // NO horizontal sort bar here any more — the ten options moved
                // behind the filter button on the search row above, into
                // [_SortSheet]. The bar cost ~52px of vertical space on every
                // screen for a control most customers touch once, if ever.
                //
                // The offers FILTER stays visible and is separate from the
                // offers SORT: one hides outlets without an offer, the other
                // just floats them up.
                Padding(
                  padding: const EdgeInsets.symmetric(horizontal: 20),
                  child: Row(
                    children: [
                      NeoChip(
                        key: const Key('chip_offers'),
                        label: 'Offers only',
                        icon: Icons.local_offer_outlined,
                        selected: _offersOnly,
                        onTap: () => setState(() => _offersOnly = !_offersOnly),
                      ),
                      // NO "Open now" chip here — see the comment by the
                      // (removed) `_openOnly` field above for why.
                    ],
                  ),
                ),
                const SizedBox(height: 8),
                Expanded(
                  child: Builder(builder: (context) {
                    if (loading) {
                      return const Center(child: CircularProgressIndicator());
                    }
                    if (snap.hasError) {
                      return _ErrorState(
                        message: snap.error is ApiException
                            ? (snap.error as ApiException).message
                            : 'Could not load restaurants.',
                        onRetry: _retry,
                      );
                    }
                    if (outlets.isEmpty && all.isNotEmpty) {
                      // Filtered to nothing — distinct from "no restaurants
                      // here", because the fix is different: clear a chip.
                      return _ErrorState(
                        message: 'No restaurants match those filters.',
                        onRetry: () => setState(() {
                          _search.clear();
                          _offersOnly = false;
                          // Sort is not cleared: it changes ORDER, never
                          // membership, so it can never be why the list is
                          // empty. Resetting it would move the list under
                          // someone who was only trying to clear a filter.
                        }),
                      );
                    }
                    if (outlets.isEmpty) {
                      return _ErrorState(
                        message: picked.isEmpty
                            ? 'No restaurants found here yet.'
                            : 'No restaurants in ${picked.join(', ')} yet.',
                      );
                    }
                    return RefreshIndicator(
                      onRefresh: () async => _retry(),
                      child: ListView.separated(
                        padding: const EdgeInsets.fromLTRB(20, 8, 20, 28),
                        itemCount: outlets.length,
                        separatorBuilder: (_, _) => const SizedBox(height: 18),
                        itemBuilder: (_, i) => _OutletCard(outlet: outlets[i]),
                      ),
                    );
                  }),
                ),
              ],
            );
          },
        ),
      ),
    );
  }
}

/// Storefront thumbnail edge. 52 -> 76 (+46%).
///
/// The photo was the smallest element on a card whose whole job is helping
/// someone recognise a restaurant, and at 52 it read as an icon rather than a
/// picture. This is the single biggest contributor to the card growing.
const double _kOutletThumb = 76;

/// Card padding. NeoCard's default is EdgeInsets.all(16); 20 here.
const double _kOutletPadding = 20;

/// Near Me / Travel, as a two-option segmented control.
///
/// [selected] is nullable: when the customer arrived having picked cities,
/// NEITHER option is on, because neither is what the list is showing. A control
/// that always claims a selection would be lying about the current filter.
class _RadiusToggle extends StatelessWidget {
  const _RadiusToggle({required this.selected, required this.onSelect});

  final RadiusMode? selected;
  final ValueChanged<RadiusMode> onSelect;

  static const Key nearMeKey = Key('radius_near_me');
  static const Key travelKey = Key('radius_travel');

  @override
  Widget build(BuildContext context) {
    final c = AppColors.of(context);
    return Row(
      children: [
        for (final mode in RadiusMode.values) ...[
          _RadiusChip(
            key: mode == RadiusMode.nearMe ? nearMeKey : travelKey,
            label: mode.label,
            selected: selected == mode,
            onTap: () => onSelect(mode),
          ),
          if (mode != RadiusMode.values.last) const SizedBox(width: 8),
        ],
        // The radius is stated rather than left to be inferred from the
        // results — "Near Me" alone does not tell anyone what was excluded.
        //
        // Expanded, not Spacer + bare Text: on a narrow surface the label has
        // nowhere to go and the Row overflows. Constraining it lets the text
        // ellipsise instead of the layout breaking.
        if (selected != null) ...[
          const SizedBox(width: 12),
          Expanded(
            child: Text(
              'within ${selected!.radiusKm.round()} km',
              textAlign: TextAlign.right,
              overflow: TextOverflow.ellipsis,
              style: Theme.of(context)
                  .textTheme
                  .bodySmall
                  ?.copyWith(color: c.inkSoft),
            ),
          ),
        ],
      ],
    );
  }
}

class _RadiusChip extends StatelessWidget {
  const _RadiusChip({
    super.key,
    required this.label,
    required this.selected,
    required this.onTap,
  });

  final String label;
  final bool selected;
  final VoidCallback onTap;

  @override
  Widget build(BuildContext context) {
    final c = AppColors.of(context);
    return GestureDetector(
      onTap: onTap,
      child: Container(
        padding: const EdgeInsets.symmetric(horizontal: 14, vertical: 7),
        decoration: BoxDecoration(
          color: selected ? c.primary : c.surface,
          borderRadius: BorderRadius.circular(AppTheme.radius - 4),
          border: Border.all(color: c.border, width: 2),
        ),
        child: Text(
          label,
          style: Theme.of(context).textTheme.labelLarge?.copyWith(
                color: selected ? c.onPrimary : c.ink,
                fontWeight: FontWeight.w700,
              ),
        ),
      ),
    );
  }
}

class _OutletCard extends StatelessWidget {
  const _OutletCard({required this.outlet});
  final Outlet outlet;

  @override
  Widget build(BuildContext context) {
    final c = AppColors.of(context);
    final textTheme = Theme.of(context).textTheme;

    return NeoCard(
      key: Key('outlet_card_${outlet.id}'),
      padding: const EdgeInsets.all(_kOutletPadding),
      // Unconditional. This used to be gated on `outlet.isOpen`, which is
      // hardcoded `true` server-side for every outlet (see the OPEN-pill
      // removal below) — so the gate never actually blocked a tap. Now that
      // nothing on the card claims to know open/closed status, silently
      // blocking navigation on that same fake signal would be worse: a tap
      // that does nothing, with no visible reason why. Real hours data
      // reintroduces this as a genuine gate when it lands.
      onTap: () => Navigator.of(context).push(
        MaterialPageRoute(builder: (_) => MenuScreen(outlet: outlet)),
      ),
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          Row(
            crossAxisAlignment: CrossAxisAlignment.start,
            children: [
              // Storefront photo (migration 011) fills the box that previously
              // always showed a generic glyph. Falls back to that glyph when the
              // outlet has no photo, or when the image fails to load.
              Container(
                width: _kOutletThumb,
                height: _kOutletThumb,
                decoration: BoxDecoration(
                  color: c.accent,
                  // 12 -> 14, so the corner keeps its proportion against the
                  // larger box rather than looking comparatively sharper.
                  borderRadius: BorderRadius.circular(14),
                  border: Border.all(color: c.border, width: 3),
                ),
                clipBehavior: Clip.antiAlias,
                child: outlet.imageUrl == null
                    // Glyph scaled with the box (default 24 -> 32); at the old
                    // size it would have floated in the middle of the frame.
                    ? Icon(Icons.restaurant, color: c.onAccent, size: 32)
                    : Image.network(
                        outlet.imageUrl!,
                        fit: BoxFit.cover,
                        errorBuilder: (_, _, _) =>
                            Icon(Icons.restaurant, color: c.onAccent, size: 32),
                        loadingBuilder: (context, child, progress) =>
                            progress == null
                                ? child
                                : Icon(Icons.restaurant,
                                    color: c.onAccent, size: 32),
                      ),
              ),
              const SizedBox(width: 16),
              Expanded(
                child: Column(
                  crossAxisAlignment: CrossAxisAlignment.start,
                  children: [
                    // "{Restaurant Name} · {Locality}" — two branches of the
                    // same chain can no longer look identical in the list.
                    Text(outlet.displayName, style: textTheme.titleLarge),
                    const SizedBox(height: 4),
                    Text(
                      outlet.address,
                      style: textTheme.bodyMedium?.copyWith(color: c.inkSoft),
                      maxLines: 2,
                      overflow: TextOverflow.ellipsis,
                    ),
                    // Serving hours, when the API supplies them. Hidden today
                    // for every outlet: `outlets` has no hours columns, so
                    // hoursLabel is always null. Wired up rather than omitted
                    // so the display exists the moment the column does — and
                    // deliberately never guessed. See Outlet.opensAt.
                    if (outlet.hoursLabel != null) ...[
                      const SizedBox(height: 4),
                      Row(
                        children: [
                          Icon(Icons.schedule, size: 13, color: c.inkSoft),
                          const SizedBox(width: 4),
                          Text(
                            outlet.hoursLabel!,
                            style: textTheme.bodySmall?.copyWith(color: c.inkSoft),
                          ),
                        ],
                      ),
                    ],
                    // Inline offer line, in the same box as the name so it
                    // reads as part of the restaurant rather than as an ad
                    // bolted onto the card. Only rendered when the outlet
                    // actually has an active offer.
                    if (outlet.hasOffers) ...[
                      const SizedBox(height: 8),
                      _OfferChip(outlet: outlet),
                    ],
                  ],
                ),
              ),
            ],
          ),
          const SizedBox(height: 16),
          Row(
            children: [
              // NO OPEN/CLOSED pill. `outlets.is_open` is hardcoded `true` for
              // every outlet in `CarevoService.list_outlets`
              // (carevo_customer/service.py) — there is no real hours data
              // behind it yet, so a pill here would state a fact the backend
              // does not actually know. Displaying a value known to be fake is
              // worse than displaying nothing; showing nothing is honest about
              // what the app doesn't know.
              //
              // The hours LINE above (outlet.hoursLabel, near the name) is a
              // separate, still-nullable field and stays exactly as wired —
              // it already hides itself until a migration adds real opening/
              // closing times, so nothing there needed to change for this fix.
              if (outlet.distanceKm != null)
                _Pill(
                  label: '${outlet.distanceKm!.toStringAsFixed(1)} km',
                  bg: c.surfaceAlt,
                  fg: c.ink,
                  icon: Icons.directions_walk,
                ),
              const Spacer(),
              // Directions, at the DISCOVERY stage.
              //
              // The map hand-off used to exist only on the checkout screen —
              // the last screen before payment, by which point the customer has
              // already picked a restaurant, browsed its menu and built an
              // order. Finding out there that it is across town means throwing
              // all of that away. Where it belongs is here, next to the
              // distance, while choosing is still cheap.
              //
              // The checkout copy is KEPT rather than moved: it does a
              // different job there — a final "is this the right branch of this
              // chain" check against the full address, immediately before money
              // moves — and deleting it would trade one gap for another.
              if (outlet.hasCoordinates) ...[
                _DirectionsButton(outlet: outlet),
                const SizedBox(width: 8),
              ],
              // Direct call (v2 §3.6). Rendered ONLY when the outlet actually
              // has a number — 5 of the 6 visible outlets in prod have none, so
              // a always-present button would be dead most of the time.
              if (outlet.canCall) ...[
                _CallButton(outlet: outlet),
                const SizedBox(width: 8),
              ],
              // Unconditional — no CLOSED-derived "Unavailable" state. Same
              // reasoning as the removed onTap gate above: it would be display
              // driven by the same known-fake `is_open`.
              Icon(Icons.arrow_forward, color: c.primary),
            ],
          ),
        ],
      ),
    );
  }
}

/// "1 active order — tap to see your code" strip above the restaurant list.
///
/// Exists because the pickup code was previously reachable only via
/// Profile → Order History, three taps deep, which is exactly where a customer
/// standing at a counter will not think to look. Renders nothing when there is
/// no active order, so the screen is unchanged in the common case.
///
/// Fetches once on build rather than polling: the strip only needs to know an
/// active order EXISTS. Live status belongs on the pickup screen it opens.
class _ActiveOrderBanner extends StatefulWidget {
  const _ActiveOrderBanner();

  @override
  State<_ActiveOrderBanner> createState() => _ActiveOrderBannerState();
}

class _ActiveOrderBannerState extends State<_ActiveOrderBanner> {
  List<OrderHistoryEntry> _active = const [];

  @override
  void initState() {
    super.initState();
    _load();
  }

  Future<void> _load() async {
    try {
      final orders = await context.read<CustomerService>().orders(limit: 20);
      if (!mounted) return;
      setState(() => _active = orders.where((o) => o.isActive).toList());
    } catch (_) {
      // Silent: a failed lookup must never block restaurant discovery. The
      // strip simply does not appear.
    }
  }

  @override
  Widget build(BuildContext context) {
    if (_active.isEmpty) return const SizedBox.shrink();
    final textTheme = Theme.of(context).textTheme;

    // ONE CARD PER ORDER, each showing its own outlet and its own code.
    //
    // The previous single banner showed only _active.first's code and counted
    // the rest ("3 orders in progress"), so with more than one order the other
    // codes were reachable only by navigating — which is precisely the moment
    // someone is standing at a counter being asked for one. Collapsing several
    // codes behind a count made the common multi-order case the slowest.
    // Height-capped and internally scrollable.
    //
    // This stack sits ABOVE the outlet list, outside its scroll view, so its
    // height is taken straight out of the list's. Ticket cards are much taller
    // than the single banner they replaced, and three concurrent orders were
    // enough to squeeze the restaurant list down to a few pixels — the orders
    // pushed the thing you came to the screen to do off the bottom. Capping it
    // at ~38% of the viewport keeps both usable no matter how many orders are
    // live; past the cap the stack scrolls on its own.
    final maxH = MediaQuery.sizeOf(context).height * 0.38;
    return Padding(
      padding: const EdgeInsets.fromLTRB(20, 0, 20, 12),
      child: ConstrainedBox(
        constraints: BoxConstraints(maxHeight: maxH),
        child: Column(
          mainAxisSize: MainAxisSize.min,
          crossAxisAlignment: CrossAxisAlignment.start,
          children: [
            if (_active.length > 1) ...[
              Text('${_active.length} orders in progress',
                  style: textTheme.titleSmall),
              const SizedBox(height: 8),
            ],
            Flexible(
              child: ListView.separated(
                shrinkWrap: true,
                padding: EdgeInsets.zero,
                itemCount: _active.length,
                separatorBuilder: (_, _) => const SizedBox(height: 10),
                itemBuilder: (_, i) =>
                    ActiveOrderCard(order: _active[i], onChanged: _load),
              ),
            ),
          ],
        ),
      ),
    );
  }
}

/// The collapsed filter control: one icon that opens [_SortSheet].
///
/// Replaced a ten-chip horizontal scroller. That bar was permanently on screen
/// and cost roughly 52px of vertical space on a list whose entire job is
/// showing restaurants — for a control most customers touch once, if at all.
///
/// ## The badge is not decoration
///
/// Collapsing a control hides its state, and a hidden sort is worse than a
/// visible one: the list is in an order the customer chose and can no longer
/// see a reason for. The dot restores exactly that one bit — "something other
/// than the default is applied" — so an unexpected order is attributable
/// without reopening the sheet. It is deliberately absent on the default sort,
/// otherwise it would be on permanently and mean nothing.
class _FilterButton extends StatelessWidget {
  const _FilterButton({
    required this.active,
    required this.busy,
    required this.onTap,
  });

  /// A non-default sort is applied — drives the badge.
  final bool active;

  /// The Nearest sort is waiting on a GPS fix.
  final bool busy;

  final VoidCallback onTap;

  @override
  Widget build(BuildContext context) {
    final c = AppColors.of(context);

    return Semantics(
      button: true,
      label: active ? 'Sort and filter, custom sort applied' : 'Sort and filter',
      child: GestureDetector(
        key: const Key('filter_button'),
        onTap: onTap,
        child: Stack(
          clipBehavior: Clip.none,
          children: [
            Container(
              // 56 square: matches the search field's height so the two sit as
              // one row rather than a button floating beside a taller box.
              width: 56,
              height: 56,
              alignment: Alignment.center,
              decoration: BoxDecoration(
                color: active ? c.primary : c.surface,
                borderRadius: BorderRadius.circular(AppTheme.radius),
                border: Border.all(color: c.border, width: AppTheme.borderWidth),
                boxShadow: [
                  BoxShadow(
                    color: c.shadow,
                    offset: const Offset(3, 3),
                    blurRadius: 0,
                  ),
                ],
              ),
              child: busy
                  ? SizedBox(
                      width: 18,
                      height: 18,
                      child: CircularProgressIndicator(
                        strokeWidth: 2,
                        color: active ? c.onPrimary : c.ink,
                      ),
                    )
                  // filter_list is the three-horizontal-line filter glyph.
                  : Icon(Icons.filter_list,
                      color: active ? c.onPrimary : c.ink, size: 24),
            ),
            if (active)
              Positioned(
                top: -3,
                right: -3,
                child: Container(
                  key: const Key('filter_active_badge'),
                  width: 14,
                  height: 14,
                  decoration: BoxDecoration(
                    color: c.accent,
                    shape: BoxShape.circle,
                    border: Border.all(color: c.border, width: 2),
                  ),
                ),
              ),
          ],
        ),
      ),
    );
  }
}

/// The sort options, as a bottom sheet.
///
/// A sheet rather than a `DropdownMenu`: ten rows, three of which carry a
/// second line of "Coming soon" text, is more than a dropdown renders
/// comfortably on a phone — and a sheet gives the blocked options room to
/// explain themselves instead of being mysteriously grey.
///
/// ## Which options are enabled is NOT decided here
///
/// It comes from [OutletSort.available], unchanged. This widget only renders
/// it. A blocked option is inert the same three independent ways the old chip
/// was: no `onTap` is passed, [IgnorePointer] stops the tap reaching a
/// detector at all, and `_selectSort` refuses it even if called directly.
///
/// Selecting pops with the chosen option, so the sheet closes itself — the
/// caller cannot forget to.
class _SortSheet extends StatelessWidget {
  const _SortSheet({required this.active});

  final OutletSort active;

  @override
  Widget build(BuildContext context) {
    final c = AppColors.of(context);
    final textTheme = Theme.of(context).textTheme;

    return SafeArea(
      top: false,
      child: Container(
        key: const Key('sort_sheet'),
        margin: const EdgeInsets.all(12),
        decoration: BoxDecoration(
          color: c.surface,
          borderRadius: BorderRadius.circular(AppTheme.radius),
          border: Border.all(color: c.border, width: AppTheme.borderWidth),
        ),
        child: Column(
          mainAxisSize: MainAxisSize.min,
          crossAxisAlignment: CrossAxisAlignment.start,
          children: [
            Padding(
              padding: const EdgeInsets.fromLTRB(20, 18, 20, 10),
              child: Text('Sort by', style: textTheme.headlineSmall),
            ),
            Flexible(
              child: ListView(
                shrinkWrap: true,
                padding: const EdgeInsets.only(bottom: 12),
                children: [
                  for (final option in OutletSort.values)
                    _SortSheetRow(
                      option: option,
                      selected: option == active,
                      onTap: option.available
                          ? () => Navigator.pop(context, option)
                          : null,
                    ),
                ],
              ),
            ),
          ],
        ),
      ),
    );
  }
}

/// One row in [_SortSheet].
class _SortSheetRow extends StatelessWidget {
  const _SortSheetRow({
    required this.option,
    required this.selected,
    required this.onTap,
  });

  final OutletSort option;
  final bool selected;

  /// Null when the option cannot be selected.
  final VoidCallback? onTap;

  @override
  Widget build(BuildContext context) {
    final c = AppColors.of(context);
    final textTheme = Theme.of(context).textTheme;
    final blocked = !option.available;

    return Semantics(
      button: !blocked,
      enabled: !blocked,
      selected: selected,
      label: blocked ? '${option.label}, coming soon' : option.label,
      child: IgnorePointer(
        ignoring: blocked,
        child: InkWell(
          key: Key('sort_${option.name}'),
          onTap: onTap,
          child: Padding(
            padding: const EdgeInsets.symmetric(horizontal: 20, vertical: 14),
            child: Row(
              children: [
                Icon(
                  selected ? Icons.radio_button_checked : Icons.radio_button_off,
                  size: 20,
                  color: blocked
                      ? c.inkSoft.withValues(alpha: 0.4)
                      : (selected ? c.primary : c.inkSoft),
                ),
                const SizedBox(width: 14),
                Expanded(
                  child: Column(
                    crossAxisAlignment: CrossAxisAlignment.start,
                    children: [
                      Text(
                        option.label,
                        style: textTheme.titleMedium?.copyWith(
                          color: blocked
                              ? c.inkSoft.withValues(alpha: 0.7)
                              : c.ink,
                        ),
                      ),
                      if (blocked)
                        Text(
                          'Coming soon',
                          style: textTheme.bodySmall?.copyWith(
                            fontSize: 11,
                            color: c.inkSoft.withValues(alpha: 0.7),
                          ),
                        ),
                    ],
                  ),
                ),
              ],
            ),
          ),
        ),
      ),
    );
  }
}

/// Opens the outlet's pin in Google Maps from the restaurant LIST.
///
/// Coordinates, not a name query: a name search can land on a different branch
/// of the same chain, which is exactly the confusion this is meant to prevent.
/// A plain universal URL rather than a Maps SDK or an embedded map — no API
/// key, no billing, no extra dependency, and it lands in whatever maps app the
/// customer actually uses.
///
/// Its own gesture sits above the card's, so a tap here opens directions
/// instead of the menu — the same pattern the offer chip and call button use.
class _DirectionsButton extends StatelessWidget {
  const _DirectionsButton({required this.outlet});
  final Outlet outlet;

  Future<void> _open(BuildContext context) async {
    final uri = Uri.parse(
      'https://www.google.com/maps/search/?api=1'
      '&query=${outlet.latitude},${outlet.longitude}',
    );
    final ok = await launchUrl(uri, mode: LaunchMode.externalApplication);
    if (!ok && context.mounted) {
      ScaffoldMessenger.of(context).showSnackBar(
        const SnackBar(content: Text('Could not open Maps on this device.')),
      );
    }
  }

  @override
  Widget build(BuildContext context) {
    final c = AppColors.of(context);
    return InkResponse(
      key: Key('directions_outlet_${outlet.id}'),
      onTap: () => _open(context),
      radius: 22,
      child: Container(
        padding: const EdgeInsets.all(8),
        decoration: BoxDecoration(
          color: c.surfaceAlt,
          borderRadius: BorderRadius.circular(10),
          border: Border.all(color: c.border, width: 2),
        ),
        child: Icon(Icons.map_outlined, size: 18, color: c.ink),
      ),
    );
  }
}

/// Direct-call action (v2 §3.6).
///
/// Uses the EXISTING outlets.phone_number rather than any new field. Its own
/// gesture sits above the card's, so tapping it dials instead of opening the
/// menu — the same pattern the offer chip already uses.
class _CallButton extends StatelessWidget {
  const _CallButton({required this.outlet});
  final Outlet outlet;

  Future<void> _call(BuildContext context) async {
    // tel: rather than a dialler package — no dependency, and it hands off to
    // whatever the customer's phone already uses.
    final uri = Uri(scheme: 'tel', path: outlet.phoneNumber);
    final ok = await launchUrl(uri);
    if (!ok && context.mounted) {
      ScaffoldMessenger.of(context).showSnackBar(
        SnackBar(content: Text('Could not start a call to ${outlet.phoneNumber}')),
      );
    }
  }

  @override
  Widget build(BuildContext context) {
    final c = AppColors.of(context);
    return InkResponse(
      key: Key('call_outlet_${outlet.id}'),
      onTap: () => _call(context),
      radius: 22,
      child: Container(
        padding: const EdgeInsets.all(8),
        decoration: BoxDecoration(
          color: c.accent,
          borderRadius: BorderRadius.circular(10),
          border: Border.all(color: c.border, width: 2),
        ),
        child: Icon(Icons.call, size: 18, color: c.onAccent),
      ),
    );
  }
}

/// The inline "there's an offer here" line on an outlet card.
///
/// Tapping opens the full list (CareVo campaigns aimed at this restaurant plus
/// its own offers, combined). Its own gesture sits above the card's, so a tap
/// here opens offers instead of navigating into the menu — deliberate, since a
/// customer reaching for the offer text wants the offers.
class _OfferChip extends StatelessWidget {
  const _OfferChip({required this.outlet});
  final Outlet outlet;

  @override
  Widget build(BuildContext context) {
    final c = AppColors.of(context);
    final textTheme = Theme.of(context).textTheme;
    // offerCount includes the headline itself, so "+N more" counts the rest.
    final extra = outlet.offerCount - 1;

    return GestureDetector(
      key: const Key('outlet_offer_chip'),
      behavior: HitTestBehavior.opaque,
      onTap: () => showOffersSheet(context, outlet: outlet),
      child: Container(
        padding: const EdgeInsets.symmetric(horizontal: 8, vertical: 6),
        decoration: BoxDecoration(
          color: c.accent,
          borderRadius: BorderRadius.circular(AppTheme.radius - 2),
          border: Border.all(color: c.border, width: 2),
        ),
        child: Row(
          mainAxisSize: MainAxisSize.min,
          children: [
            Icon(Icons.local_offer, size: 14, color: c.onAccent),
            const SizedBox(width: 6),
            Flexible(
              child: Text(
                outlet.offerText!,
                maxLines: 1,
                overflow: TextOverflow.ellipsis,
                style: textTheme.labelLarge
                    ?.copyWith(color: c.onAccent, fontSize: 12),
              ),
            ),
            if (extra > 0) ...[
              const SizedBox(width: 6),
              Text(
                '+$extra more',
                style: textTheme.labelSmall?.copyWith(color: c.onAccent),
              ),
            ],
          ],
        ),
      ),
    );
  }
}

class _Pill extends StatelessWidget {
  const _Pill({required this.label, required this.bg, required this.fg, this.icon});
  final String label;
  final Color bg;
  final Color fg;
  final IconData? icon;

  @override
  Widget build(BuildContext context) {
    final c = AppColors.of(context);
    return Container(
      padding: const EdgeInsets.symmetric(horizontal: 10, vertical: 5),
      decoration: BoxDecoration(
        color: bg,
        borderRadius: BorderRadius.circular(8),
        border: Border.all(color: c.border, width: 2),
      ),
      child: Row(
        mainAxisSize: MainAxisSize.min,
        children: [
          if (icon != null) ...[Icon(icon, size: 13, color: fg), const SizedBox(width: 4)],
          Text(
            label,
            style: Theme.of(context)
                .textTheme
                .labelLarge
                ?.copyWith(color: fg, fontSize: 12),
          ),
        ],
      ),
    );
  }
}

class _ErrorState extends StatelessWidget {
  const _ErrorState({required this.message, this.onRetry});
  final String message;
  final VoidCallback? onRetry;

  @override
  Widget build(BuildContext context) {
    final c = AppColors.of(context);
    return Center(
      child: Padding(
        padding: const EdgeInsets.all(28),
        child: Column(
          mainAxisSize: MainAxisSize.min,
          children: [
            Icon(Icons.sentiment_dissatisfied, size: 48, color: c.inkSoft),
            const SizedBox(height: 12),
            Text(
              message,
              textAlign: TextAlign.center,
              style: Theme.of(context).textTheme.titleMedium,
            ),
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
