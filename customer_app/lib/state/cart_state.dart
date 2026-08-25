import 'dart:convert';

import 'package:flutter/foundation.dart';
import 'package:shared_preferences/shared_preferences.dart';

import '../models/cart_item.dart';
import '../models/menu.dart';
import '../models/outlet.dart';

/// Client-side cart, persisted to device storage.
///
/// The cart is tied to a single outlet. Persistence uses `shared_preferences`
/// (already a dependency for the auth token and theme) rather than adding hive:
/// a cart is one small JSON blob, so a full embedded database would buy nothing
/// here.
///
/// Every mutation writes through to disk, so the cart survives backgrounding,
/// a force-close, and process death — not just navigation.
///
/// ## Why disk reads are lifecycle-driven, not screen-driven
///
/// The cart used to be read from disk EXACTLY ONCE, in `main()`, and never
/// again. Nothing re-read it and nothing flushed it on the way out, which is
/// the whole of the "cart looks empty until you visit another screen" family of
/// bugs — the fix is at this level, not in the screens that displayed the
/// result:
///
///  * **Writes could be lost outright.** Mutators called `_persist()` without
///    awaiting it, and nothing ever awaited it either. Add an item and
///    force-close within the same tick and the write never reached disk, so the
///    next cold start restored a cart that genuinely did not have it. See
///    [flush], which the app shell now calls when the app leaves the foreground.
///  * **Nothing re-read after startup.** [syncFromDisk] is called on app
///    resume, so in-memory state cannot drift from what is on disk.
///
/// Screens are unchanged: they watch this object and rebuild. Making one screen
/// re-read on mount would have hidden the symptom on that screen only, and left
/// every other one wrong.
///
/// ## Why the storage key carries an identity
///
/// It used to be ONE global key, `carevo_cart_v1`, shared by every account that
/// ever signed in on the device. Logout cleared the session token and nothing
/// else, so the next customer to sign in — a brand-new account included —
/// inherited the previous one's basket, the outlet it was bound to, and the
/// "Continue where you left off" banner naming that restaurant.
///
/// The key is now scoped to the customer's id (see [setIdentity]), so two
/// accounts on one device address two different blobs and neither can see the
/// other's. Scoping the STORE rather than clearing at each logout call site is
/// deliberate: a clear-on-logout fix has to be repeated at every path that
/// changes who is signed in, and the diagnostic found paths that do not go
/// through logout at all (a Google sign-in over a live session, and the 401
/// session-loss redirect). A key that depends on the identity cannot be reached
/// by the wrong identity, whatever route the app took to get there.
class CartState extends ChangeNotifier {
  /// The pre-scoping key. Global, therefore unattributable: nothing recorded
  /// who wrote it. Read once at [restore] only to DELETE it — see there.
  static const legacyGlobalKey = 'carevo_cart_v1';

  /// Scope used while nobody is signed in. A real, separate namespace rather
  /// than "the old global key" or "whichever account was last here", so a
  /// logged-out basket cannot be mistaken for anyone's.
  static const guestScope = 'guest';

  /// Which scope the persisted cart belongs to, so a cold start can restore the
  /// right basket before the first frame instead of waiting for `/customer/me`.
  static const scopePrefsKey = 'carevo_cart_scope';

  /// One blob per identity. `guest` is a scope like any other.
  static String storageKeyFor(String scope) => 'carevo_cart_v1_$scope';

  String _scope = guestScope;

  /// The identity this cart currently reads and writes. Exposed for tests and
  /// for the assertion that a switch actually moved it.
  String get scope => _scope;

  String get _storageKey => storageKeyFor(_scope);

  final List<CartItem> _items = [];
  List<CartItem> get items => List.unmodifiable(_items);

  Outlet? _outlet;
  Outlet? get outlet => _outlet;
  String? get outletId => _outlet?.id;

  int _lineCounter = 0;

