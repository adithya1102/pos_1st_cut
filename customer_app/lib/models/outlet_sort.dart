import '../models/outlet.dart';

/// The sort options offered on the restaurant list.
///
/// ## Three work; seven are declared but not built
///
/// The three that work are the three the app already has real data for:
///
///  * [nearest]    — `distance_km`, computed server-side from a GPS origin.
///  * [newest]     — `outlets.created_at`, a real column.
///  * [bestOffers] — `offer_count`, already returned inline per outlet.
///
/// The other seven are listed with [available] = false and rendered greyed
/// with a "Coming soon" label. They are NOT hidden, deliberately: each one
/// needs a backing signal the platform does not collect yet, and showing the
/// intended shape of the feature is more honest than pretending the list of
/// options is complete. Each carries the reason it cannot work in [blockedBy],
/// so nobody has to re-derive it later.
///
/// The alternative — shipping them enabled and silently no-op — is the exact
/// bug the OPEN badge had, and it was removed for the same reason: a control
/// that looks live and does nothing is worse than one that says it is not
/// ready.
enum OutletSort {
  nearest(
    label: 'Nearest',
    available: true,
  ),
  newest(
    label: 'Newest',
    available: true,
  ),
  bestOffers(
    label: 'Best Offers',
    available: true,
  ),

  // ---- declared, not built. See the class doc. ----
  recommended(
    label: 'Recommended',
    available: false,
    hidden: true,
    blockedBy: 'needs a personalisation model; no per-customer signal is '
        'collected yet',
  ),
  highestRated(
    label: 'Highest Rated',
    available: false,
    blockedBy: 'needs outlet ratings; there is no ratings table',
  ),
  mostPopular(
    label: 'Most Popular',
    available: false,
    blockedBy: 'needs order-volume aggregates per outlet; not exposed to the '
        'customer API',
  ),
  fastestPickup(
    label: 'Fastest Pickup',
    available: false,
    blockedBy: 'needs measured prep/wait times per outlet; only per-ITEM '
        'prep_time_minutes exists, which is not an outlet-level figure',
  ),
  priceLowHigh(
    label: 'Price: Low to High',
    available: false,
    blockedBy: 'needs an outlet-level price index; the API returns no '
        'aggregate menu price',
  ),
  priceHighLow(
    label: 'Price: High to Low',
    available: false,
    blockedBy: 'same missing price index as priceLowHigh',
  ),
  mostReviewed(
    label: 'Most Reviewed',
    available: false,
    blockedBy: 'needs a reviews table; none exists',
  );

  const OutletSort({
    required this.label,
    required this.available,
    this.hidden = false,
    this.blockedBy,
  });

  final String label;

  /// False for an option that is displayed but cannot be selected.
  final bool available;

  /// Not rendered at all, not even greyed.
  ///
  /// The class doc argues for SHOWING blocked options rather than hiding them,
  /// and that still holds for the rest: "Most Reviewed" tells you the platform
  /// intends reviews. Recommended is the exception because it does not describe
  /// a missing signal so much as promise a judgement the app has no basis for —
  /// personalisation nobody has opted into and no data to build it from. It
  /// sets an expectation the roadmap does not hold, so it is not shown.
  ///
  /// Kept as a VALUE rather than deleted: [blockedBy] records why it does not
  /// exist, which is the thing a future reader needs, and removing the constant
  /// would silently break anything that has persisted the name.
  final bool hidden;

  /// Why [available] is false. Null for the three that work.
  final String? blockedBy;

  /// The default. Distance is the one people mean most often, and it degrades
  /// gracefully — see [apply].
  static const OutletSort initial = OutletSort.nearest;

  static List<OutletSort> get enabled =>
      values.where((s) => s.available).toList();
  static List<OutletSort> get comingSoon =>
      values.where((s) => !s.available && !s.hidden).toList();

  /// Everything the sort sheet should render, in order.
  static List<OutletSort> get visible =>
      values.where((s) => !s.hidden).toList();

  /// Sort [outlets] by this option. Returns a NEW list; never mutates input.
  ///
  /// Only the three working options do anything. A disabled option cannot
  /// reach here (the UI refuses to select it), but if one somehow did it
  /// returns the list untouched rather than silently producing a fake order.
  List<Outlet> apply(List<Outlet> outlets) {
    final out = List<Outlet>.of(outlets);
    switch (this) {
      case OutletSort.nearest:
        // Unknown distance sorts LAST rather than as 0 — claiming an outlet
        // with no GPS origin is the closest is a lie the customer acts on.
        out.sort((a, b) => _nullsLast(a.distanceKm, b.distanceKm,
            (x, y) => x.compareTo(y)));
      case OutletSort.newest:
        // Descending: newest first. Unknown creation date sorts last.
        out.sort((a, b) => _nullsLast(a.createdAt, b.createdAt,
            (x, y) => y.compareTo(x)));
      case OutletSort.bestOffers:
        // Most offers first; ties keep their incoming order (List.sort is not
        // stable, so the count comparison is the whole rule and equal counts
        // are simply not reordered relative to each other in any meaningful
        // way — acceptable, since equal-offer outlets have no better ordering).
        out.sort((a, b) => b.offerCount.compareTo(a.offerCount));
      default:
        // A not-yet-built option: leave the order alone.
        break;
    }
    return out;
  }

  /// Shared null handling: a missing value always sorts to the end, whichever
  /// direction the present values are compared in.
  static int _nullsLast<T>(T? a, T? b, int Function(T, T) compare) {
    if (a == null && b == null) return 0;
    if (a == null) return 1;
    if (b == null) return -1;
    return compare(a, b);
  }
}
