import 'package:flutter/material.dart';
import 'package:provider/provider.dart';
import 'package:url_launcher/url_launcher.dart';

import '../models/cart_item.dart';
import '../models/offer.dart';
import '../config/city_transport.dart';
import '../models/outlet.dart';
import '../services/api_client.dart';
import '../services/cashfree_service.dart';
import '../services/location_service.dart';
import '../services/order_service.dart';
import '../services/payment_service.dart';
import '../state/cart_state.dart';
import '../theme/app_colors.dart';
import '../theme/widgets/neo_button.dart';
import '../theme/widgets/neo_card.dart';
import '../theme/widgets/ticket_card.dart';
import '../widgets/arrival_time_picker.dart';
import '../widgets/focus_release.dart';
import '../widgets/location_permission_dialog.dart';
import '../widgets/offer_sheet.dart';
import '../widgets/price_text.dart';
import 'payment_processing_screen.dart';
import 'pickup_screen.dart';
import '../widgets/account_button.dart';

/// PE Step 3 (FR-C1) — how the customer will travel to the outlet. Values map
/// 1:1 to the backend MODE_SPEED_MPS keys used by the travel predictor.
enum TransportMode {
  walk('walk', 'Walk', Icons.directions_walk),
  bike('bike', 'Bike', Icons.two_wheeler),
  car('car', 'Car', Icons.directions_car),
  auto('auto', 'Auto', Icons.local_taxi),
  bus('bus', 'Bus', Icons.directions_bus),
  // Addendum Item 1. Unlike every mode above, this leg is NOT derived from a
  // GPS origin — the customer states an arrival time and the server treats it
  // as given, so selecting it swaps the origin picker for a time picker.
  train('train', 'Train', Icons.train),
  // Migration 029. A declared-arrival mode like train, NOT a speed-based one:
  // a metro rider knows which train they are on and when it gets in, and no
  // GPS origin could beat that. It also sidesteps a real trap — the backend's
  // MODE_SPEED_MPS has no metro entry and `.get(mode, DEFAULT)` resolves a
  // missing key to BIKE speed, so a speed-based metro would have been timed as
  // a cycle ride and nobody would have noticed for months.
  metro('metro', 'Metro', Icons.subway),
  // Migration 030. Declared-arrival for the same reason as metro: a tram runs
  // a scheduled route you read a time off, so a GPS origin would be collected
  // and then ignored — and the backend's MODE_SPEED_MPS has no 'tram' key, so
  // a speed-based tram would silently resolve to BIKE speed.
  tram('tram', 'Tram', Icons.tram);

  const TransportMode(this.wire, this.label, this.icon);
  final String wire;
  final String label;
  final IconData icon;

  /// LOCAL default for whether this mode is satisfied by a declared arrival
  /// time. The SERVER's `uses_declared_arrival` wins when present — see
  /// [CheckoutMode]. This is the offline/legacy answer only.
  bool get usesDeclaredArrival =>
      this == TransportMode.train ||
      this == TransportMode.metro ||
      this == TransportMode.tram;

  /// Look up a known mode by its wire value, or null when the server has sent
  /// one this build has never heard of.
  static TransportMode? byWire(String wire) {
    for (final m in TransportMode.values) {
      if (m.wire == wire) return m;
    }
    return null;
  }
}

/// One selectable chip, as the SERVER describes it.
///
/// Distinct from [TransportMode] on purpose. The enum is this build's registry
/// of modes it has an icon for; this is whatever the backend actually enabled
/// for the city, which may include a mode added after this app shipped.
///
/// That is the whole point of migration 030: a ninth mode is one INSERT, and it
/// must appear in an already-installed app rather than waiting for a release.
/// So an unknown code still renders — server label, fallback icon — and still
/// BEHAVES correctly, because `usesDeclaredArrival` travels with the data
/// instead of being inferred from a name the app does not recognise.
class CheckoutMode {
  const CheckoutMode({
    required this.wire,
    required this.label,
    required this.icon,
    required this.usesDeclaredArrival,
  });

  final String wire;
  final String label;
  final IconData icon;
  final bool usesDeclaredArrival;

  /// Generic transit glyph for a mode this build predates. Deliberately not a
  /// question mark or a warning: an unrecognised mode is a normal consequence
  /// of the server being ahead, not an error the customer should worry about.
  static const IconData _unknownIcon = Icons.directions_transit;

  /// Built from a server `transport_modes` entry.
  factory CheckoutMode.fromServer(OutletTransportMode m) {
    final known = TransportMode.byWire(m.code);
    return CheckoutMode(
      wire: m.code,
      // Server label wins — it is the one an admin can correct without a
      // release. Falls back to the built-in label only when blank.
      label: m.label.trim().isNotEmpty ? m.label.trim() : (known?.label ?? m.code),
      icon: known?.icon ?? _unknownIcon,
      usesDeclaredArrival: m.usesDeclaredArrival,
    );
  }

  /// Built from a mode this build knows, for the offline/legacy path.
  factory CheckoutMode.fromLocal(TransportMode m) => CheckoutMode(
        wire: m.wire,
        label: m.label,
        icon: m.icon,
        usesDeclaredArrival: m.usesDeclaredArrival,
      );

  /// The word for the vehicle, for copy that names it ("When does your tram
  /// arrive?"). Only meaningful for [usesDeclaredArrival] modes.
  ///
  /// Lower-cased server label rather than a hardcoded switch, so a mode added
  /// server-side gets correct copy with no app change.
  String get vehicleNoun => label.trim().toLowerCase();
}

/// Step 8: checkout with UPI / Card / Net Banking ONLY (no pay-at-counter).
class CheckoutScreen extends StatefulWidget {
  const CheckoutScreen({super.key, this.customerNotes});
  final String? customerNotes;

  @override
  State<CheckoutScreen> createState() => _CheckoutScreenState();
}

class _CheckoutScreenState extends State<CheckoutScreen> {
  bool _placing = false;

  /// Optional points-discount coupon code. Validated server-side at order
  /// creation — the app deliberately does no local check, so there is exactly
  /// one place that decides whether a code is spendable.
  final _coupon = TextEditingController();

  /// Held so the screen can answer "is the keyboard up?" — which is the same
  /// question as "does a field on this screen have focus". Needed by the
  /// [PopScope] in build(): a back press while typing must close the keyboard
  /// instead of leaving checkout.
  final _couponFocus = FocusNode();

  /// The offer the customer picked from the restaurant's list (migration 016).
  ///
  /// Mutually exclusive with [_coupon] because V1 does not stack: the server
  /// rejects an order carrying both, so the UI disables one when the other is
  /// in play rather than letting them build a basket that cannot be paid for.
  Offer? _offer;

  @override
  void initState() {
    super.initState();
    // Rebuild on focus change so PopScope.canPop is re-evaluated. Without this
    // the flag is read once and back would keep popping the screen even while
    // the keyboard is up.
    _couponFocus.addListener(_onFocusChanged);
  }

  void _onFocusChanged() {
    if (mounted) setState(() {});
  }

  @override
  void dispose() {
    _couponFocus.removeListener(_onFocusChanged);
    _couponFocus.dispose();
    _coupon.dispose();
    super.dispose();
  }

  /// Local preview of the saving, for the struck-through price. The server
  /// recomputes and is the authority — the order response carries the real
  /// original / discount / final figures.
  double _previewDiscount(double subtotal) =>
      _offer?.previewSaving(subtotal) ?? 0;

