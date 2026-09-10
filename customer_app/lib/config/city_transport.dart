/// Which rail modes a customer can plausibly arrive on.
///
/// Gates the Train and Metro options at checkout. Both are unlike every other
/// mode: they carry no GPS origin and no speed, because the customer STATES an
/// arrival time and the server takes it as given. Offering either where there
/// is no rail would collect a declared arrival for a journey that cannot
/// happen, and that value feeds the prediction engine's timing directly.
///
/// ## The server answers first (migration 029)
///
/// This used to be a const map and nothing else, which meant enabling rail for
/// a new city needed a store release. The old docstring named that as the trade
/// and named the fix: *"the honest fix is a server-supplied flag on the outlet
/// payload, not a longer list here."* That flag now exists — `city_type`,
/// `has_metro` and `has_train` on `OutletOut`, set from a radio on the admin
/// dashboard's Cities page. An admin marking a city `metro` lights Metro up on
/// phones that are already installed.
///
/// ## The map below is now a FALLBACK, not the source of truth
///
/// It is still here, and still correct, because the server's answer can be
/// genuinely absent:
///
///   * a backend that predates migration 029 sends no such fields
///   * a city with an outlet but no `cities` row resolves to null
///   * a cart persisted by an older build restores without them
///
/// In all three the flag arrives as `null`, and null is NOT false — see
/// [Outlet.hasMetro]. Treating those as "no rail" would silently strip Train
/// from Chennai the first time the app met an older backend. So: use the
/// server's answer when it gave one, otherwise fall back to what shipped.
///
/// ## Keyed lower-cased, on purpose
///
/// `outlets.city` is free text with no constraint or check — nothing in the
/// schema keeps capitalisation consistent. `CarevoService.list_outlets` already
/// compares `lower(city)` on both sides for exactly this reason; this lookup
/// follows the same rule so the two cannot disagree about what "Chennai" is.
///
/// ## Absent still means false
///
/// A city neither the server nor the map knows shows no Train and no Metro.
/// That remains the DELIBERATE safe default: a new city appearing in `outlets`
/// — through a signup, not a code change — must not silently start offering a
/// mode nobody has checked it has.
library;

import '../models/outlet.dart';

class CityTransport {
  CityTransport._();

  /// Cities with rail a customer can realistically arrive on.
  ///
  /// FALLBACK ONLY — consulted when the server sent no answer. Kept in sync
  /// with migration 029's seed, which sets exactly these four to
  /// `city_type='metro', has_train=true`, so the two agree on day one.
  ///
  ///   * Chennai   — Chennai Suburban Railway (one of India's oldest and
  ///                 busiest) plus Chennai Metro.
  ///   * Bengaluru — Namma Metro; suburban rail (BSRP) still being built, but
  ///                 the metro alone satisfies "can arrive by rail".
  ///   * Kolkata   — Kolkata Metro (India's first) plus an extensive suburban
  ///                 network.
  ///   * Kochi     — Kochi Metro (operational since 2017) and Ernakulam's
  ///                 mainline stations.
  ///
  /// Madurai is deliberately absent: a major mainline junction, but no metro,
  /// and it has never been offered Train here. Changing that is now an admin
  /// decision on the Cities page rather than an edit to this file.
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

  /// True only when [city] is a known rail city, per the built-in map.
  ///
  /// Null, empty, or unknown all return false — an unrecognised city is treated
  /// exactly like a city known to have no rail.
  ///
  /// Prefer [trainFor]/[metroFor] where an [Outlet] is in hand: those consult
  /// the server first and only land here when it stayed silent.
  static bool hasTrainAccess(String? city) {
    final key = (city ?? '').trim().toLowerCase();
    if (key.isEmpty) return false;
    return _hasRail[key] ?? false;
  }

  /// The mode codes this outlet's city offers, or null when the server has not
  /// said (pre-030 backend, or a city with no row).
  ///
  /// Three layers, most authoritative first:
  ///   1. `transport_modes` — the 030 answer, a real list including modes this
  ///      build may never have heard of
  ///   2. `has_metro` / `has_train` — the 029 answer, for a backend that has
  ///      not run 030 yet
  ///   3. the built-in `_hasRail` map — offline, or a backend older than both
  ///
  /// Only layer 1 can express a mode added after this app shipped, which is why
  /// it is checked first and why an empty list from it is honoured rather than
  /// treated as absent.
  static List<OutletTransportMode>? serverModesFor(Outlet? outlet) =>
      outlet?.transportModes;

  /// Whether [outlet]'s city offers Train.
  ///
  /// Server answer wins; the built-in map covers a null.
  static bool trainFor(Outlet? outlet) {
    final modes = outlet?.transportModes;
    if (modes != null) return modes.any((m) => m.code == 'train');
    return outlet?.hasTrain ?? hasTrainAccess(outlet?.city);
  }

  /// Whether [outlet]'s city offers Tram.
  ///
  /// No built-in fallback on purpose: tram is new in migration 030, so a
  /// backend old enough to omit `transport_modes` has no opinion about it and
  /// the honest answer is "no". Guessing from the rail map would offer Tram in
  /// four cities on the strength of them having a metro.
  static bool tramFor(Outlet? outlet) {
    final modes = outlet?.transportModes;
    if (modes != null) return modes.any((m) => m.code == 'tram');
    return false;
  }

  /// Whether [outlet]'s city offers Metro.
  ///
  /// Falls back to the SAME rail map as Train, which is honest for the four
  /// cities in it — all four run metros, which is why the migration seeds them
  /// `city_type='metro'`. It is a fallback, not a claim that rail implies
  /// metro: any city where the two genuinely differ gets its answer from the
  /// server, because a city the admin has touched always sends real flags.
  static bool metroFor(Outlet? outlet) {
    final modes = outlet?.transportModes;
    if (modes != null) return modes.any((m) => m.code == 'metro');
    return outlet?.hasMetro ?? hasTrainAccess(outlet?.city);
  }
}