  /// False until [restore] finishes, so UI can avoid flashing an empty cart
  /// over one that is about to load.
  bool _restored = false;
  bool get restored => _restored;

  int get totalQuantity => _items.fold(0, (sum, i) => sum + i.quantity);
  double get subtotal => _items.fold(0.0, (sum, i) => sum + i.lineTotal);
  bool get isEmpty => _items.isEmpty;

  // ----------------------------- persistence -------------------------------

  /// Load any persisted cart. Called once at startup, before the first frame.
  ///
  /// Adopts the scope the last session left behind, so a relaunch restores the
  /// signed-in customer's basket immediately rather than showing an empty one
  /// until `/customer/me` resolves.
  ///
  /// Also deletes any [legacyGlobalKey] blob left by a pre-scoping build. It is
  /// NOT migrated into a scope: nothing in it records who wrote it, and
  /// adopting an unattributable basket into whichever account happens to open
  /// the app next is precisely the bug this scoping removes. The cost is that a
  /// customer upgrading mid-basket loses those items once; the alternative is
  /// handing them to the wrong person.
  Future<void> restore() async {
    final prefs = await SharedPreferences.getInstance();
    await prefs.reload();
    _scope = prefs.getString(scopePrefsKey) ?? guestScope;
    if (prefs.containsKey(legacyGlobalKey)) {
      await prefs.remove(legacyGlobalKey);
    }
    await _readFromDisk();
  }

  /// Point the cart at [customerId]'s basket, or at [guestScope] when null.
  ///
  /// Called on EVERY identity change — sign-in, logout, a second sign-in over a
  /// live session, account deletion, and session loss — by [CartIdentitySync].
  /// Whatever was in memory for the previous identity is dropped here, so the
  /// switch does not depend on any screen rebuilding or on the app being
  /// restarted.
  ///
  /// A no-op when the identity has not actually changed. That matters on cold
  /// start: `/customer/me` resolving to the same customer must not re-read the
  /// cart and blink the basket.
  Future<void> setIdentity(String? customerId) async {
    final next = (customerId == null || customerId.trim().isEmpty)
        ? guestScope
        : customerId.trim();
    if (next == _scope) return;

    // Land every queued write under the scope that PRODUCED it. Without this a
    // mutation made moments before signing out could still be in flight and
    // would arrive after the switch — writing the old customer's items into the
    // new customer's key, which is the leak again by a slower route.
    await flush();

    final previous = _scope;
    _scope = next;

    final prefs = await SharedPreferences.getInstance();
    await prefs.setString(scopePrefsKey, next);

    // Guest basket is DISCARDED at sign-in, never merged into the account.
    // See the class docs on [guestScope]: a merge is the same identity-boundary
    // crossing this fix exists to stop — on a shared device it hands whoever
    // signs in next the previous person's items.
    if (previous == guestScope && next != guestScope) {
      await prefs.remove(storageKeyFor(guestScope));
    }

    await _readFromDisk();
  }

  /// Re-read the persisted cart, adopting whatever is on disk.
  ///
  /// Called on app resume. Any queued write is flushed FIRST, so this can only
  /// ever adopt a blob that already includes this session's mutations — without
  /// that ordering a resume could race an in-flight write and reinstate the
  /// pre-mutation cart, which would be a far worse bug than the one it fixes.
  Future<void> syncFromDisk() async {
    await flush();
    await _readFromDisk();
  }