  // FR-C1/C2: travel context captured before the order is placed.
  /// The SELECTED mode's wire value, not an enum member.
  ///
  /// A string because the offered list is server-driven as of migration 030 and
  /// may contain a mode this build has no enum case for. Storing the enum would
  /// make such a mode unselectable — the exact thing 030 exists to avoid.
  String _transport = TransportMode.bike.wire;

  /// The modes offered for [outlet]'s city.
  ///
  /// Train and Metro are the conditional ones: both are satisfied by a DECLARED
  /// arrival time rather than an origin, so offering either where there is no
  /// such rail would collect a stated arrival for a journey that cannot happen
  /// — and that value goes straight into the timing engine. The other five are
  /// unconditional; walking, cycling and road transport exist everywhere.
  ///
  /// Gated SEPARATELY rather than off one "has rail" boolean. They genuinely
  /// come apart: a city can have a mainline junction and no metro (Madurai) or
  /// a metro and no useful suburban rail. One flag for both would have to be
  /// wrong about one of them, and the admin dashboard exposes them as two
  /// controls precisely so it does not have to be.
  /// The chips to render, SERVER-FIRST.
  ///
  /// When the outlet carries a `transport_modes` list (migration 030) that list
  /// IS the answer, verbatim and in server order — including any mode this
  /// build has never heard of, which renders with a fallback icon and still
  /// behaves correctly because `uses_declared_arrival` comes with it.
  ///
  /// The local branch below is the pre-030 fallback only. It cannot express
  /// Tram (nothing older than 030 knows about it), so it does not try.
  List<CheckoutMode> _modesFor(Outlet? outlet) {
    final server = CityTransport.serverModesFor(outlet);
    if (server != null) {
      return [for (final m in server) CheckoutMode.fromServer(m)];
    }
    final train = CityTransport.trainFor(outlet);
    final metro = CityTransport.metroFor(outlet);
    final tram = CityTransport.tramFor(outlet);
    return [
      for (final m in TransportMode.values)
        if (switch (m) {
          TransportMode.train => train,
          TransportMode.metro => metro,
          TransportMode.tram => tram,
          _ => true,
        })
          CheckoutMode.fromLocal(m),
    ];
  }

  /// [_transport], but never a mode this outlet does not offer.
  ///
  /// Belt and braces: Train can only be SELECTED from a list that already
  /// excluded it, so a stale selection is not reachable through the UI today.
  /// It is guarded anyway because the failure would be silent and would land in
  /// the prediction engine as a train order from a city with no trains — the
  /// kind of thing that is invisible until someone reads the data months later.
  /// [_transport], but never a mode this outlet does not offer.
  ///
  /// Belt and braces: a mode can only be SELECTED from a list that already
  /// excluded the others, so a stale selection is not reachable through the UI
  /// today. It is guarded anyway because the failure would be silent and would
  /// land in the prediction engine as (say) a tram order from a city with no
  /// trams — the kind of thing that is invisible until someone reads the data
  /// months later.
  ///
  /// Falls back to the first offered mode rather than a hardcoded `bike`: with
  /// a server-driven list there is no guarantee bike is even on it.
  CheckoutMode _effectiveMode(Outlet? outlet) {
    final allowed = _modesFor(outlet);
    for (final m in allowed) {
      if (m.wire == _transport) return m;
    }
    return allowed.isNotEmpty
        ? allowed.first
        : CheckoutMode.fromLocal(TransportMode.bike);
  }
  double? _originLat;
  double? _originLng;
  String _originSource = 'none'; // none | gps | places_autocomplete
  String? _originLabel;
  bool _locating = false;

  /// Whether this screen has already tried to resolve an origin.
  /// Gates the one-off deliberate prompt in [_selectMode].
  bool _originAttempted = false;

  /// Train mode only: the arrival time the customer states. Sent as
  /// `declared_arrival_at`; null for every other mode.
  DateTime? _declaredArrival;

  /// Set when Pay is tapped in train mode with no arrival time chosen. Drives
  /// the inline error; cleared as soon as a time is picked or the mode changes.
  bool _arrivalMissing = false;

  // --- scheduled pickup (migration 031) ------------------------------------

  /// False = order now (every order before this shipped). True = the customer
  /// has chosen "Pick a time".
  bool _scheduled = false;

  /// The pickup time chosen, once they have chosen one. Sent as
  /// `requested_pickup_at`; null for an ASAP order.
  DateTime? _requestedPickup;

  /// Set when Pay is tapped with scheduling on but no time chosen. Same
  /// treatment as [_arrivalMissing] — an inline message rather than a dead
  /// button, for the same reason.
  bool _pickupMissing = false;

  /// Client-side floor on how soon a slot may be. The SERVER is the authority
  /// and accepts anything from now onward (releasing immediately when there is
  /// no room to hold), so this is purely about not offering a "schedule" that
  /// is indistinguishable from ordering now.
  static const _minScheduleLead = Duration(minutes: 30);

  /// Subtracted from the outlet's closing time to get the last offerable slot.
  ///
  /// Mirrors the server's ORDER_CUTOFF_MINUTES, which is what
  /// outlet_availability enforces when the arrival gate evaluates the chosen
  /// instant. Matching it means the picker never offers a time the server will
  /// then refuse — the app is not re-implementing the rule, it is declining to
  /// contradict it.
  static const _schedulePrepAllowance = Duration(minutes: 30);

  /// Last slot this outlet can be asked for today, or null when it keeps no
  /// hours (always-open, so only the horizon applies).
  DateTime? _latestSlotFor(Outlet? outlet) {
    final close = outlet?.nextCloseAfter(DateTime.now());
    if (close == null) return null;
    return close.subtract(_schedulePrepAllowance);
  }

  Future<void> _pickPickupTime(Outlet? outlet) async {
    final now = DateTime.now();
    final latest = _latestSlotFor(outlet);
    // An outlet with no hours on record is always-open server-side, so falling
    // back to the end of today is the honest bound — NOT refusing to offer a
    // picker, which would read as "scheduling is unavailable here" when in fact
    // it is unconstrained.
    final ceiling = latest ??
        DateTime(now.year, now.month, now.day, 23, 59);

    final when = await ArrivalTimePicker.show(
      context,
      initial: now.add(const Duration(minutes: 45)),
      // Unused once `latest` is given, but the parameter is required and the
      // two must not disagree if that ever changes.
      maxAhead: ceiling.difference(now),
      latest: ceiling,
      minAhead: _minScheduleLead,
      title: 'When would you like to collect?',
      confirmLabel: 'Set pickup time',
    );
    if (when == null || !mounted) return;
    setState(() {
      _requestedPickup = when;
      _pickupMissing = false;
    });
  }

  /// Whether this outlet can be asked for a future slot at all.
  ///
  /// Offered while the outlet is open OR closing soon — closing_soon is the
  /// window where scheduling is most useful, since "no room to cook that now"
  /// is not an answer to a request for later. A fully closed shutter offers
  /// nothing, matching the server, which refuses scheduled orders there too.
  bool _canSchedule(Outlet? outlet) =>
      outlet == null || outlet.orderStatus != 'closed';

  /// Upper bound on how far ahead an arrival may be declared.
  ///
  /// 6h is generous enough for a genuine long-distance train while still
  /// rejecting a mistyped date — the real risk is a customer picking a time
  /// that has already passed today, or fat-fingering tomorrow, and the
  /// kitchen being told to start cooking at a nonsense moment.
  static const _maxArrivalAhead = Duration(hours: 6);

