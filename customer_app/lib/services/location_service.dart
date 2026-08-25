import 'dart:async';

import 'package:flutter/foundation.dart';
import 'package:geolocator/geolocator.dart';

/// Outcome of a location request.
///
/// [denied] and [deniedForever] are deliberately SEPARATE. They need different
/// UI: a plain denial can be re-asked on the next attempt, a permanent one can
/// only be undone in system settings, and offering "try again" for the latter
/// is a button that is guaranteed to do nothing.
enum LocationOutcome { granted, denied, deniedForever, serviceDisabled, error }

class LocationResult {
  const LocationResult(this.outcome, {this.latitude, this.longitude});
  final LocationOutcome outcome;
  final double? latitude;
  final double? longitude;

  bool get hasCoordinates => latitude != null && longitude != null;

  /// True when the customer said no in some form — as opposed to the hardware
  /// being off or the lookup failing.
  bool get isRefusal =>
      outcome == LocationOutcome.denied ||
      outcome == LocationOutcome.deniedForever;
}

/// Wraps geolocator so screens don't touch the plugin directly.
///
/// FOREGROUND ONLY. Everything here maps to ACCESS_FINE/COARSE_LOCATION —
/// "while using the app". Background ("allow all the time") location is
/// deliberately not requested: no feature reads location while the app is
/// backgrounded (the en-route pings in PickupScreen run off a Timer that only
/// ticks while the screen is alive), so asking for it would be a scary prompt
/// bought for nothing.
///
/// Registered once in main.dart, so the prompt bookkeeping below is app-wide —
/// which is also why a denial on one screen used to silence the prompt on a
/// different one. Incidental callers still ask at most once per grant state;
/// callers passing `userInitiated: true` ask every time. The STATUS itself is
/// always re-read from the OS on every call, never served from cache.
///
/// A [ChangeNotifier] because [refreshPermission] can change the answer without
/// any screen having asked — the app-resume re-check does exactly that — and a
/// screen showing "location is off" has to stop showing it once it isn't.
class LocationService extends ChangeNotifier {
  /// Last status read from the OS.
  LocationPermission? _permission;
  LocationPermission? get permission => _permission;

  /// Whether the OS dialog has already been raised for the CURRENT grant state.
  ///
  /// Without this, a denial on one screen made every later screen ask again —
  /// the duplicate prompt. (Android also auto-denies repeat asks, so re-asking
  /// mostly just produced a silent no.)
  ///
  /// It is a latch on the grant state, NOT on the session: [_syncPermission]
  /// releases it whenever the OS answer changes underneath us. That is what
  /// makes "Ask every time" work — see the comment there.
  bool _prompted = false;

  /// De-dups overlapping calls — e.g. the 60s en-route timer firing while the
  /// departure request is still waiting on a GPS fix. Two concurrent
  /// `requestPermission` calls throw on Android, and two dialogs is exactly the
  /// bug this class is fixing.
  Future<LocationResult>? _inFlight;

  static bool _isGranted(LocationPermission p) =>
      p == LocationPermission.whileInUse || p == LocationPermission.always;

  /// True when location can be read without showing the user anything.
  bool get hasPermission => _isGranted(_permission ?? LocationPermission.denied);

  /// True when only a trip to system settings can change the answer, so the UI
  /// offers that instead of a retry that the OS will silently swallow.
  bool get isBlocked => _permission == LocationPermission.deniedForever;

  /// Records a freshly-read OS status and decides whether the one-prompt latch
  /// should be released.
  ///
  /// The latch is released on ANY change of grant state, which covers the three
  /// ways the OS answer moves without the app doing anything:
  ///
  ///  * **"Ask every time"** (Android's ONE_TIME grant) reads back as
  ///    `whileInUse` while the app is in the foreground, then reverts to
  ///    `denied` once the grant lapses. A latch that survived that revert is
  ///    precisely why the next order attempt never re-prompted — it saw
  ///    `denied`, believed it had already asked, and returned a silent no.
  ///  * **A grant or revoke made in system settings**, which the app now
  ///    notices on resume rather than at next launch.
  ///  * **A denial being upgraded to permanent** by the OS after repeat asks.
  ///
  /// Returns true when the status actually moved, so callers can decide whether
  /// listeners need waking.
  bool _syncPermission(LocationPermission next) {
    final previous = _permission;
    _permission = next;
    if (previous == next) return false;
    // Any transition invalidates "we already asked under these conditions".
    // deniedForever is the one state worth keeping latched: the OS suppresses
    // that dialog entirely, so releasing the latch would only buy a no-op await.
    _prompted = next == LocationPermission.deniedForever;
    return true;
  }