  Future<void> _readFromDisk() async {
    try {
      final prefs = await SharedPreferences.getInstance();
      // reload() so a resume sees writes made after the in-memory cache was
      // populated. SharedPreferences caches on first access, so without this
      // the "re-read" would just hand back the same startup snapshot.
      await prefs.reload();
      final raw = prefs.getString(_storageKey);
      if (raw != null && raw.isNotEmpty) {
        final map = jsonDecode(raw) as Map<String, dynamic>;
        final outletJson = (map['outlet'] as Map?)?.cast<String, dynamic>();
        _outlet = outletJson == null ? null : Outlet.fromJson(outletJson);
        _items
          ..clear()
          ..addAll(((map['items'] as List?) ?? const [])
              .whereType<Map>()
              .map((i) => CartItem.fromJson(i.cast<String, dynamic>())));
        _lineCounter = int.tryParse(map['line_counter']?.toString() ?? '') ?? _items.length;
      } else {
        // An absent blob means an empty cart, and must be adopted as such —
        // otherwise a cart cleared in another entry point would come back.
        _items.clear();
        _outlet = null;
        _lineCounter = 0;
      }
    } catch (_) {
      // A corrupt or schema-changed blob must never brick startup: drop it and
      // begin with an empty cart.
      _items.clear();
      _outlet = null;
      _lineCounter = 0;
    }
    _restored = true;
    notifyListeners();
  }

  /// Serialises writes so two mutations in the same frame cannot land on disk
  /// out of order, and so [flush] has something to await.
  Future<void> _writes = Future<void>.value();

  /// Completes once every write queued so far has reached disk.
  ///
  /// The app shell awaits this when the app leaves the foreground. Mutators
  /// still do NOT await — a slow disk must never make tapping "add" feel
  /// laggy — but the last write before a force-close is no longer a race.
  Future<void> flush() => _writes;

  /// Queue a write. The payload is encoded SYNCHRONOUSLY, at mutation time, so
  /// the queued job persists the state that actually triggered it rather than
  /// whatever the cart happens to look like when the job reaches the head of
  /// the queue.
  ///
  /// The KEY is captured at the same moment and for the same reason: the scope
  /// can change while a write is queued, and a job that resolved its key late
  /// would file the outgoing customer's basket under the incoming customer's
  /// identity.
  void _persist() {
    final String key = _storageKey;
    final String? payload = (_items.isEmpty && _outlet == null)
        ? null
        : jsonEncode({
            'outlet': _outlet?.toJson(),
            'items': _items.map((i) => i.toJson()).toList(),
            'line_counter': _lineCounter,
          });

    _writes = _writes.then((_) async {
      try {
        final prefs = await SharedPreferences.getInstance();
        if (payload == null) {
          await prefs.remove(key);
        } else {
          await prefs.setString(key, payload);
        }
      } catch (_) {
        // Persistence is best-effort; the in-memory cart stays authoritative
        // for this session even if the write fails. Swallowed rather than
        // rethrown so one failed write cannot poison the queue for every
        // later one.
      }
    });
  }

  // ------------------------------- outlet ----------------------------------

  /// True when [outlet] differs from the cart's outlet AND the cart has items,
  /// i.e. binding to it would discard the customer's basket.
  ///
  /// Callers use this to prompt BEFORE calling [setOutlet]; merely browsing a
  /// different restaurant must not silently empty the cart.
  bool wouldDiscardCart(Outlet outlet) =>
      _items.isNotEmpty && _outlet != null && _outlet!.id != outlet.id;

  /// Bind the cart to [outlet]. Clears the basket only when switching to a
  /// DIFFERENT outlet — check [wouldDiscardCart] first and confirm with the
  /// customer, because this is not reversible.
  void setOutlet(Outlet outlet) {
    if (_outlet?.id != outlet.id) {
      _items.clear();
      _lineCounter = 0;
    }
    _outlet = outlet;
    _persist();
    notifyListeners();
  }

  /// Bind to [outlet] without touching the basket. Safe when the cart is empty
  /// or already belongs to this outlet; used when only browsing.
  void bindOutletIfSafe(Outlet outlet) {
    if (wouldDiscardCart(outlet)) return;
    setOutlet(outlet);
  }