  Future<void> _pickArrivalTime() async {
    final now = DateTime.now();
    // Scrolling wheels, not the clock dial. The dial asks you to think in
    // angles; a train arrival is a number you were told. The sheet does its own
    // roll-to-tomorrow and its own max-ahead check, so it can never hand back a
    // value this screen would then have to reject.
    final when = await ArrivalTimePicker.show(
      context,
      initial: now.add(const Duration(minutes: 45)),
      maxAhead: _maxArrivalAhead,
      // The sheet names the same vehicle the heading that opened it does.
      // Effective, not raw, for the same reason as everywhere else here: the
      // picker must never name a mode the chip row did not offer.
      vehicleNoun: _effectiveMode(context.read<CartState>().outlet).vehicleNoun,
    );
    if (when == null || !mounted) return;
    setState(() {
      _declaredArrival = when;
      // Clear the blocking message the moment it stops being true.
      _arrivalMissing = false;
    });
  }

  /// Picks a transport mode AND settles the origin it implies, in one tap.
  ///
  /// Choosing "Bike" already means "I am travelling here, from where I am" —
  /// so the location ask belongs to that tap, not to a second control further
  /// down the screen. Previously the two were disconnected: the chip set a
  /// mode, and the customer then had to find "Use GPS" under a separate
  /// heading before anything could be timed. Most never did, which is how
  /// orders arrived carrying a mode and no origin.
  ///
  /// Three things it deliberately does NOT do:
  ///
  ///  * **Never overwrites an origin that already exists.** A searched address
  ///    is a deliberate choice; stomping it with GPS because the customer then
  ///    switched Bike→Car would silently discard it.
  ///  * **Never re-asks once blocked.** `deniedForever` means the OS swallows
  ///    the dialog, so calling out to it would buy a no-op await. The origin
  ///    card still offers the route to Settings.
  ///  * **Asks at most once per grant state.** `userInitiated` is left FALSE
  ///    on purpose — the latch in LocationService is what stops tapping
  ///    through five chips from raising five dialogs. The tap means "I'm
  ///    coming by car", not "locate me"; only the explicit Use-GPS button
  ///    carries the second meaning, and only it re-prompts.
  ///
  /// FR-C6 is unchanged either way: a refusal leaves the origin at `none` and
  /// checkout proceeds with a wider, approximate wait.
  Future<void> _selectMode(CheckoutMode mode) async {
    // Re-tapping the mode already selected is the RETRY gesture.
    //
    // Migration 030 removed the separate "Your starting point" card, so there
    // is no longer a "Use GPS" button to press after a refusal. Re-tapping the
    // active chip takes its place: it is the only control on screen that still
    // means "this is how I am travelling", and repeating that is a reasonable
    // way to say "try again".
    //
    // userInitiated: true is what makes it a real retry — it bypasses
    // LocationService's one-prompt latch, so the OS dialog is raised again
    // rather than silently swallowed (see getCurrentLocation for why the latch
    // has to be bypassed for a deliberate tap). A FIRST tap stays
    // userInitiated: false so tapping through five chips cannot stack five
    // dialogs.
    final isRetap = _transport == mode.wire;

    // FIRST resolve on this screen also counts as deliberate.
    //
    // Without this, a denial on Discover's "Near me" would leave the app-wide
    // one-prompt latch set, and the first chip tap here would fall through to a
    // silent refusal — the app suppressing its own dialog, which is the exact
    // bug LocationService's latch was rewritten to stop. The removed Use-GPS
    // button used to carry this weight by always passing userInitiated: true.
    //
    // It is scoped to the first attempt only, so tapping through five chips
    // still cannot stack five dialogs: attempts 2..n are plain switches.
    final isFirstAttempt = !_originAttempted;

    setState(() {
      _transport = mode.wire;
      // Switching away from a declared-arrival mode retires the error with the
      // requirement that produced it.
      if (!mode.usesDeclaredArrival) _arrivalMissing = false;
    });

    // A declared-arrival leg is a stated time, not a place — no origin to get.
    if (mode.usesDeclaredArrival) return;

    // Already answered, by GPS or by address search. Reuse it — unless this is
    // a deliberate re-tap, which is how someone replaces an origin they are
    // unhappy with now that the separate control is gone.
    if (_originSource != 'none' && !isRetap) return;

    // A tap the customer meant: the first resolve on this screen, or a re-tap
    // on the chip already chosen. Both raise the OS dialog; a plain switch
    // between chips does not, so five chips cannot stack five prompts.
    final deliberate = isRetap || isFirstAttempt;

    final service = context.read<LocationService>();

    // ---------------- STAGE 2, arrived at from an earlier session ----------
    // Already permanently denied before this screen was opened. The OS
    // suppresses its dialog entirely, so a deliberate tap must get the
    // explanation or it is a dead control — the precise failure this whole
    // flow was fixed for.
    if (service.isBlocked) {
      if (deliberate && mounted) await _explainBlocked(service);
      return;
    }

    _originAttempted = true;
    final res = await _resolveOrigin(userInitiated: deliberate);
    if (!mounted) return;

    // ---------------- STAGE 2, arrived at just now -------------------------
    // Android flips `denied` to `deniedForever` on the SECOND refusal, so the
    // decline that just happened is the one that made it permanent. The
    // escalation belongs here, immediately — not on some later tap the
    // customer has no reason to make, and which was where it used to sit.
    //
    // Unconditional: they are looking at the consequence of a prompt they just
    // dismissed, so this is an answer, not an ambush.
    if (res.outcome == LocationOutcome.deniedForever) {
      await _explainBlocked(service);
      return;
    }

    // ---------------- STAGE 1 ----------------------------------------------
    // A plain `denied` is deliberately SILENT. No dialog, no snackbar, no
    // nagging: the chip stays tappable and a re-tap re-prompts normally. The
    // customer said no once and is allowed to have meant it.
  }

  /// The escalation: explain, and offer the only thing that can still fix it.
  Future<void> _explainBlocked(LocationService service) =>
      showLocationBlockedDialog(
        context,
        service: service,
        purpose: 'estimate your travel time to the restaurant',
      );

  /// Reads a GPS fix and folds the outcome into the origin fields.
  ///
  /// Shared by both entry points; [userInitiated] is the entire difference
  /// between them. The explicit "Use GPS" button passes true and re-asks every
  /// time — see LocationService.getCurrentLocation for why that has to bypass
  /// the latch. Mode selection passes false and asks once per grant state.
  Future<LocationResult> _resolveOrigin({required bool userInitiated}) async {
    setState(() => _locating = true);
    final service = context.read<LocationService>();

    late final LocationResult res;
    try {
      res = await service.getCurrentLocation(userInitiated: userInitiated);
    } finally {
      // Cleared BEFORE any dialog the caller shows, so the button is not left
      // spinning behind a modal the customer has to read.
      if (mounted) setState(() => _locating = false);
    }
    if (!mounted) return res;

    if (res.hasCoordinates) {
      setState(() {
        _originLat = res.latitude;
        _originLng = res.longitude;
        _originSource = 'gps';
        _originLabel = 'Current location';
      });
    } else {
      // FR-C6: denial degrades gracefully — the order still goes through,
      // the estimate is just wider/approximate.
      setState(() {
        _originLat = null;
        _originLng = null;
        _originSource = 'none';
        _originLabel = null;
      });
    }
    return res;
  }

