import 'package:flutter/material.dart';
import 'package:provider/provider.dart';
import 'package:url_launcher/url_launcher.dart';

import '../models/outlet.dart';
import '../models/outlet_sort.dart';
import '../services/api_client.dart';
import '../services/app_error.dart';
import '../services/image_cdn.dart';
import '../widgets/error_state.dart';
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
import '../widgets/area_picker.dart';
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
///
/// Now also step 3. "Find restaurants near you" on Home comes straight here
/// rather than through the Discover screen, so the WHERE question — location
/// permission, or a city — is answered on this screen instead of in front of
/// it. See [autoLocate] and [_bootstrapLocation].
class OutletsScreen extends StatefulWidget {
  const OutletsScreen({
    super.key,
    this.lat,
    this.lng,
    this.cities = const {},
    this.autoLocate = false,
  });

  final double? lat;
  final double? lng;

  /// Cities to open with. Multi-select, so this is a set — empty means no city
  /// filter (the location path, which filters by coordinates instead).
  final Set<String> cities;

  /// Whether to go looking for a location on arrival.
  ///
  /// Defaults to FALSE, and that default is the important half. Arriving with
  /// neither cities nor coordinates is a legitimate way to open this screen —
  /// "just show me everything" — and it must not raise a permission dialog
  /// nobody asked for. Only the Home CTA passes true, because tapping "Find
  /// restaurants near you" IS the request: the customer has just said what they
  /// want, which is exactly the moment the prompt explains itself.
  ///
  /// Ignored when [lat]/[lng] or [cities] are supplied — there is nothing to
  /// acquire, and asking anyway would prompt for something already answered.
  final bool autoLocate;

  /// City of the closest outlet that has one.
  ///
  /// This is the app's stand-in for a reverse geocode, and it is deliberately
  /// not one: no new dependency, no extra request, and — the reason it is
  /// actually better here — the answer is always a city the picker can offer,
  /// because it came off an outlet that exists. A geocoder would happily return
  /// the town the customer is standing in and leave every box unticked.
  ///
  /// Static and pure so the rule is testable without a screen.
  ///
  /// Outlets with no `distance_km` are SKIPPED rather than treated as distance
  /// zero: that field is null for every outlet whenever the request carried no
  /// origin, and sorting nulls first would "detect" whichever city happened to
  /// come back first.
  static String? nearestCity(List<Outlet> outlets) {
    Outlet? closest;
    for (final o in outlets) {
      if (o.distanceKm == null) continue;
      if ((o.city ?? '').trim().isEmpty) continue;
      if (closest == null || o.distanceKm! < closest.distanceKm!) closest = o;
    }
    return closest?.city?.trim();
  }

  @override
  State<OutletsScreen> createState() => _OutletsScreenState();
}

class _OutletsScreenState extends State<OutletsScreen> {
  late Future<List<Outlet>> _future;

  /// Cities actually applied to the query. Seeded from [OutletsScreen.cities]
  /// but MUTABLE from both directions: the picker sets them (see
  /// [_applyCities]) and choosing a radius mode clears them — the two are
  /// mutually exclusive by product decision.
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

  /// Cities offered by the picker, from GET /customer/areas. Null until the
  /// sheet has fetched them once; cached here so reopening it does not refetch.
  List<AreaOption>? _areas;

  /// City the customer appears to be in, derived from the NEAREST outlet in a
  /// location-based response — not from a geocoder.
  ///
  /// Deriving it from the list we already fetched costs nothing and has a
  /// property a real reverse geocode does not: the answer is always a city the
  /// picker can actually offer, because it came off an outlet that exists. A
  /// geocoder will happily return the town you are standing in and leave the
  /// box unticked because no restaurant there serves it.
  ///
  /// This only PRE-TICKS the picker. It is not itself a filter — while it is
  /// set the list is still the radius query that produced it.
  String? _detectedCity;

  /// Guards the arrival flow so it runs once per screen, not once per rebuild.
  bool _bootstrapped = false;

  /// The most recent loaded list, cached OUTSIDE the FutureBuilder.
  ///
  /// The pinned search header holds a callback that opens the sort sheet, and
  /// the sort sheet needs the loaded outlets to decide whether the Nearest
  /// option already has distances to work with. A header delegate is only
  /// rebuilt when [_PinnedSearchHeader.shouldRebuild] says so, so a callback
  /// that CLOSED OVER the list would keep whichever list existed when the
  /// delegate was made — the empty one from the first frame — and every sort
  /// would then look distance-less and ask for location it did not need.
  ///
  /// Reading a field instead means the callback sees the current list whenever
  /// it is actually invoked.
  List<Outlet> _loaded = const [];

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

