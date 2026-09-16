import 'package:flutter/foundation.dart';

/// Tagged, UNCONDITIONAL logging for the session-refresh path.
///
/// ## Why this is not kDebugMode-gated
///
/// Every log line on this path used to be wrapped in `if (kDebugMode)`, and
/// five of its exits logged nothing at all in any build. That is the same shape
/// as the FCM registration bug: the failure only ever happened on a real
/// device, the release build printed nothing, and the cause stayed theoretical
/// for weeks because there was no evidence to read.
///
/// `debugPrint` is NOT compiled out of a release build — it forwards to
/// `print`, which reaches logcat. Only the `kDebugMode` wrapper was silencing
/// it. So removing that wrapper is the whole fix, and these lines are
/// deliberately left in for release builds: a session bug that only reproduces
/// on someone else's phone is exactly the one worth paying a few log lines for.
///
/// Volume is bounded by events, not by polling — a refresh happens at most once
/// per 401 burst (they are coalesced, see ApiClient._refreshSession), and the
/// Firebase-restore line fires at most once per process.
const String _tag = '[session]';

/// Time since app start, so a log line says WHEN in the launch sequence it
/// happened rather than just what happened.
///
/// The leading hypothesis for the forced re-logins is a race — a 401 refresh
/// firing before Firebase has finished restoring `currentUser` from disk. That
/// is only distinguishable from an ordinary failure by the ORDER and SPACING of
/// two events, so every line carries an elapsed stamp.
final Stopwatch _sinceStart = Stopwatch();

/// Called once from `main()` before anything else can log.
void markAppStart() {
  _sinceStart
    ..reset()
    ..start();
}

String get _stamp =>
    _sinceStart.isRunning ? '+${_sinceStart.elapsedMilliseconds}ms' : '+?ms';

void sessionLog(String message) => debugPrint('$_tag $_stamp $message');

/// Latch so the Firebase-restore line is logged once, on the FIRST transition
/// to a non-null user, rather than on every auth-state emission.
bool _firebaseUserLogged = false;

/// The moment Firebase finished restoring a persisted user, relative to app
/// start. Half of the evidence for the race hypothesis.
///
/// [uid] is deliberately truncated: it identifies the session in a log without
/// writing a full account identifier to a device log that may be shared.
void logFirebaseUserRestored(String? uid, {required List<String> providers}) {
  if (_firebaseUserLogged) return;
  _firebaseUserLogged = true;
  final short = (uid == null || uid.isEmpty)
      ? 'none'
      : '${uid.substring(0, uid.length.clamp(0, 6))}…';
  sessionLog('firebase user restored (uid=$short providers=$providers)');
}

/// Firebase reported auth state but with NO user. Logged once, because "no user
/// yet" and "no user ever" look identical at a single point in time and only
/// the elapsed stamp tells them apart.
void logFirebaseNoUser() {
  if (_firebaseUserLogged) return;
  sessionLog('firebase auth state resolved with NO user');
}

/// Reset for tests. The latch is process-global, which is right for an app and
/// wrong for a suite where several tests exercise the same path.
@visibleForTesting
void resetSessionLogForTest() {
  _firebaseUserLogged = false;
  _sinceStart
    ..reset()
    ..start();
}