  // REMOVED with the "Your starting point" card (migration 030):
  //   _useMyLocation()  — the "Use GPS" button is gone; a re-tap on the
  //                       selected chip is the retry, and _selectMode passes
  //                       userInitiated: true for exactly that case.
  //   _searchLocation() — the Places address-search entry point went with the
  //                       card that hosted it. WORTH KNOWING: that removes the
  //                       only way to give an origin WITHOUT granting GPS.
  //                       Someone who declines location now has no manual
  //                       fallback and always gets the wide estimate. FR-C6
  //                       still holds (the order goes through), but this is a
  //                       real capability loss, not just a moved button.

  /// Hard availability gate, run BEFORE payment.
  ///
  /// Returns true when the order may proceed. When items have gone unavailable
  /// since they were added, this prompts to remove them and returns false —
  /// the customer is never charged for a basket the kitchen cannot fulfil, and
  /// never discovers the problem after committing.
  Future<bool> _ensureAvailable(CartState cart) async {
    final outletId = cart.outletId;
    if (outletId == null || cart.isEmpty) return true;

    final orders = context.read<OrderService>();
    final List<String> unavailableIds;
    try {
      unavailableIds = await orders.checkCartAvailability(
        outletId: outletId,
        menuItemIds: cart.items.map((i) => i.item.id).toSet().toList(),
      );
    } on ApiException {
      // The pre-check is a courtesy, not the authority. If it cannot run, let
      // create_order's server-side validation be the gate rather than blocking
      // a legitimate order on a flaky network call.
      return true;
    }
    if (unavailableIds.isEmpty || !mounted) return unavailableIds.isEmpty;

    final names = cart.items
        .where((i) => unavailableIds.contains(i.item.id))
        .map((i) => i.item.name)
        .toSet()
        .toList();

    final removed = await showDialog<bool>(
      context: context,
      builder: (c) => AlertDialog(
        title: Text(
          names.length == 1 ? 'An item just sold out' : 'Some items just sold out',
        ),
        content: Column(
          mainAxisSize: MainAxisSize.min,
          crossAxisAlignment: CrossAxisAlignment.start,
          children: [
            Text(
              names.length == 1
                  ? '${names.first} is no longer available at this restaurant.'
                  : 'These are no longer available at this restaurant:',
            ),
            if (names.length > 1) ...[
              const SizedBox(height: 8),
              ...names.map((n) => Text('•  $n')),
            ],
            const SizedBox(height: 12),
            const Text(
              'Remove them to continue — you have not been charged.',
              style: TextStyle(fontSize: 12),
            ),
          ],
        ),
        actions: [
          TextButton(
            onPressed: () => Navigator.pop(c, false),
            child: const Text('Back to cart'),
          ),
          FilledButton(
            onPressed: () => Navigator.pop(c, true),
            child: Text(names.length == 1 ? 'Remove it' : 'Remove them'),
          ),
        ],
      ),
    );

    if (removed == true) {
      cart.removeUnavailable(unavailableIds.toSet());
    }
    // Always false: even after removing, the customer re-confirms the new total
    // rather than having a smaller order silently charged.
    return false;
  }

  Future<void> _payNow() async {
    final cart = context.read<CartState>();

    // Train and Metro REQUIRE an arrival time — it is the only input the timing
    // engine has for these modes (there is no GPS origin to infer from), so an
    // order without it cannot be scheduled at all. Gated on the shared
    // `usesDeclaredArrival` rather than a mode literal, which is why adding
    // Metro to that getter was enough to cover this path too.
    //
    // Surfaced as an inline message on the field, not a silently disabled Pay
    // button: a button that does nothing when tapped teaches the customer that
    // the app is broken, and gives them nothing to act on.
    final mode = _effectiveMode(cart.outlet);
    if (mode.usesDeclaredArrival && _declaredArrival == null) {
      setState(() => _arrivalMissing = true);
      return;
    }

    // Scheduling turned on but no slot chosen. Same shape as the arrival check
    // above and for the same reason — a Pay button that silently does nothing
    // teaches the customer the app is broken.
    if (_scheduled && _requestedPickup == null) {
      setState(() => _pickupMissing = true);
      return;
    }

    setState(() => _placing = true);
    try {
      if (!await _ensureAvailable(cart)) return;
      if (!mounted) return;
      final order = await context.read<OrderService>().createOrder(
            cart.toOrderPayload(
              customerNotes: widget.customerNotes,
              transportMode: mode.wire,
              originLat: _originLat,
              originLng: _originLng,
              originSource: _originSource,
              // Never both: an offer takes precedence over a leftover coupon
              // code, matching the mutual exclusion the UI already enforces.
              couponCode: _offer == null ? _coupon.text : null,
              promotionId: _offer?.id,
              declaredArrivalAt:
                  mode.usesDeclaredArrival ? _declaredArrival : null,
              // Only when the toggle is actually on: a stale _requestedPickup
              // left over from switching back to ASAP must not quietly hold
              // the order.
              requestedPickupAt: _scheduled ? _requestedPickup : null,
            ),
          );
      if (!mounted) return;

      // Stub backend (no Cashfree session): keep the simulate path so dev and
      // any deploy still on PAYMENT_GATEWAY=stub remains walkable.
      if (!(order.payment?.isCashfree ?? false)) {
        Navigator.of(context).push(
          MaterialPageRoute(
            builder: (_) => PaymentProcessingScreen(
              order: order,
              // Nominal only — the stub records a method string and does not
              // branch on it. The customer no longer picks one.
              method: PaymentMethod.upi,
            ),
          ),
        );
        return;
      }

      // Cashfree Drop-in. UPI, cards and netbanking all live inside this
      // sheet, which is why the app no longer asks the customer to choose.
      final result = await context.read<CashfreeService>().openCheckout(
            orderId: order.id,
            paymentSessionId: order.payment!.paymentSessionId!,
          );
      if (!mounted) return;

      if (result.outcome == CheckoutOutcome.notStarted) {
        // Never opened, so nothing was charged and nothing needs confirming.
        ScaffoldMessenger.of(context).showSnackBar(SnackBar(
          content: Text(result.message ?? 'Could not open payment.'),
        ));
        return;
      }

      // BOTH outcomes go to PickupScreen, which is now state-aware — the same
      // single destination checkout had before the retry fix, restored. What
      // the SDK reports decides only which STATE that screen opens in, never
      // whether the order is paid.
      //
      // Neither the SDK's yes nor its no is trustworthy: onVerify can fire for a
      // payment the bank later reverses, and can fail to fire for one that
      // genuinely succeeded (app killed, network dropped returning from a UPI
      // app). Only the webhook moves an order to PAID — so on a NO, PickupScreen
      // opens in its "confirming" state, polls the server for a grace window,
      // and only surfaces "Try Payment Again" if payment is still unconfirmed
      // when that window closes. A YES opens it straight on the normal path.
      //
      // The cart is NOT cleared here on either branch: payment_status is still
      // whatever the server last knew. PickupScreen clears it once the order is
      // actually observed PAID.
      Navigator.of(context).pushReplacement(
        MaterialPageRoute(
          builder: (_) => PickupScreen(
            orderId: order.id,
            amount: order.finalAmount,
            // A verified sheet needs no confirmation dance; a dismissed or
            // failed one does. The order is carried through only in the latter
            // case, because retry reopens ITS payment session.
            awaitingPayment: !result.verified,
            paymentOrder: result.verified ? null : order,
            paymentReason: result.verified ? null : result.message,
          ),
        ),
      );
    } on ApiException catch (e) {
      if (mounted) {
        ScaffoldMessenger.of(context)
            .showSnackBar(SnackBar(content: Text(e.message)));
      }
    } catch (_) {
      if (mounted) {
        ScaffoldMessenger.of(context).showSnackBar(
          const SnackBar(content: Text('Could not place order. Try again.')),
        );
      }
    } finally {
      if (mounted) setState(() => _placing = false);
    }
  }

