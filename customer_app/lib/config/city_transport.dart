/// Which cities a customer can plausibly arrive by rail from.
///
/// Gates the Train option at checkout. Train is unlike every other mode: it has
/// no GPS origin and no speed, because the customer STATES an arrival time and
/// the server takes it as given. Offering it where there is no rail would
/// collect a declared arrival for a journey that cannot happen, and that value
/// feeds the prediction engine's timing directly.
///
/// ## Keyed lower-cased, on purpose
///
/// `outlets.city` is free text with no constraint or check — nothing in the
/// schema keeps capitalisation consistent. `CarevoService.list_outlets` already
/// compares `lower(city)` on both sides for exactly this reason; this lookup
/// follows the same rule so the two cannot disagree about what "Chennai" is.
///
/// ## Absent means false
///
/// A city not listed here shows no Train option. That is the DELIBERATE safe
/// default, not an oversight: a new city appearing in `outlets` — through a new
/// signup, not a code change — must not silently start offering a mode nobody
/// has checked has rail. Adding a city here is a decision someone makes on
/// purpose.
///
/// The consequence to know: this ships in the app, so enabling rail for a new
/// city needs a release. That is the trade for the safe default. If it becomes
/// a real constraint, the honest fix is a server-supplied flag on the outlet
/// payload, not a longer list here.
library;

class CityTransport {
  CityTransport._();

  /// Cities with rail a customer can realistically arrive on.
  ///
  /// All four live cities qualify today:
  ///   * Chennai   — Chennai Suburban Railway (one of India's oldest and
  ///                 busiest) plus Chennai Metro.
  ///   * Bengaluru — Namma Metro; suburban rail (BSRP) still being built, but
  ///                 the metro alone satisfies "can arrive by rail".
  ///   * Kolkata   — Kolkata Metro (India's first) plus an extensive suburban
  ///                 network.
  ///   * Kochi     — Kochi Metro (operational since 2017) and Ernakulam's
  ///                 mainline stations.
  ///
  /// Worth knowing rather than discovering later: this is a CITY-level answer,
  /// not a per-outlet one. Kakkanad (the Kochi outlet) is not itself metro-served
  /// yet — Phase II is under construction — but Kochi has rail and a customer
  /// can arrive by it, which is the question this asks. If per-outlet accuracy
  /// is ever needed, this map is the wrong shape for it.
  static const Map<String, bool> _hasRail = {
    'chennai': true,
    'bengaluru': true,
    'kolkata': true,
    'kochi': true,
  };

  /// True only when [city] is a known rail city.
  ///
  /// Null, empty, or unknown all return false — an unrecognised city is treated
  /// exactly like a city known to have no rail.
  static bool hasTrainAccess(String? city) {
    final key = (city ?? '').trim().toLowerCase();
    if (key.isEmpty) return false;
    return _hasRail[key] ?? false;
  }
}
