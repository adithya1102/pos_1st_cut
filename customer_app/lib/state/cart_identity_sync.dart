import 'package:flutter/foundation.dart';

import 'auth_state.dart';
import 'cart_state.dart';

/// Keeps [CartState]'s storage scope pointed at whoever is signed in.
///
/// ## One listener, not one fix per call site
///
/// The cart used to be a single global blob that outlived every sign-out, so a
/// new customer signing in on the same device inherited the previous one's
/// basket. The obvious repair — "clear the cart in `logout()`" — is the wrong
/// shape: it fixes the paths that go through logout and silently misses the
/// ones that do not. The diagnostic found two such paths, and neither is
/// exotic:
///
///  * **a second Google sign-in over a live session** (`AuthState.signInWithGoogle`)
///    replaces the customer without logging anybody out, and
///  * **session loss** (`AuthState._onSessionLost`, driven by any 401) drops the
///    customer from a background request with no screen involved at all.
///
/// Every one of those paths does do the same ONE thing, though: it assigns
/// `AuthState._customer` and notifies. So this binds there instead — a single
/// subscription that re-scopes the cart whenever the answer to "who is this?"
/// changes, by whatever route it changed. New auth flows are covered on the day
/// they are written, without anyone remembering to add a line to them.
///
/// ## `null` customer is not the same as "guest"
///
/// On a cold start with a restored token the customer is null until
/// `/customer/me` comes back — the session exists, its identity is merely not
/// resolved yet. Treating that as a sign-out would re-scope the cart to guest
/// and blank a basket that is about to be restored, so an authenticated session
/// with an unresolved profile is left alone until it resolves. A null customer
/// counts as guest only when there is genuinely no session.
class CartIdentitySync {
  CartIdentitySync(this._auth, this._cart);

  final AuthState _auth;
  final CartState _cart;
  bool _started = false;

  /// Subscribe, and adopt the identity the session already has.
  void start() {
    if (_started) return;
    _started = true;
    _auth.addListener(_onIdentityChanged);
    _onIdentityChanged();
  }

  void dispose() {
    if (!_started) return;
    _auth.removeListener(_onIdentityChanged);
    _started = false;
  }

  /// Re-scope once, for the identity as it stands right now.
  Future<void> syncNow() {
    final id = _auth.customer?.id;
    if (id == null && _auth.isAuthenticated) {
      // Authenticated but unresolved — see the class docs. Keep the scope the
      // last session left behind rather than falling back to guest.
      return Future<void>.value();
    }
    return _cart.setIdentity(id);
  }

  Future<void> _pending = Future<void>.value();

  /// Completes once every re-scope queued so far has finished.
  ///
  /// Production never awaits this — an identity change must not block the UI
  /// thread on a disk read — but a test that has just driven a sign-in needs a
  /// deterministic point to assert from, and the alternative (sleeping on the
  /// event queue) both hangs under the test binding and proves nothing.
  Future<void> get settled => _pending;

  /// Queued, not fired in parallel.
  ///
  /// One auth call notifies SEVERAL times — `AuthState` toggles `busy` on the
  /// way in and out around assigning the customer — so overlapping re-scopes
  /// are the normal case, not an edge one. Two concurrent [CartState.setIdentity]
  /// calls can both pass its "already on this scope" guard (it awaits a flush
  /// before assigning), leaving two disk reads racing to populate one cart.
  /// Serialising removes that outright.
  void _onIdentityChanged() {
    _pending = _pending.then((_) => syncNow()).catchError(
      (Object e) {
        // Best-effort, exactly like cart persistence itself: a failed re-scope
        // must not take down the app, and must not poison the queue for the
        // next identity change.
        debugPrint('CartIdentitySync: re-scope failed: $e');
      },
    );
  }
}