  @override
  Widget build(BuildContext context) {
    final cart = context.watch<CartState>();
    final textTheme = Theme.of(context).textTheme;
    final c = AppColors.of(context);

    final subtotal = cart.subtotal;
    final discount = _previewDiscount(subtotal);
    final payable = (subtotal - discount).clamp(0.0, subtotal);

    // Operating-hours gate (migration 024). The server is the hard gate — it
    // refuses the order at creation — but disabling Pay here, with the reason,
    // means the customer is told before they tap rather than after. Null outlet
    // (should not happen on this screen) is treated as "accepting" so the
    // server stays the authority.
    //
    // SPLIT IN TWO by scheduled pickup (031). This used to be a single
    // !isAcceptingOrders test, which collapses 'closed' and 'closing_soon' into
    // one refusal — and that would have made scheduling unreachable at exactly
    // the moment it earns its keep. "We cannot cook that in the 20 minutes we
    // have left" is a true statement about ordering NOW and says nothing about
    // a request for 19:30.
    //
    // So: a closed shutter still blocks everything (the server agrees, and
    // refuses scheduled orders there too), while closing_soon blocks only the
    // ASAP path and steps aside once a slot has actually been chosen.
    final outlet = cart.outlet;
    final closed = outlet != null && outlet.orderStatus == 'closed';
    final closingSoon = outlet != null && outlet.orderStatus == 'closing_soon';
    final hasSlot = _scheduled && _requestedPickup != null;
    final blocked = closed || (closingSoon && !hasSlot);

    // Back closes the keyboard BEFORE it leaves checkout.
    //
    // Android's back already dismisses the IME at the platform level, but the
    // field keeps focus — so the caret goes on blinking and the NEXT back pops
    // the screen out from under someone who was still mid-coupon. Consuming the
    // first back and releasing focus makes the two presses mean the obvious
    // things: close the keyboard, then leave.
    //
    // Nothing about the order is touched, so checkout is exactly resumable:
    // the typed code stays in _coupon and the field simply loses focus.
    return PopScope(
      canPop: !_couponFocus.hasFocus,
      onPopInvokedWithResult: (didPop, _) {
        if (!didPop) releaseFocus();
      },
      child: _buildScaffold(context, cart, textTheme, c, subtotal, discount,
          payable, outlet, blocked, closingSoon),
    );
  }