  /// Re-read the OS permission WITHOUT ever showing a dialog.
  ///
  /// Called on app resume (see [CareVoApp]) so a permission changed in system
  /// settings takes effect immediately, instead of the app carrying a stale
  /// answer until the next cold start — which was the reported bug.
  ///
  /// Safe to call often: it is a cheap platform-channel read and notifies only
  /// when the answer actually changed.
  Future<void> refreshPermission() async {
    try {
      if (_syncPermission(await Geolocator.checkPermission())) {
        notifyListeners();
      }
    } catch (_) {
      // A failed read must never be treated as a revocation — leave the last
      // known status in place.
    }
  }

  /// Requests permission and returns the position. On any denial/failure the
  /// caller falls back to manual city/area select.
  ///
  /// Three callers, three policies:
  ///
  ///  * [allowPrompt] `false` — automatic/background-ish callers (polling
  ///    timers, prefetches). They can use an existing grant but can never be
  ///    the thing that raises a dialog the user didn't ask for.
  ///  * [userInitiated] `true` — the customer just tapped a control whose
  ///    whole meaning is location ("Near me", the Nearest sort). These ask
  ///    EVERY time, because the tap IS the request. See below.
  ///  * neither — incidental callers, which ask once per grant state.
  ///
  /// ## Why [userInitiated] has to bypass the latch
  ///
  /// [_prompted] is cleared only by [_syncPermission], and that returns early
  /// when the status has not moved. So after one denial the status stays
  /// `denied`, the latch stays set, and every later tap fell through to a
  /// silent refusal — the dialog was suppressed by US, not by the OS.
  ///
  /// That is wrong for a deliberate tap. Android re-shows the system dialog on
  /// a plain `denied` (it only stops once the denial becomes permanent, which
  /// geolocator reports as `deniedForever` and which is still never re-asked
  /// below). Suppressing it meant tapping "Near me" a second time did visibly
  /// nothing at all.
  ///
  /// The latch still protects the incidental callers it was added for, and
  /// [_inFlight] still collapses genuinely concurrent calls, so bypassing it
  /// here cannot produce two stacked dialogs.
  Future<LocationResult> getCurrentLocation({
    bool allowPrompt = true,
    bool userInitiated = false,
  }) {
    final pending = _inFlight;
    if (pending != null) return pending;

    late final Future<LocationResult> call;
    call = _resolve(allowPrompt: allowPrompt, userInitiated: userInitiated)
        .whenComplete(() {
      if (identical(_inFlight, call)) _inFlight = null;
    });
    _inFlight = call;
    return call;
  }

  Future<LocationResult> _resolve({
    required bool allowPrompt,
    required bool userInitiated,
  }) async {
    var changed = false;
    try {
      final serviceEnabled = await Geolocator.isLocationServiceEnabled();
      if (!serviceEnabled) {
        return const LocationResult(LocationOutcome.serviceDisabled);
      }

      // Always re-read first. The cached value can be stale by an arbitrary
      // amount — the customer may have just come back from system settings.
      changed = _syncPermission(await Geolocator.checkPermission());
      var permission = _permission!;

      // `deniedForever` is never re-asked, whoever is asking and however
      // deliberately: the OS suppresses that dialog entirely, so calling
      // requestPermission would be a no-op wait that returns the same refusal.
      // Those callers get [openSettings] instead.
      //
      // A plain `denied` IS re-askable, and a user-initiated tap always takes
      // that path — the latch only gates incidental callers.
      if (permission == LocationPermission.denied &&
          allowPrompt &&
          (userInitiated || !_prompted)) {
        _prompted = true;
        // Foreground grant only; we never follow up with a background upgrade.
        permission = await Geolocator.requestPermission();
        // Record the ANSWER without releasing the latch we just set: the user
        // has now been asked, and asking twice in a row is the duplicate-prompt
        // bug. Assigned directly rather than through _syncPermission for that
        // reason.
        if (_permission != permission) {
          _permission = permission;
          changed = true;
        }
      }

      if (!_isGranted(permission)) {
        // A refusal the customer can still reverse in-app, versus one that
        // needs system settings. The caller words its message from this.
        return LocationResult(
          permission == LocationPermission.deniedForever
              ? LocationOutcome.deniedForever
              : LocationOutcome.denied,
        );
      }

      final position = await Geolocator.getCurrentPosition(
        locationSettings: const LocationSettings(accuracy: LocationAccuracy.medium),
      );
      return LocationResult(
        LocationOutcome.granted,
        latitude: position.latitude,
        longitude: position.longitude,
      );
    } catch (_) {
      return const LocationResult(LocationOutcome.error);
    } finally {
      if (changed) notifyListeners();
    }
  }

  /// Opens the OS settings page for this app, so a [isBlocked] refusal has a
  /// way out that does not involve reinstalling.
  Future<bool> openSettings() async {
    try {
      return await Geolocator.openAppSettings();
    } catch (_) {
      return false;
    }
  }
}