    // Post-frame, not inline: the arrival flow shows a dialog, a SnackBar and a
    // modal sheet, all of which need a mounted route to attach to.
    if (_shouldAutoLocate) {
      WidgetsBinding.instance
          .addPostFrameCallback((_) => _bootstrapLocation());
    }
  }

  /// Arriving with nothing — no cities, no origin — AND having been told to go
  /// looking. Both halves matter: see [OutletsScreen.autoLocate].
  bool get _shouldAutoLocate =>
      widget.autoLocate &&
      widget.cities.isEmpty &&
      widget.lat == null &&
      widget.lng == null;

  /// The arrival flow, for a customer who tapped "Find restaurants near you"
  /// and has told us nothing else.
  ///
  /// This is the work the Discover screen used to do, minus the screen. The
  /// outcome handling is the SAME as [_setRadiusMode] and [_selectSort] — a
  /// permanent denial gets the settings dialog, everything else gets a
  /// one-line SnackBar — because it is the same question being asked.
  ///
  /// Where it differs is the fallback. Those two are refinements of a list the
  /// customer is already looking at, so a refusal just leaves it alone. Here a
  /// refusal leaves them with no way to have expressed a location at all, so it
  /// opens the city picker: the alternative Discover used to offer, at the
  /// moment it becomes the only one left.
  Future<void> _bootstrapLocation() async {
    if (_bootstrapped || !mounted) return;
    _bootstrapped = true;

    setState(() => _locating = true);
    final service = context.read<LocationService>();
    // userInitiated: the tap on Home IS the request. Same reasoning as the
    // radius chips — and the same shared one-prompt latch it has to defeat, or
    // a customer who declined once elsewhere would silently get no dialog and
    // no explanation of why the screen did nothing.
    final result = await service.getCurrentLocation(userInitiated: true);
    if (!mounted) return;
    setState(() => _locating = false);

    if (result.hasCoordinates) {
      setState(() {
        _lat = result.latitude;
        _lng = result.longitude;
        _radiusMode = RadiusMode.nearMe;
        _future = _load();
      });
      await _detectCityFrom(_future);
      return;
    }

    if (result.outcome == LocationOutcome.deniedForever) {
      await showLocationBlockedDialog(
        context,
        service: service,
        purpose: 'find restaurants near you',
      );
    } else {
      final message = switch (result.outcome) {
        LocationOutcome.serviceDisabled =>
          'Location services are off. Pick your city instead.',
        LocationOutcome.denied => 'No problem — pick your city instead.',
        _ => 'Could not get your location. Pick your city instead.',
      };
      ScaffoldMessenger.of(context)
          .showSnackBar(SnackBar(content: Text(message)));
    }

    // Every non-granted outcome lands here, including the permanent one: the
    // settings dialog explains the refusal but does not resolve it, and the
    // customer still came here to find restaurants.
    if (!mounted) return;
    await _openCityPicker();
  }

  /// Read the customer's city off a location-based response.
  ///
  /// Failure is silent and total: a load error, an empty list, outlets with no
  /// city — all just leave [_detectedCity] null, which costs an unticked box in
  /// a picker the customer is about to use anyway. Nothing here is worth
  /// interrupting them for.
  Future<void> _detectCityFrom(Future<List<Outlet>> pending) async {
    try {
      final city = OutletsScreen.nearestCity(await pending);
      if (!mounted || city == null) return;
      setState(() => _detectedCity = city);
    } catch (_) {
      // The list itself reports its own failure — see the FutureBuilder.
    }
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

  /// Explain scheduled pickup. Awareness only — it does NOT schedule anything.
  ///
  /// ## Why an explainer and not a deep link
  ///
  /// A deep link was considered and is not merely harder, it is incoherent.
  /// Scheduling is a property of an ORDER: the picker lives at checkout, is
  /// bounded by the chosen outlet's closing time, and the time it produces is
  /// sent as `requested_pickup_at` on that order. From a list of restaurants
  /// there is no order to attach one to — a link would have to invent which
  /// outlet and which items, or drop the customer on an empty cart that can
  /// schedule nothing. Either is a worse answer than a sentence.
  ///
  /// So this does the one job it can do honestly: tell people the feature
  /// exists, before they have picked a restaurant, and get out of the way.
  /// "Choose a restaurant to get started" is the call to action, because
  /// choosing one IS the next step and the list is already underneath.
  Future<void> _openScheduleInfo() async {
    await showModalBottomSheet<void>(
      context: context,
      backgroundColor: Colors.transparent,
      isScrollControlled: true,
      builder: (_) => const _ScheduleInfoSheet(),
    );
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

  /// Open the city picker, and apply whatever comes back.
  ///
  /// Seeded with the cities already in effect, or — when there are none — with
  /// [_detectedCity], so the common case is one confirming tap rather than a
  /// hunt down the list. Dismissing returns null and changes nothing.
  Future<void> _openCityPicker() async {
    final seed = _cities.isNotEmpty ? _cities : {?_detectedCity};

    final picked = await showModalBottomSheet<Set<String>>(
      context: context,
      backgroundColor: Colors.transparent,
      isScrollControlled: true,
      builder: (_) => _CityPickerSheet(
        initialSelection: seed,
        // Handed the cached list so a second open is instant. The sheet fetches
        // only when this is null.
        cached: _areas,
        onLoaded: (areas) => _areas = areas,
      ),
    );

    if (picked == null || !mounted) return;
    _applyCities(picked);
  }

  /// Filter by cities, REPLACING any radius.
  ///
  /// The mirror image of [_setRadiusMode], which clears the cities. The two
  /// controls are mutually exclusive in this app — the server is happy to
  /// answer both at once, so this is a UI decision about what the two mean to
  /// each other, and it has to be enforced from both sides or the losing
  /// control keeps claiming a filter that is no longer applied.
  ///
  /// [_lat]/[_lng] deliberately SURVIVE. They are an origin, not a filter: with
  /// the radius gone they no longer narrow anything, but they still make the
  /// server return `distance_km`, so a city list keeps its distances and the
  /// Nearest sort keeps working without re-asking for permission.
  void _applyCities(Set<String> picked) {
    setState(() {
      _cities = picked;
      _radiusMode = null;
      _future = _load();
    });
  }

  Future<List<Outlet>> _load() {
    final pending = context
        .read<CatalogService>()
        .fetchOutlets(
          lat: _lat,
          lng: _lng,
          // The chosen cities ARE the filter. They previously only fed the
          // subtitle, so every area showed the identical full outlet list.
          cities: _cities,
          // Only with an origin. Without coordinates a radius has nothing to
          // measure from, so the mode stays selected in the UI but sends
          // nothing — the list is then simply unfiltered rather than empty.
          radiusKm: (_lat != null && _lng != null) ? _radiusMode?.radiusKm : null,
        )
        // Cached for the pinned header's sort callback — see [_loaded].
        .then((list) {
      _loaded = list;
      return list;
    });

    // Observe the failure here, TOO, and throw the result away.
    //
    // The FutureBuilder is the thing that renders the error, but it only
    // subscribes on the next build. A request that fails before that frame —
    // which is what a pull-to-refresh against a down backend does, since
    // setState only schedules a rebuild — would reject with nobody listening
    // and be reported as an unhandled async error. Attaching a handler marks
    // it observed; `pending` still carries the real error to the builder.
    pending.catchError((Object _) => const <Outlet>[]);

    return pending;
  }

  /// A BLOCK body, not an arrow.
  ///
  /// `setState(() => _future = _load())` returns the assigned Future out of the
  /// closure, and setState asserts on a callback that returns one. Nothing
  /// caught it while the only RefreshIndicator sat in the success branch and no
  /// test ever pulled it; wiring refresh into every state made it reachable.
  void _retry() {
    setState(() {
      _future = _load();
    });
  }

  /// The list, or whichever of the four non-list states applies.
  ///
  /// Every placeholder is a [SliverFillRemaining] with `hasScrollBody: false`.
  /// Both halves are deliberate: *FillRemaining* so a one-line message still
  /// centres in the space left under the header rather than clinging to it, and
  /// *hasScrollBody: false* so the box does NOT introduce a scrollable of its
  /// own — the enclosing CustomScrollView is the only one, which is what lets
  /// the RefreshIndicator work from these states. That is also why
  /// [ErrorStateView] is asked for its non-scrolling shape here.
  List<Widget> _contentSlivers({
    required bool loading,
    required AsyncSnapshot<List<Outlet>> snap,
    required List<Outlet> all,
    required List<Outlet> outlets,
  }) {
    if (loading) {
      return const [
        SliverFillRemaining(
          hasScrollBody: false,
          child: Center(child: CircularProgressIndicator()),
        ),
      ];
    }

    if (snap.hasError) {
      // Classified, not hand-worded. This used to render ApiException.message
      // straight out, which is how "Network error: unable to reach server.
      // (TimeoutException after 0:00:20)" reached customers.
      final err = AppError.from(snap.error!);
      err.logTo('OutletsScreen.outlets');
      return [
        SliverFillRemaining(
          hasScrollBody: false,
          child: ErrorStateView(
            error: err,
            scrollable: false,
            onRetry: () async => _retry(),
          ),
        ),
      ];
    }

    if (outlets.isEmpty && all.isNotEmpty) {
      // Filtered to nothing — distinct from "no restaurants here", because the
      // fix is different: clear a chip.
      return [
        SliverFillRemaining(
          hasScrollBody: false,
          child: _ErrorState(
            message: 'No restaurants match those filters.',
            // Nothing failed — the filter worked and matched none — so the
            // button clears the filters rather than retrying.
            retryLabel: 'Show all restaurants',
            onRetry: () => setState(() {
              _search.clear();
              _offersOnly = false;
              // Sort is not cleared: it changes ORDER, never membership, so it
              // can never be why the list is empty. Resetting it would move the
              // list under someone who was only trying to clear a filter.
            }),
          ),
        ),
      ];
    }

    if (outlets.isEmpty) {
      // Genuinely no data, NOT a failure — so it gets the empty copy and no
      // Try Again (see AppError.canRetry).
      return [
        SliverFillRemaining(
          hasScrollBody: false,
          child: ErrorStateView(error: AppError.empty(), scrollable: false),
        ),
      ];
    }

    return [
      SliverPadding(
        padding: const EdgeInsets.fromLTRB(20, 8, 20, 28),
        sliver: SliverList.separated(
          itemCount: outlets.length,
          separatorBuilder: (_, _) => const SizedBox(height: 18),
          itemBuilder: (_, i) => _OutletCard(outlet: outlets[i]),
        ),
      ),
    ];
  }

  @override
  Widget build(BuildContext context) {
    final c = AppColors.of(context);
    final textTheme = Theme.of(context).textTheme;
    // Names the cities while there are few enough to read, then falls back to
    // a count.
    //
    // Precedence is "what is the list actually under": chosen cities beat a
    // detected one, because a detection the customer has overridden is no
    // longer what they are looking at.
    final picked = _cities.toList()..sort();
    final subtitle = picked.isEmpty
        ? (_detectedCity != null
            ? 'Near $_detectedCity'
            : (_lat != null ? 'Closest to you' : 'All restaurants'))
        : (picked.length <= 2
            ? 'In ${picked.join(' & ')}'
            : 'In ${picked.length} cities');

    return Scaffold(
      appBar: AppBar(
        title: const Text('Nearby'),
        actions: careVoActions(),
      ),
      body: SafeArea(
        // The FutureBuilder still wraps EVERYTHING, not just the list. That was
        // true of the old Column and matters just as much here: the result
        // count needs the filtered length, which only exists inside the
        // builder, and it is a sliver several positions above the list.
        child: FutureBuilder<List<Outlet>>(
          future: _future,
          builder: (context, snap) {
            final loading = snap.connectionState == ConnectionState.waiting;
            final all = snap.data ?? const <Outlet>[];
            final outlets = _apply(all);
            final searching = _search.text.trim().isNotEmpty;
            final filtering = searching || _offersOnly;

            // ONE RefreshIndicator around the WHOLE scroll view, not around the
            // success branch alone.
            //
            // It used to wrap only the ListView, so the three states a customer
            // most wants to refresh FROM — a load error, an empty list, a
            // filtered-to-nothing list — were the exact three where pulling did
            // nothing. Wrapping the CustomScrollView fixes that for every state
            // at once, and is why the placeholder slivers below are
            // SliverFillRemaining rather than plain boxes: they keep the scroll
            // view scrollable when there is nothing to scroll.
            return RefreshIndicator(
              onRefresh: () async => _retry(),
              child: CustomScrollView(
                // Required for pull-to-refresh on a SHORT list. Without it a
                // viewport with little content refuses the overscroll drag and
                // the indicator never appears.
                physics: const AlwaysScrollableScrollPhysics(),
                slivers: [
                  SliverToBoxAdapter(
                    child: Padding(
                      padding: const EdgeInsets.fromLTRB(20, 4, 20, 12),
                      child: Column(
                        crossAxisAlignment: CrossAxisAlignment.start,
                        children: [
                          const PageHeader('Pick a spot'),
                          const SizedBox(height: 8),
                          // The location line is now the CONTROL for changing
                          // it, not just a readout. It was the only thing on
                          // screen naming where the list came from, so it is
                          // where someone looks when that is the thing they
                          // want to change — which previously meant going back
                          // to a screen that no longer exists on this route.
                          _LocationChip(
                            label: subtitle,
                            busy: _locating,
                            onTap: _openCityPicker,
                          ),
                          const SizedBox(height: 10),
                          // How far the list reaches. Sits under the location
                          // line because it qualifies it: "closest to you" is
                          // only meaningful once "how close" has an answer.
                          _RadiusToggle(
                            selected: _radiusMode,
                            onSelect: _setRadiusMode,
                          ),
                        ],
                      ),
                    ),
                  ),
                  // Scrolls with everything else now, and is no longer capped.
                  // See [_ActiveOrderBanner].
                  const SliverToBoxAdapter(child: _ActiveOrderBanner()),
                  // ---- search + filters (v2) ----
                  // THE one pinned element on the screen. Everything above
                  // scrolls up under it; everything below scrolls beneath it.
                  //
                  // Its POSITION is unchanged — still between the active-order
                  // strip and the result count — so the screen reads exactly as
                  // it did on arrival. What changed is that scrolling no longer
                  // takes it away: searching is the one thing on this screen a
                  // customer does *after* looking at the list, which is the
                  // moment the old layout had just scrolled the field off.
                  SliverPersistentHeader(
                    pinned: true,
                    delegate: _PinnedSearchHeader(
                      controller: _search,
                      // The badge is driven by "is a non-default sort applied",
                      // which is the only thing the collapsed control can no
                      // longer show by being visible.
                      filterActive: _sort != OutletSort.initial,
                      busy: _locating,
                      onChanged: () => setState(() {}),
                      // Reads [_loaded] at TAP time, not at build time — the
                      // delegate outlives the build that created it.
                      onFilterTap: () => _openSortSheet(_loaded),
                    ),
                  ),
                  // Result count, DIRECTLY under the search box.
                  //
                  // Position is the whole point. A count at the foot of the
                  // list is under the raised keyboard at exactly the moment it
                  // is wanted — while typing — so it sits here instead, right
                  // beneath the field, where the pinned header keeps it in the
                  // top third of the screen.
                  //
                  // Only while a filter is active: "6 restaurants" over an
                  // unfiltered list is a number nobody asked for.
                  //
                  // `outlets` is the FILTERED list, computed by the enclosing
                  // FutureBuilder — which is why that builder still wraps the
                  // whole scroll view rather than just the list sliver.
                  if (filtering && !loading)
                    SliverToBoxAdapter(
                      child: Padding(
                        padding: const EdgeInsets.fromLTRB(20, 0, 20, 8),
                        child: Text(
                          key: const Key('outlet_result_count'),
                          outlets.length == 1
                              ? '1 restaurant'
                              : '${outlets.length} restaurants',
                          style: textTheme.bodySmall?.copyWith(color: c.inkSoft),
                        ),
                      ),
                    ),
                  // NO horizontal sort bar here any more — the ten options
                  // moved behind the filter button on the search row above,
                  // into [_SortSheet]. The bar cost ~52px of vertical space on
                  // every screen for a control most customers touch once.
                  //
                  // The offers FILTER stays visible and is separate from the
                  // offers SORT: one hides outlets without an offer, the other
                  // just floats them up.
                  SliverToBoxAdapter(
                    child: Padding(
                      padding: const EdgeInsets.symmetric(horizontal: 20),
                      // Wrap, not Row (and not a horizontal scroller).
                      //
                      // A second chip overflowed the fixed Row by 140px on a
                      // 390pt screen — the striped overflow banner, on the main
                      // discovery screen. A horizontal ListView is the usual
                      // reflex for a chip row and is wrong HERE: it fixes the
                      // overflow by letting a chip sit off-screen, and the whole
                      // reason this second chip exists is to be seen. It would
                      // have failed hardest for large-text users, who need it
                      // most and would have been the ones it hid from.
                      //
                      // Wrap costs one extra line when the two do not fit and
                      // keeps both fully visible at every text scale.
                      child: Wrap(
                        spacing: 10,
                        runSpacing: 10,
                        children: [
                          NeoChip(
                            key: const Key('chip_offers'),
                            label: 'Offers only',
                            icon: Icons.local_offer_outlined,
                            selected: _offersOnly,
                            onTap: () =>
                                setState(() => _offersOnly = !_offersOnly),
                          ),
                          // An ACTION, not a filter — the one chip here that
                          // does not narrow the list.
                          //
                          // It sits next to a toggle and is drawn by the same
                          // widget, which is a real risk: two controls that look
                          // alike should not behave differently. `selected` is
                          // pinned false so it never takes the filled state that
                          // means "this filter is on", and the clock icon plus a
                          // verb-shaped label ("Schedule ahead", not "Scheduled")
                          // carry the difference. It opens a sheet immediately,
                          // so the distinction survives exactly one tap.
                          //
                          // It lives here because this is the last screen before
                          // someone commits to a restaurant, and scheduling is
                          // otherwise invisible until checkout — three screens
                          // later, past the point where knowing would have
                          // changed which restaurant they picked.
                          NeoChip(
                            key: const Key('chip_schedule'),
                            label: 'Schedule ahead',
                            icon: Icons.schedule,
                            selected: false,
                            onTap: _openScheduleInfo,
                          ),
                          // NO "Open now" chip here — see the comment by the
                          // (removed) `_openOnly` field above for why.
                        ],
                      ),
                    ),
                  ),
                  const SliverToBoxAdapter(child: SizedBox(height: 8)),
                  ..._contentSlivers(
                    loading: loading,
                    snap: snap,
                    all: all,
                    outlets: outlets,
                  ),
                ],
              ),
            );
          },
        ),
      ),
    );
  }
}

/// The search row, pinned to the top of the scroll view.
///
/// ## Why a SliverPersistentHeader and not a SliverAppBar
///
/// SliverAppBar is an APP BAR — it brings a leading/title/actions layout,
/// toolbar semantics, a system-overlay style and back-button handling, none of
/// which this row wants, and this Scaffold already has a real [AppBar] above it
/// ('Nearby'). A second one would announce itself to screen readers as another
/// toolbar and put two app bars on one screen. SliverPersistentHeader is the
/// primitive underneath it: pinning behaviour, nothing else. The row it renders
/// is the same Row as before, moved verbatim.
///
/// The extent is fixed and stated in parts below rather than measured, because
/// a delegate has to declare its height before its child is laid out.
class _PinnedSearchHeader extends SliverPersistentHeaderDelegate {
  const _PinnedSearchHeader({
    required this.controller,
    required this.filterActive,
    required this.busy,
    required this.onChanged,
    required this.onFilterTap,
  });

  final TextEditingController controller;
  final bool filterActive;
  final bool busy;
  final VoidCallback onChanged;
  final VoidCallback onFilterTap;

  /// Natural height of the search field: 16+16 content padding around a
  /// single line of bodyLarge, plus the 2px border top and bottom. Taller than
  /// [_FilterButton]'s 56, so it is the one that sets the row.
  ///
  /// A delegate must declare its extent BEFORE its child is laid out, so this
  /// cannot be measured — it is stated. [_headroom] is what keeps that from
  /// being fragile, and the row is top-aligned rather than stretched so a
  /// mismatch shows as space, never as an overflow.
  static const double _rowHeight = 62;

  /// The Neo hard shadow hangs 3px below the field and is part of the control.
  static const double _shadow = 3;

  /// Slack for a slightly taller row than [_rowHeight] predicts — a larger
  /// system text scale being the realistic cause.
  static const double _headroom = 6;

  static const double _padTop = 4;
  static const double _padBottom = 8;

  static const double extent =
      _rowHeight + _shadow + _headroom + _padTop + _padBottom;

  @override
  double get minExtent => extent;

  @override
  double get maxExtent => extent;

  @override
  Widget build(BuildContext context, double shrinkOffset, bool overlapsContent) {
    // OPAQUE, and that is not decoration: pinned means content passes
    // underneath, so a transparent header would have outlet cards sliding
    // visibly behind the search field.
    return Material(
      color: Theme.of(context).scaffoldBackgroundColor,
      child: Padding(
        padding: const EdgeInsets.fromLTRB(20, _padTop, 20, _padBottom),
        // Top-aligned, NOT stretched. A delegate hands its child a tight box of
        // exactly [extent]; letting the Row take its natural height inside that
        // box means the leftover shows up as the shadow gap and [_headroom]
        // rather than as a RenderFlex overflow.
        child: Align(
          alignment: Alignment.topCenter,
          child: Row(
            crossAxisAlignment: CrossAxisAlignment.center,
            children: [
              Expanded(
                child: NeoTextField(
                  key: const Key('outlet_search'),
                  controller: controller,
                  hintText: 'Search restaurants or areas',
                  prefixIcon: Icons.search,
                  onChanged: (_) => onChanged(),
                ),
              ),
              const SizedBox(width: 10),
              _FilterButton(
                active: filterActive,
                busy: busy,
                onTap: onFilterTap,
              ),
            ],
          ),
        ),
      ),
    );
  }

  @override
  bool shouldRebuild(_PinnedSearchHeader old) =>
      // NOT the controller's TEXT: the field owns that, and rebuilding the
      // header on every keystroke would rebuild the TextField under the cursor.
      // The screen rebuilds for the result count anyway; this only has to catch
      // changes to what the header itself renders.
      old.controller != controller ||
      old.filterActive != filterActive ||
      old.busy != busy;
}

/// The "where am I looking" line under the page title — a readout that is also
/// the way to change it.
///
/// A row rather than a NeoChip: it sits directly under a PageHeader and the
/// chip styling read as a filter control, which it is not — it is the statement
/// of what the whole list is scoped to.
class _LocationChip extends StatelessWidget {
  const _LocationChip({
    required this.label,
    required this.busy,
    required this.onTap,
  });

  final String label;

  /// True while a location request is in flight, so the affordance does not
  /// invite a second tap on top of a dialog that is already coming.
  final bool busy;

  final VoidCallback onTap;

  @override
  Widget build(BuildContext context) {
    final c = AppColors.of(context);
    final textTheme = Theme.of(context).textTheme;

    return Semantics(
      button: true,
      label: '$label. Tap to change location.',
      child: InkWell(
        key: const Key('location_chip'),
        onTap: busy ? null : onTap,
        borderRadius: BorderRadius.circular(AppTheme.radius),
        child: Padding(
          padding: const EdgeInsets.symmetric(vertical: 2),
          child: Row(
            mainAxisSize: MainAxisSize.min,
            children: [
              Icon(Icons.place, size: 16, color: c.primary),
              const SizedBox(width: 4),
              // Flexible + ellipsis, because this label is not bounded: it
              // grows with the city names in it ("In Bengaluru & Chennai" is
              // already 2px past a 350px-wide phone once the chevron is
              // allowed for). Truncating is right for the same reason the
              // label counts cities past two — the chevron saying it can be
              // changed matters more than the tail of the third name.
              //
              // Excluded from semantics: the wrapper above already announces
              // the full label, and leaving this in reads the location twice.
              Flexible(
                child: ExcludeSemantics(
                  child: Text(
                    label,
                    overflow: TextOverflow.ellipsis,
                    style: textTheme.titleSmall?.copyWith(color: c.inkSoft),
                  ),
                ),
              ),
              const SizedBox(width: 4),
              if (busy)
                SizedBox(
                  width: 12,
                  height: 12,
                  child: CircularProgressIndicator(
                      strokeWidth: 2, color: c.inkSoft),
                )
              else
                Icon(Icons.expand_more, size: 18, color: c.primary),
            ],
          ),
        ),
      ),
    );
  }
}

/// The city picker, as a sheet over the outlet list.
///
/// Wraps [AreaPicker] — the same widget the Discover screen uses, unchanged.
/// That widget was already multi-select, already search-backed, and already
/// had no navigation capability of its own, which is what makes it reusable
/// here: the thing that changes between the two callers is what "confirm"
/// means, and that lives in the host.
///
/// Owns a DRAFT selection rather than editing the screen's. Ticking a box mid-
/// sheet must not refetch the list behind it — the customer is still deciding,
/// and a list that reloaded under every tap would make choosing three cities
/// three round trips. Nothing is applied until the CTA.
///
/// Fetches its own areas so opening the sheet is what pays for them; the host
/// caches the result via [onLoaded] so a reopen is instant.
class _CityPickerSheet extends StatefulWidget {
  const _CityPickerSheet({
    required this.initialSelection,
    required this.cached,
    required this.onLoaded,
  });

  final Set<String> initialSelection;
  final List<AreaOption>? cached;
  final ValueChanged<List<AreaOption>> onLoaded;

  @override
  State<_CityPickerSheet> createState() => _CityPickerSheetState();
}

class _CityPickerSheetState extends State<_CityPickerSheet> {
  List<AreaOption>? _areas;
  String? _error;
  late final Set<String> _draft = Set<String>.of(widget.initialSelection);

  @override
  void initState() {
    super.initState();
    _areas = widget.cached;
    if (_areas == null) _loadAreas();
  }

  Future<void> _loadAreas() async {
    setState(() => _error = null);
    try {
      final areas = await context.read<CatalogService>().fetchAreas();
      if (!mounted) return;
      setState(() {
        _areas = areas;
        // Drop ticks for cities that no longer have an outlet, as a set
        // difference so a refresh that removes one does not clear the rest.
        final live = areas.map((a) => a.city).toSet();
        _draft.removeWhere((city) => !live.contains(city));
      });
      widget.onLoaded(areas);
    } on ApiException catch (e) {
      if (!mounted) return;
      setState(() {
        _areas = const [];
        _error = e.message;
      });
    }
  }

  /// Names the cities while there are few enough to read, then counts them.
  String get _ctaLabel {
    final picked = _draft.toList()..sort();
    if (picked.isEmpty) return 'Pick at least one city';
    if (picked.length <= 2) return 'Show outlets in ${picked.join(' & ')}';
    return 'Show outlets in ${picked.length} cities';
  }

  @override
  Widget build(BuildContext context) {
    final c = AppColors.of(context);
    final textTheme = Theme.of(context).textTheme;

    return SafeArea(
      top: false,
      child: Container(
        key: const Key('city_picker_sheet'),
        margin: const EdgeInsets.all(12),
        constraints: BoxConstraints(
          // Never taller than most of the screen: the list is as long as there
          // are serviceable cities, and it must not grow past the viewport.
          maxHeight: MediaQuery.of(context).size.height * 0.75,
        ),
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
              padding: const EdgeInsets.fromLTRB(20, 18, 20, 4),
              child: Text('Where are you?', style: textTheme.headlineSmall),
            ),
            Padding(
              padding: const EdgeInsets.fromLTRB(20, 0, 20, 12),
              child: Text(
                'Pick one or more cities.',
                style: textTheme.bodyMedium?.copyWith(color: c.inkSoft),
              ),
            ),
            Flexible(
              child: SingleChildScrollView(
                padding: const EdgeInsets.symmetric(horizontal: 20),
                child: AreaPicker(
                  areas: _areas,
                  error: _error,
                  selected: _draft,
                  // The draft is owned here, so the CTA label and the rows read
                  // the same source.
                  onToggle: (city) => setState(() {
                    if (!_draft.remove(city)) _draft.add(city);
                  }),
                  onRetry: _loadAreas,
                ),
              ),
            ),
            Padding(
              padding: const EdgeInsets.fromLTRB(20, 16, 20, 18),
              // Disabled on an empty selection rather than treating empty as
              // "all": with a default, ticking none and ticking everything
              // would do the same thing and nothing on screen would say what
              // the boxes were for.
              child: NeoButton(
                key: const Key('city_picker_apply'),
                label: _ctaLabel,
                icon: Icons.arrow_forward,
                onPressed: _draft.isEmpty
                    ? null
                    : () => Navigator.pop(context, Set<String>.of(_draft)),
              ),
            ),
          ],
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

/// Open / Closing soon / Closed pill (migration 024). Colour carries the state
/// too, not just the word: green open, amber closing-soon, red closed.
class _OutletStatusBadge extends StatelessWidget {
  const _OutletStatusBadge({required this.outlet});
  final Outlet outlet;

  @override
  Widget build(BuildContext context) {
    final c = AppColors.of(context);
    final (Color bg, Color fg, IconData icon) = switch (outlet.orderStatus) {
      'closed' => (AppColors.tomato, Colors.white, Icons.block),
      'closing_soon' => (AppColors.sunny, AppColors.ink, Icons.schedule),
      _ => (c.accent, c.onAccent, Icons.check_circle),
    };
    return Container(
      key: Key('outlet_status_${outlet.id}'),
      padding: const EdgeInsets.symmetric(horizontal: 10, vertical: 4),
      decoration: BoxDecoration(
        color: bg,
        borderRadius: BorderRadius.circular(8),
        border: Border.all(color: c.border, width: 2),
      ),
      child: Row(
        mainAxisSize: MainAxisSize.min,
        children: [
          Icon(icon, size: 14, color: fg),
          const SizedBox(width: 6),
          Text(outlet.statusLabel,
              style: Theme.of(context).textTheme.labelMedium?.copyWith(
                  color: fg, fontWeight: FontWeight.w700)),
        ],
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
                        // Thumbnail-sized, not the full original — see
                        // cdnThumbnail. The box is ~76px; the source images
                        // are unresized Cloudinary uploads.
                        cdnThumbnail(outlet.imageUrl)!,
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
                    // Operating status (migration 024): Open / Closing soon /
                    // Closed, computed server-side. Real now — the old OPEN pill
                    // was removed because is_open was hardcoded true; this one
                    // carries genuine state, so browsing the menu of a closed
                    // outlet warns before the customer reaches a disabled Pay.
                    const SizedBox(height: 6),
                    _OutletStatusBadge(outlet: outlet),
                    // Serving hours, when the API supplies them. Shown once an
                    // owner has set them (migration 024); still never guessed.
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
    //
    // ## No height cap, and no scroll view of its own
    //
    // Both used to be here: a maxHeight of 38% of the viewport wrapped around
    // an internally-scrolling ListView. Neither was about active orders. They
    // existed because this strip sat ABOVE the outlet list and OUTSIDE its
    // scroll view, so every pixel it took came straight out of the list's —
    // three concurrent orders squeezed the restaurant list down to almost
    // nothing, and the cap was the patch.
    //
    // The strip is now a sliver in the screen's one CustomScrollView, so it has
    // no fixed space to run out of: it is as tall as its orders and the whole
    // page scrolls. That removes the reason for the cap, and removes the
    // scrollable that came with it — a ListView here would now be a second
    // vertical scroll view inside the first, which is the arrangement that
    // makes a drag land in whichever one wins the gesture arena. A plain Column
    // has no such ambiguity.
    return Padding(
      padding: const EdgeInsets.fromLTRB(20, 0, 20, 12),
      child: Column(
        mainAxisSize: MainAxisSize.min,
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          if (_active.length > 1) ...[
            Text('${_active.length} orders in progress',
                style: textTheme.titleSmall),
            const SizedBox(height: 8),
          ],
          for (var i = 0; i < _active.length; i++) ...[
            if (i > 0) const SizedBox(height: 10),
            ActiveOrderCard(order: _active[i], onChanged: _load),
          ],
        ],
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
/// What "Schedule ahead" opens. Purely informational — see [_openScheduleInfo]
/// for why this is a sentence and not a link.
///
/// Three lines and a dismiss, deliberately. Everything a customer needs in
/// order to go looking for the control later is: the feature exists, where it
/// lives, and what it does for them. Anything more is a manual for a two-tap
/// toggle they have not reached yet.
///
/// It promises no specific TIME and no guarantee. The hold is computed from a
/// prep estimate plus a safety margin and the server can refuse a slot outright
/// when the restaurant cannot honour it, so "close to when you arrive" is the
/// strongest honest claim — and the checkout picker only ever offers times that
/// outlet can actually serve.
class _ScheduleInfoSheet extends StatelessWidget {
  const _ScheduleInfoSheet();

  @override
  Widget build(BuildContext context) {
    final c = AppColors.of(context);
    final textTheme = Theme.of(context).textTheme;

    return SafeArea(
      top: false,
      child: Container(
        key: const Key('schedule_info_sheet'),
        margin: const EdgeInsets.all(12),
        padding: const EdgeInsets.fromLTRB(20, 18, 20, 18),
        decoration: BoxDecoration(
          color: c.surface,
          borderRadius: BorderRadius.circular(AppTheme.radius),
          border: Border.all(color: c.border, width: AppTheme.borderWidth),
        ),
        child: Column(
          mainAxisSize: MainAxisSize.min,
          crossAxisAlignment: CrossAxisAlignment.start,
          children: [
            Row(
              children: [
                Icon(Icons.schedule, color: c.ink),
                const SizedBox(width: 10),
                Expanded(
                  child: Text('Schedule ahead',
                      style: textTheme.headlineSmall),
                ),
              ],
            ),
            const SizedBox(height: 12),
            Text(
              'Order now and pick a time to collect later today. '
              'We hold your order and send it to the kitchen at the right '
              'moment, so it is ready close to when you arrive.',
              style: textTheme.bodyMedium?.copyWith(color: c.inkSoft),
            ),
            const SizedBox(height: 10),
            Text(
              'Choose a restaurant to get started — the pickup time is the '
              'last thing you set before paying.',
              style: textTheme.bodyMedium?.copyWith(color: c.inkSoft),
            ),
            const SizedBox(height: 18),
            NeoButton(
              key: const Key('schedule_info_dismiss'),
              label: 'Got it',
              icon: Icons.check,
              onPressed: () => Navigator.of(context).pop(),
            ),
          ],
        ),
      ),
    );
  }
}

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
                  // `visible`, not `values`: Recommended is hidden outright.
                  // See OutletSort.hidden for why that one is the exception to
                  // showing blocked options.
                  for (final option in OutletSort.visible)
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
  const _ErrorState({
    required this.message,
    this.onRetry,
    this.retryLabel = 'Try again',
  });
  final String message;
  final VoidCallback? onRetry;

  /// The button caption. Defaults to "Try again" for the genuine-failure case,
  /// but a filter that simply matched nothing did not fail — there the action
  /// is "show all", not "retry", so callers override this.
  final String retryLabel;

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
                label: retryLabel,
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