  Widget _buildScaffold(
    BuildContext context,
    CartState cart,
    TextTheme textTheme,
    AppColorScheme c,
    double subtotal,
    double discount,
    double payable,
    Outlet? outlet,
    bool blocked,
    bool closingSoon,
  ) {
    return Scaffold(
      appBar: AppBar(
        title: const Text('Checkout'),
        actions: careVoActions(),
      ),
      bottomNavigationBar: SafeArea(
        top: false,
        child: Padding(
          padding: const EdgeInsets.fromLTRB(16, 8, 16, 16),
          child: Column(
            mainAxisSize: MainAxisSize.min,
            children: [
              if (blocked) ...[
                Row(
                  key: const Key('checkout_closed_reason'),
                  children: [
                    Icon(Icons.block, size: 18, color: AppColors.tomato),
                    const SizedBox(width: 8),
                    Expanded(
                      child: Text(
                        // `blocked` is only true when outlet is non-null, but
                        // that promotion is lost across the parameter boundary.
                        //
                        // When it is closing_soon the refusal has a way out —
                        // say so, rather than leaving the customer to discover
                        // the toggle further up the page on their own.
                        closingSoon
                            ? 'Too close to closing for an order right now — '
                                'pick a pickup time above to schedule one.'
                            : (outlet!.closedReason ??
                                'This outlet is not accepting orders right now.'),
                        style: textTheme.bodyMedium
                            ?.copyWith(color: AppColors.tomato),
                      ),
                    ),
                  ],
                ),
                const SizedBox(height: 10),
              ],
              NeoButton(
                key: const Key('checkout_pay'),
                label: blocked
                    ? outlet!.statusLabel
                    : 'Pay ${formatRupees(payable)}',
                icon: blocked ? Icons.block : Icons.lock,
                loading: _placing,
                onPressed: (cart.isEmpty || blocked) ? null : _payNow,
              ),
            ],
          ),
        ),
      ),
      body: SafeArea(
        bottom: false,
        child: ListView(
          padding: const EdgeInsets.fromLTRB(20, 12, 20, 24),
          children: [
            Text('Confirm order', style: textTheme.headlineSmall),
            const SizedBox(height: 5),
            Text('Review your details before paying.',
                style: textTheme.titleSmall?.copyWith(color: c.inkSoft)),
            const SizedBox(height: 16),
            _PickupOutletCard(outlet: cart.outlet),
            const SizedBox(height: 24),
            Text('How are you getting here?', style: textTheme.headlineSmall),
            const SizedBox(height: 6),
            Text('Helps us time your food so it\'s fresh when you arrive.',
                style: textTheme.bodyMedium?.copyWith(color: c.inkSoft)),
            const SizedBox(height: 14),
            Wrap(
              spacing: 10,
              runSpacing: 10,
              children: [
                for (final mode in _modesFor(cart.outlet))
                  _TransportChip(
                    mode: mode,
                    selected: _transport == mode.wire,
                    // Selecting a mode also settles the origin that mode
                    // implies — see _selectMode. The location ask lives inside
                    // this one tap rather than in a second control below.
                    onTap: () => _selectMode(mode),
                  ),
              ],
            ),
            const SizedBox(height: 24),
            // Train and Metro replace the origin picker entirely: Leg A is a
            // stated time, so a GPS origin would be collected and then ignored.
            // Effective, not raw: the arrival picker must never appear for a
            // mode the chip row did not offer.
            if (_effectiveMode(cart.outlet).usesDeclaredArrival) ...[
              // Named after the mode actually chosen. Asking a metro rider when
              // their "train" arrives is the kind of small wrongness that makes
              // someone doubt the app knows what they picked.
              Text(
                  'When does your '
                  '${_effectiveMode(cart.outlet).vehicleNoun} arrive?',
                  style: textTheme.headlineSmall),
              const SizedBox(height: 6),
              Text(
                  'Required — it is the only timing signal '
                  '${_effectiveMode(cart.outlet).vehicleNoun} mode has.',
                  style: textTheme.bodyMedium?.copyWith(color: c.inkSoft)),
              const SizedBox(height: 12),
              NeoCard(
                key: const Key('arrival_field'),
                onTap: _pickArrivalTime,
                color: _declaredArrival != null ? c.accent : c.surface,
                // A red border, not a red field: the control is incomplete, not
                // wrong, and it stays readable while it is being corrected.
                borderColor: _arrivalMissing ? AppColors.tomato : null,
                child: Row(
                  children: [
                    Icon(Icons.schedule,
                        color: _declaredArrival != null ? c.onAccent : c.ink),
                    const SizedBox(width: 14),
                    Expanded(
                      child: Text(
                        _declaredArrival == null
                            ? 'Set arrival time'
                            : '${DayPart.forHour(_declaredArrival!.hour).label}'
                                ' · '
                                '${TimeOfDay.fromDateTime(_declaredArrival!).format(context)}',
                        style: textTheme.titleMedium?.copyWith(
                            color: _declaredArrival != null ? c.onAccent : c.ink),
                      ),
                    ),
                    Icon(Icons.edit,
                        size: 18,
                        color: _declaredArrival != null ? c.onAccent : c.inkSoft),
                  ],
                ),
              ),
              if (_arrivalMissing) ...[
                const SizedBox(height: 8),
                Row(
                  key: const Key('arrival_required_error'),
                  children: [
                    Icon(Icons.error_outline,
                        size: 18, color: AppColors.tomato),
                    const SizedBox(width: 8),
                    Expanded(
                      child: Text(
                        'Set your arrival time before paying — we cannot time '
                        'the kitchen without it.',
                        style: textTheme.bodyMedium
                            ?.copyWith(color: AppColors.tomato),
                      ),
                    ),
                  ],
                ),
              ],
            ] else ...[
              // The separate "Your starting point" card is GONE (migration 030).
              //
              // It was a second, disconnected place to answer a question the
              // chip above already implies, and it sat far enough down a long
              // page that most customers never reached it — which is how orders
              // arrived carrying a mode and no origin. Location now resolves
              // only through the chip tap; re-tapping the selected chip retries.
              //
              // What remains is a one-line STATUS, not a control: it says what
              // the app has, and nothing else. Deliberately quiet — the origin
              // is optional (FR-C6) and a prominent card implied otherwise.
              _OriginStatus(
                originLabel: _originLabel,
                locating: _locating,
                key: const Key('checkout_origin_status'),
              ),
            ],
            // --- scheduled pickup (migration 031) ------------------------
            // Placed after the travel question and before payment: the two
            // answers together are what let the kitchen be timed, and the
            // choice has to be made before money moves — the server refuses an
            // infeasible slot at order creation, which is only useful if the
            // customer has already picked one.
            if (_canSchedule(cart.outlet)) ...[
              const SizedBox(height: 24),
              Text('When do you want it?', style: textTheme.headlineSmall),
              const SizedBox(height: 6),
              Text(
                _scheduled
                    ? 'We\'ll hold your order and send it to the kitchen so '
                        'it\'s ready when you arrive.'
                    : 'Order now, or pick a time later today.',
                style: textTheme.bodyMedium?.copyWith(color: c.inkSoft),
              ),
              const SizedBox(height: 14),
              Row(
                key: const Key('schedule_toggle'),
                children: [
                  Expanded(
                    child: _ScheduleChoice(
                      key: const Key('schedule_asap'),
                      label: 'Order now',
                      icon: Icons.bolt,
                      selected: !_scheduled,
                      onTap: () => setState(() {
                        _scheduled = false;
                        _pickupMissing = false;
                      }),
                    ),
                  ),
                  const SizedBox(width: 10),
                  Expanded(
                    child: _ScheduleChoice(
                      key: const Key('schedule_later'),
                      label: 'Pick a time',
                      icon: Icons.schedule,
                      selected: _scheduled,
                      onTap: () {
                        setState(() => _scheduled = true);
                        // Opening the picker on the same tap: choosing "Pick a
                        // time" and then having to find a second control to
                        // actually pick one is the disconnect that lost the
                        // origin card its origins (migration 030).
                        _pickPickupTime(cart.outlet);
                      },
                    ),
                  ),
                ],
              ),
              if (_scheduled) ...[
                const SizedBox(height: 12),
                NeoCard(
                  key: const Key('pickup_time_field'),
                  onTap: () => _pickPickupTime(cart.outlet),
                  color: _requestedPickup != null ? c.accent : c.surface,
                  borderColor: _pickupMissing ? AppColors.tomato : null,
                  child: Row(
                    children: [
                      Icon(Icons.schedule,
                          color: _requestedPickup != null ? c.onAccent : c.ink),
                      const SizedBox(width: 14),
                      Expanded(
                        child: Text(
                          _requestedPickup == null
                              ? 'Set pickup time'
                              : 'Ready for '
                                  '${TimeOfDay.fromDateTime(_requestedPickup!).format(context)}',
                          style: textTheme.titleMedium?.copyWith(
                              color: _requestedPickup != null
                                  ? c.onAccent
                                  : c.ink),
                        ),
                      ),
                      Icon(Icons.edit,
                          size: 18,
                          color: _requestedPickup != null
                              ? c.onAccent
                              : c.inkSoft),
                    ],
                  ),
                ),
                if (_pickupMissing) ...[
                  const SizedBox(height: 8),
                  Row(
                    key: const Key('pickup_required_error'),
                    children: [
                      Icon(Icons.error_outline,
                          size: 18, color: AppColors.tomato),
                      const SizedBox(width: 8),
                      Expanded(
                        child: Text(
                          'Choose a pickup time, or switch back to Order now.',
                          style: textTheme.bodyMedium
                              ?.copyWith(color: AppColors.tomato),
                        ),
                      ),
                    ],
                  ),
                ],
              ],
            ],
            const SizedBox(height: 24),
            Text('Offers', style: textTheme.headlineSmall),
            const SizedBox(height: 6),
            Text(
              _offer == null
                  ? 'Pick one offer for this order.'
                  : 'One offer per order.',
              style: textTheme.bodyMedium?.copyWith(color: c.inkSoft),
            ),
            const SizedBox(height: 12),
            _OfferPicker(
              offer: _offer,
              // No picker without an outlet — offers are per restaurant, and
              // the cart is always bound to one before checkout is reachable.
              onBrowse: cart.outlet == null
                  ? null
                  : () => showOffersSheet(
                        context,
                        outlet: cart.outlet!,
                        subtotal: subtotal,
                        onApply: (o) => setState(() {
                          _offer = o;
                          // Mutual exclusion, made visible: adopting an offer
                          // clears a half-typed coupon rather than leaving a
                          // field the server would reject.
                          _coupon.clear();
                        }),
                      ),
              onClear: () => setState(() => _offer = null),
            ),
            const SizedBox(height: 24),
            Text('Have a coupon?', style: textTheme.headlineSmall),
            const SizedBox(height: 6),
            Text(
              _offer == null
                  ? 'Redeem points in your account to get a code.'
                  : 'Remove the offer above to use a points coupon instead.',
              style: textTheme.bodyMedium?.copyWith(color: c.inkSoft),
            ),
            const SizedBox(height: 12),
            TextField(
              key: const Key('checkout_coupon_field'),
              controller: _coupon,
              focusNode: _couponFocus,
              // Disabled, not hidden: the customer can see why it is
              // unavailable and what to do about it.
              enabled: _offer == null,
              autocorrect: false,
              enableSuggestions: false,
              textCapitalization: TextCapitalization.characters,
              // The three dismissal routes. This is a raw TextField rather than
              // a NeoTextField (it needs the label + prefix icon decoration),
              // which is exactly how it missed the fix NeoTextField already
              // carries — see the note on NeoTextField.onTapOutside for why a
              // null onTapOutside leaves the IME up on Android.
              //
              //  * tap outside  -> onTapOutside
              //  * confirm key  -> textInputAction + onSubmitted
              //  * back button  -> the PopScope in build()
              onTapOutside: (_) => releaseFocus(),
              // "Done", not "Next": this is the last field on the screen, and
              // the coupon is validated server-side at order creation, so the
              // key has nothing to submit — its whole job is to put the
              // keyboard away.
              textInputAction: TextInputAction.done,
              onSubmitted: (_) => releaseFocus(),
              decoration: const InputDecoration(
                labelText: 'Coupon code (optional)',
                hintText: 'PTS-ABCD2345',
                prefixIcon: Icon(Icons.confirmation_number_outlined),
              ),
            ),
            const SizedBox(height: 24),
            Text('Payment', style: textTheme.headlineSmall),
            const SizedBox(height: 6),
            // No method picker any more: Cashfree's sheet presents UPI, cards
            // and netbanking itself, and handing card entry to them is what
            // keeps card details out of this app entirely.
            Text(
              'Pay securely with UPI, card or net banking. '
              'Counter payment is not available.',
              style: textTheme.bodyMedium?.copyWith(color: c.inkSoft),
            ),
            const SizedBox(height: 16),
            NeoCard(
              child: Row(
                children: [
                  Icon(Icons.lock_outline, color: c.primary),
                  const SizedBox(width: 14),
                  Expanded(
                    child: Text(
                      'You\'ll choose how to pay on the next screen.',
                      style: textTheme.bodyMedium,
                    ),
                  ),
                ],
              ),
            ),
            const SizedBox(height: 20),
            _TotalRow(
              key: const Key('checkout_total_row'),
              items: cart.items,
              subtotal: subtotal,
              discount: discount,
              payable: payable,
              offerLabel: _offer?.benefitText,
            ),
            const SizedBox(height: 14),
            Text(
              'Your pickup code appears the moment payment succeeds.',
              textAlign: TextAlign.center,
              style: textTheme.bodySmall?.copyWith(color: c.inkSoft),
            ),
          ],
        ),
      ),
    );
  }
}