  /// Drop lines whose menu item is no longer available, returning the removed
  /// names. Used by the pre-checkout availability gate (see checkout_screen).
  List<String> removeUnavailable(Set<String> unavailableItemIds) {
    final removed = <String>[];
    _items.removeWhere((line) {
      if (unavailableItemIds.contains(line.item.id)) {
        removed.add(line.item.name);
        return true;
      }
      return false;
    });
    if (removed.isNotEmpty) {
      _persist();
      notifyListeners();
    }
    return removed;
  }

  void addItem(
    MenuItem item, {
    int quantity = 1,
    List<SelectedOption> options = const [],
    String? notes,
  }) {
    final candidate = CartItem(
      lineId: 'l${_lineCounter++}',
      item: item,
      quantity: quantity,
      selectedOptions: List.of(options),
      notes: notes,
    );

    // Merge with an existing identical configuration.
    final existing = _items
        .where((c) => c.signature == candidate.signature)
        .cast<CartItem?>()
        .firstWhere((_) => true, orElse: () => null);

    if (existing != null) {
      existing.quantity += quantity;
    } else {
      _items.add(candidate);
    }
    _persist();
    notifyListeners();
  }

  void increment(String lineId) {
    final line = _find(lineId);
    if (line != null) {
      line.quantity++;
      _persist();
      notifyListeners();
    }
  }

  void decrement(String lineId) {
    final line = _find(lineId);
    if (line == null) return;
    line.quantity--;
    if (line.quantity <= 0) {
      _items.removeWhere((i) => i.lineId == lineId);
    }
    _persist();
    notifyListeners();
  }

  void removeLine(String lineId) {
    _items.removeWhere((i) => i.lineId == lineId);
    _persist();
    notifyListeners();
  }

  void clear() {
    _items.clear();
    _lineCounter = 0;
    _persist();
    notifyListeners();
  }

  CartItem? _find(String lineId) {
    for (final i in _items) {
      if (i.lineId == lineId) return i;
    }
    return null;
  }

  /// Build the `POST /customer/orders` payload.
  ///
  /// PE Step 3 (FR-C1/C2): the checkout may attach a travel [transportMode]
  /// and the customer's [originLat]/[originLng] starting point so the
  /// prediction engine can estimate travel. All are optional — a customer who
  /// denies location still checks out, just with `origin_source: 'none'`.
  /// A [promotionId] is an offer the customer tapped from the list;
  /// [promotionCode] is one they typed in. Both are separate from
  /// [couponCode] — a points coupon and an offer are different instruments and
  /// the server rejects an order carrying both.
  Map<String, dynamic> toOrderPayload({
    String? customerNotes,
    String? transportMode,
    double? originLat,
    double? originLng,
    String? originSource,
    String? couponCode,
    String? promotionId,
    String? promotionCode,
    DateTime? declaredArrivalAt,
  }) =>
      {
        'outlet_id': _outlet?.id,
        'items': _items.map((i) => i.toOrderItemJson()).toList(),
        if (customerNotes != null && customerNotes.trim().isNotEmpty)
          'customer_notes': customerNotes.trim(),
        // Omitted when blank: the server validates a minimum length, so an
        // empty string would be rejected rather than treated as "no coupon".
        if (couponCode != null && couponCode.trim().isNotEmpty)
          'coupon_code': couponCode.trim().toUpperCase(),
        if (promotionId != null && promotionId.isNotEmpty)
          'promotion_id': promotionId,
        if (promotionCode != null && promotionCode.trim().isNotEmpty)
          'promotion_code': promotionCode.trim().toUpperCase(),
        'transport_mode': ?transportMode,
        // Train mode only (addendum Item 1). UTC on the wire: the server does
        // all its timing in UTC, and a local-time string would be read as UTC
        // and silently shift the kitchen notification by the offset.
        if (declaredArrivalAt != null)
          'declared_arrival_at': declaredArrivalAt.toUtc().toIso8601String(),
        'origin_lat': ?originLat,
        'origin_lng': ?originLng,
        'origin_source': ?originSource,
      };
}