/// Where the customer is confirming they will collect the order from.
///
/// Shows the restaurant as "{Name} · {Locality}", the full address in plain
/// text, and a hand-off to Google Maps. The address is spelled out rather than
/// left implicit because this is the last screen before payment — it is where
/// someone realises they picked the wrong branch of a chain, and a name alone
/// is exactly what makes two branches indistinguishable.
///
/// The Maps hand-off is a plain universal URL, NOT a Maps SDK or an embedded
/// map: it needs no API key, no billing, and no extra dependency (url_launcher
/// is already a dependency for the payment flow). It also means the customer
/// lands in whatever maps app they actually use.
class _PickupOutletCard extends StatelessWidget {
  const _PickupOutletCard({required this.outlet});

  final Outlet? outlet;

  /// Opens the outlet's coordinates in Google Maps (or the platform's handler
  /// for that URL). Never called without coordinates — the button is not
  /// rendered in that case.
  Future<void> _openInMaps(BuildContext context) async {
    final o = outlet;
    if (o == null || !o.hasCoordinates) return;

    // Coordinates, not a name query: a name search can land on a different
    // branch of the same chain, which is the precise failure this screen
    // exists to prevent.
    final uri = Uri.parse(
      'https://www.google.com/maps/search/?api=1'
      '&query=${o.latitude},${o.longitude}',
    );

    // externalApplication so it opens the Maps app rather than an in-app
    // webview, which is what a customer about to travel actually wants.
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
    final textTheme = Theme.of(context).textTheme;
    final o = outlet;

    return NeoCard(
      color: c.primary,
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          Row(
            crossAxisAlignment: CrossAxisAlignment.start,
            children: [
              Icon(Icons.storefront, color: c.onPrimary),
              const SizedBox(width: 12),
              Expanded(
                child: Text(
                  'Self pickup at ${o?.displayName ?? 'the outlet'}',
                  style: textTheme.titleMedium?.copyWith(color: c.onPrimary),
                ),
              ),
            ],
          ),
          // Full address, plainly. Hidden entirely when the outlet has none on
          // record rather than showing an empty line.
          if (o != null && o.address.isNotEmpty) ...[
            const SizedBox(height: 10),
            Padding(
              // Aligns under the title, clear of the storefront icon.
              padding: const EdgeInsets.only(left: 36),
              child: Text(
                o.address,
                style: textTheme.bodyMedium?.copyWith(color: c.onPrimary),
              ),
            ),
          ],
          // Only offered when there is actually a pin to open. Outlets that
          // never captured coordinates simply show the address.
          if (o != null && o.hasCoordinates) ...[
            const SizedBox(height: 14),
            Align(
              alignment: Alignment.centerLeft,
              child: NeoButton(
                label: 'Open in Maps',
                icon: Icons.map_outlined,
                // Sits on a primary-coloured card, so it takes the neutral
                // variant — a primary-on-primary button would disappear.
                variant: NeoButtonVariant.neutral,
                // Secondary to "Pay now": inline and compact rather than a
                // full-width bar competing with the actual call to action.
                expand: false,
                compact: true,
                onPressed: () => _openInMaps(context),
              ),
            ),
          ],
        ],
      ),
    );
  }
}

/// "Add an offer" / the chosen offer, with a way back out.
class _OfferPicker extends StatelessWidget {
  const _OfferPicker({
    required this.offer,
    required this.onBrowse,
    required this.onClear,
  });

  final Offer? offer;
  final VoidCallback? onBrowse;
  final VoidCallback onClear;

  @override
  Widget build(BuildContext context) {
    final c = AppColors.of(context);
    final textTheme = Theme.of(context).textTheme;
    final chosen = offer;

    if (chosen == null) {
      return NeoCard(
        onTap: onBrowse,
        child: Row(
          children: [
            Icon(Icons.local_offer_outlined, color: c.primary),
            const SizedBox(width: 14),
            Expanded(
              child: Text('See offers at this restaurant',
                  style: textTheme.titleMedium),
            ),
            Icon(Icons.chevron_right, color: c.inkSoft),
          ],
        ),
      );
    }

    return NeoCard(
      color: c.accent,
      child: Row(
        children: [
          Icon(Icons.local_offer, color: c.onAccent),
          const SizedBox(width: 14),
          Expanded(
            child: Column(
              crossAxisAlignment: CrossAxisAlignment.start,
              children: [
                Text(chosen.benefitText,
                    style: textTheme.titleMedium?.copyWith(color: c.onAccent)),
                Text(
                  chosen.isCareVo ? 'CareVo offer' : 'Restaurant offer',
                  style: textTheme.bodySmall?.copyWith(color: c.onAccent),
                ),
              ],
            ),
          ),
          IconButton(
            tooltip: 'Remove offer',
            onPressed: onClear,
            icon: Icon(Icons.close, color: c.onAccent),
          ),
        ],
      ),
    );
  }
}

class _TransportChip extends StatelessWidget {
  const _TransportChip({
    required this.mode,
    required this.selected,
    required this.onTap,
  });
  final CheckoutMode mode;
  final bool selected;
  final VoidCallback onTap;

  @override
  Widget build(BuildContext context) {
    final c = AppColors.of(context);
    final textTheme = Theme.of(context).textTheme;
    return GestureDetector(
      onTap: onTap,
      child: Container(
        padding: const EdgeInsets.symmetric(horizontal: 14, vertical: 10),
        decoration: BoxDecoration(
          color: selected ? c.accent : c.surface,
          borderRadius: BorderRadius.circular(10),
          border: Border.all(color: c.border, width: 2.5),
          boxShadow: [
            BoxShadow(
              color: c.shadow,
              offset: selected ? const Offset(3, 3) : const Offset(2, 2),
              blurRadius: 0,
            ),
          ],
        ),
        child: Row(
          mainAxisSize: MainAxisSize.min,
          children: [
            Icon(mode.icon, size: 20, color: selected ? c.onAccent : c.ink),
            const SizedBox(width: 8),
            Text(mode.label,
                style: textTheme.titleSmall
                    ?.copyWith(color: selected ? c.onAccent : c.ink)),
          ],
        ),
      ),
    );
  }
}

/// One half of the Order-now / Pick-a-time choice (migration 031).
///
/// Shares [_TransportChip]'s visual language deliberately — same border weight,
/// same accent fill, same hard shadow — because it is the same kind of decision
/// one section further down the page. What differs is the layout: these two
/// stretch to fill the row rather than wrapping to their content, so the choice
/// reads as a pair of alternatives rather than as the start of another list of
/// chips the customer should scan for more options.
class _ScheduleChoice extends StatelessWidget {
  const _ScheduleChoice({
    super.key,
    required this.label,
    required this.icon,
    required this.selected,
    required this.onTap,
  });

  final String label;
  final IconData icon;
  final bool selected;
  final VoidCallback onTap;

  @override
  Widget build(BuildContext context) {
    final c = AppColors.of(context);
    final textTheme = Theme.of(context).textTheme;
    return GestureDetector(
      onTap: onTap,
      child: Container(
        padding: const EdgeInsets.symmetric(horizontal: 14, vertical: 12),
        decoration: BoxDecoration(
          color: selected ? c.accent : c.surface,
          borderRadius: BorderRadius.circular(10),
          border: Border.all(color: c.border, width: 2.5),
          boxShadow: [
            BoxShadow(
              color: c.shadow,
              offset: selected ? const Offset(3, 3) : const Offset(2, 2),
              blurRadius: 0,
            ),
          ],
        ),
        child: Row(
          mainAxisAlignment: MainAxisAlignment.center,
          children: [
            Icon(icon, size: 20, color: selected ? c.onAccent : c.ink),
            const SizedBox(width: 8),
            Flexible(
              child: Text(
                label,
                overflow: TextOverflow.ellipsis,
                style: textTheme.titleSmall
                    ?.copyWith(color: selected ? c.onAccent : c.ink),
              ),
            ),
          ],
        ),
      ),
    );
  }
}

/// A one-line, non-interactive statement of the origin the app holds.
///
/// Replaces the old `_OriginCard` + `_OriginAction` pair, which were a separate
/// heading, a card and two buttons for a question the transport chip already
/// asks. That card is gone: location resolves only through the chip tap, and
/// re-tapping the selected chip retries.
///
/// This is a STATUS, not a control, and it is deliberately quiet. The origin is
/// optional — FR-C6 says a refusal must still leave checkout payable with a
/// wider estimate — and the prominent card implied it was required. It renders
/// no button at all, so there is nothing here to press and nothing to be
/// confused about pressing.
class _OriginStatus extends StatelessWidget {
  const _OriginStatus({
    super.key,
    required this.originLabel,
    required this.locating,
  });

  final String? originLabel;
  final bool locating;

  @override
  Widget build(BuildContext context) {
    final c = AppColors.of(context);
    final textTheme = Theme.of(context).textTheme;
    final hasOrigin = originLabel != null;

    // Three honest states, and the third is why the retry hint exists: with no
    // separate button, someone whose location failed needs telling how to try
    // again, or the flow is a dead end.
    final (IconData icon, String line) = locating
        ? (Icons.my_location, 'Finding your location…')
        : hasOrigin
            ? (Icons.my_location, originLabel!)
            : (Icons.location_searching,
                'No location yet — tap your travel mode again to retry. '
                'Optional: we will show an approximate wait without it.');

    return Row(
      crossAxisAlignment: CrossAxisAlignment.start,
      children: [
        if (locating)
          const SizedBox(
              width: 16, height: 16,
              child: CircularProgressIndicator(strokeWidth: 2))
        else
          Icon(icon, size: 18, color: hasOrigin ? c.ink : c.inkSoft),
        const SizedBox(width: 10),
        Expanded(
          child: Text(
            line,
            style: textTheme.bodySmall
                ?.copyWith(color: hasOrigin ? c.ink : c.inkSoft),
          ),
        ),
      ],
    );
  }
}

/// The price breakdown: original struck through, the saving, then what is
/// actually charged.
///
/// Collapses to the single "Amount payable" row it has always been when there
/// is no discount — a struck-through price identical to the final one is noise.
/// The order summary, printed as a ticket (prototype §2, screen 08).
///
/// Checkout is the first place the ticket visual appears — deliberately. The
/// same object the customer will hold at the counter is what they approve here,
/// so the pickup ticket that follows payment is recognisably the thing they
/// just confirmed rather than a new screen they have never seen.
///
/// The struck-through original total and the offer line have no equivalent in
/// the prototype; they are existing behaviour and are kept, set in ticket ink
/// rather than the app's purple, which fails contrast on the cream stock.
class _TotalRow extends StatelessWidget {
  const _TotalRow({
    super.key,
    required this.items,
    required this.subtotal,
    required this.discount,
    required this.payable,
    this.offerLabel,
  });

  final List<CartItem> items;
  final double subtotal;
  final double discount;
  final double payable;
  final String? offerLabel;

  @override
  Widget build(BuildContext context) {
    final textTheme = Theme.of(context).textTheme;
    final t = TicketColors.of(context);
    final hasDiscount = discount > 0;

    return TicketCard(
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.stretch,
        children: [
          Text(
            'ORDER SUMMARY',
            textAlign: TextAlign.center,
            style: textTheme.labelLarge?.copyWith(
              color: t.ink,
              letterSpacing: 2.6,
              fontWeight: FontWeight.w700,
            ),
          ),
          const TicketDivider(verticalPadding: 12),
          for (final line in items)
            Padding(
              padding: const EdgeInsets.only(bottom: 10),
              child: Row(
                crossAxisAlignment: CrossAxisAlignment.start,
                children: [
                  Expanded(
                    child: Text(
                      '${line.quantity}× ${line.item.name}',
                      style: textTheme.bodyLarge?.copyWith(color: t.ink),
                    ),
                  ),
                  const SizedBox(width: 12),
                  Text(
                    formatRupees(line.lineTotal),
                    style: textTheme.bodyLarge?.copyWith(
                      color: t.ink,
                      fontWeight: FontWeight.w700,
                    ),
                  ),
                ],
              ),
            ),
          const TicketDivider(verticalPadding: 4),
          const SizedBox(height: 8),
          if (hasDiscount) ...[
            TicketRow(label: 'SUBTOTAL', value: formatRupees(subtotal)),
            const SizedBox(height: 8),
            TicketRow(
              label: offerLabel == null
                  ? 'OFFER'
                  : 'OFFER · ${offerLabel!.toUpperCase()}',
              value: '− ${formatRupees(discount)}',
            ),
            const SizedBox(height: 8),
          ] else ...[
            TicketRow(label: 'SUBTOTAL', value: formatRupees(subtotal)),
            const SizedBox(height: 8),
          ],
          TicketRow(label: 'TAXES & FEES', value: formatRupees(0)),
          const SizedBox(height: 12),
          Container(height: 2, color: t.ink),
          const SizedBox(height: 12),
          TicketRow(
            label: 'TOTAL',
            value: formatRupees(payable),
            emphasize: true,
          ),
        ],
      ),
    );
  }
}
