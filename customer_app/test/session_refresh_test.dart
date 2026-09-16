// An expired CareVo token renews itself instead of logging the customer out.
//
// The CareVo JWT lives 24h (ACCESS_TOKEN_EXPIRE_MINUTES=1440) and there is no
// refresh token anywhere in the system, while the Firebase session behind it
// persists indefinitely. The app exchanged that once at sign-in and never
// again, so people were signed out roughly daily for bookkeeping reasons
// rather than because their identity had gone.
//
// These drive ApiClient directly with a stub SessionRefresher. That is the
// whole reason the refresher is a callback rather than a Firebase import: the
// client is testable without a Firebase app, and a NULL refresher reproduces
// the old behaviour exactly — which is what makes the no-regression cases
// below meaningful instead of vacuous.
import 'dart:convert';

import 'package:flutter/foundation.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:http/http.dart' as http;
import 'package:http/testing.dart';
import 'package:shared_preferences/shared_preferences.dart';

import 'package:customer_app/services/api_client.dart';
import 'package:customer_app/services/session_log.dart';

/// Capture everything [sessionLog] emits during [body].
///
/// debugPrint is swapped rather than the logger being made injectable: the
/// whole point of this change is that the call sites print UNCONDITIONALLY in a
/// real build, and a seam that tests could disable is a seam production could
/// disable too. This asserts on the actual output path.
Future<List<String>> captureLogs(Future<void> Function() body) async {
  final lines = <String>[];
  final original = debugPrint;
  debugPrint = (String? message, {int? wrapWidth}) {
    if (message != null) lines.add(message);
  };
  resetSessionLogForTest();
  try {
    await body();
  } finally {
    debugPrint = original;
  }
  return lines;
}

http.Response _json(Object body, {int status = 200}) =>
    http.Response(jsonEncode(body), status,
        headers: {'content-type': 'application/json'});

/// A backend that 401s until it sees [goodToken], then succeeds.
///
/// Asserting on the Authorization header is the point: it proves the replay
/// carried the NEW token, not merely that a second request happened.
class _Backend {
  _Backend({this.goodToken = 'fresh-token'});
  final String goodToken;

  final List<String> paths = [];
  final List<String?> auths = [];

  http.Client client() => MockClient((req) async {
        paths.add(req.url.path);
        final auth = req.headers['Authorization'];
        auths.add(auth);

        // The exchange endpoints are unauthenticated and always answer.
        if (req.url.path.contains('/auth/')) {
          return _json({'access_token': goodToken, 'token_type': 'bearer'});
        }
        if (auth == 'Bearer $goodToken') {
          return _json({'ok': true});
        }
        return _json({'detail': 'Invalid or missing customer token'},
            status: 401);
      });

  int get protectedCalls => paths.where((p) => !p.contains('/auth/')).length;
}

Future<ApiClient> _signedIn(_Backend backend, {String token = 'stale'}) async {
  SharedPreferences.setMockInitialValues({});
  final api = ApiClient(client: backend.client());
  await api.setToken(token);
  return api;
}

void main() {
  TestWidgetsFlutterBinding.ensureInitialized();

  group('a 401 with a live identity refreshes instead of logging out', () {
    test('the original request succeeds on the replay', () async {
      final backend = _Backend();
      final api = await _signedIn(backend);
      var refreshes = 0;
      api.sessionRefresher = () async {
        refreshes++;
        return 'fresh-token';
      };

      final res = await api.get('/customer/orders');

      expect(res, {'ok': true});
      expect(refreshes, 1);
      expect(api.token, 'fresh-token', reason: 'the new token must be stored');
      expect(api.isAuthenticated, isTrue, reason: 'no logout should happen');
      expect(backend.protectedCalls, 2, reason: 'original + one replay');
    });

    test('the replay carries the NEW token, not the stale one', () async {
      // Without this the test would pass on an implementation that retried
      // with the same header and happened to be given a lenient backend.
      final backend = _Backend();
      final api = await _signedIn(backend);
      api.sessionRefresher = () async => 'fresh-token';

      await api.get('/customer/orders');

      final protectedAuths = [
        for (var i = 0; i < backend.paths.length; i++)
          if (!backend.paths[i].contains('/auth/')) backend.auths[i]
      ];
      expect(protectedAuths.first, 'Bearer stale');
      expect(protectedAuths.last, 'Bearer fresh-token');
    });

    test('no AuthExpiredException reaches the caller', () async {
      final backend = _Backend();
      final api = await _signedIn(backend);
      api.sessionRefresher = () async => 'fresh-token';

      // authFailures drives the app's route-to-login; it must not move.
      final before = api.authFailures.value;
      await api.get('/customer/orders');
      expect(api.authFailures.value, before);
    });

    test('POST is replayed too, not only GET', () async {
      // Safe because a 401 comes from get_current_customer, a dependency that
      // only decodes the JWT and SELECTs — it raises before the handler body,
      // so nothing was processed and there is nothing to double-apply.
      final backend = _Backend();
      final api = await _signedIn(backend);
      api.sessionRefresher = () async => 'fresh-token';

      final res = await api.post('/customer/orders', body: {'x': 1});

      expect(res, {'ok': true});
      expect(backend.protectedCalls, 2);
    });
  });

  group('a genuinely dead identity still logs out, exactly as before', () {
    test('no refresher wired — unchanged behaviour', () async {
      final backend = _Backend();
      final api = await _signedIn(backend);
      // sessionRefresher deliberately left null: the pre-existing path.

      await expectLater(
        api.get('/customer/orders'),
        throwsA(isA<AuthExpiredException>()),
      );
      expect(api.isAuthenticated, isFalse, reason: 'token must be cleared');
      expect(api.authFailures.value, 1);
      expect(backend.protectedCalls, 1, reason: 'nothing should be replayed');
    });

    test('refresher returns null (Firebase session gone)', () async {
      final backend = _Backend();
      final api = await _signedIn(backend);
      api.sessionRefresher = () async => null;

      await expectLater(
        api.get('/customer/orders'),
        throwsA(isA<AuthExpiredException>()),
      );
      expect(api.isAuthenticated, isFalse);
      expect(api.authFailures.value, 1);
    });

    test('refresher throws — treated as a failed refresh, not a crash',
        () async {
      final backend = _Backend();
      final api = await _signedIn(backend);
      api.sessionRefresher = () async => throw StateError('firebase exploded');

      await expectLater(
        api.get('/customer/orders'),
        throwsA(isA<AuthExpiredException>()),
        reason: 'the customer must see an expiry, never a Firebase error',
      );
      expect(api.isAuthenticated, isFalse);
    });

    test('a refreshed token that is STILL rejected logs out', () async {
      // The replay gets one attempt. If that 401s too, the session really is
      // dead and looping would just hammer the exchange endpoint.
      final backend = _Backend(goodToken: 'never-issued');
      final api = await _signedIn(backend);
      var refreshes = 0;
      api.sessionRefresher = () async {
        refreshes++;
        return 'still-wrong';
      };

      await expectLater(
        api.get('/customer/orders'),
        throwsA(isA<AuthExpiredException>()),
      );
      expect(refreshes, 1, reason: 'exactly one refresh, no loop');
      expect(backend.protectedCalls, 2, reason: 'original + one replay, then stop');
      expect(api.isAuthenticated, isFalse);
    });
  });

  group('concurrent 401s share one refresh', () {
    test('five parallel requests trigger exactly one exchange',
        () async {
      // Home fires several requests at once and they expire together, since
      // they carry the same token. Each minting its own token would be a burst
      // of identical logins with the last write deciding the winner.
      final backend = _Backend();
      final api = await _signedIn(backend);
      var refreshes = 0;
      api.sessionRefresher = () async {
        refreshes++;
        await Future<void>.delayed(const Duration(milliseconds: 30));
        return 'fresh-token';
      };

      final results = await Future.wait([
        api.get('/customer/orders'),
        api.get('/customer/outlets'),
        api.get('/customer/me'),
        api.get('/customer/points'),
        api.get('/customer/coupons'),
      ]);

      expect(refreshes, 1, reason: 'one refresh shared by all five');
      for (final r in results) {
        expect(r, {'ok': true}, reason: 'every request must still succeed');
      }
    });

    test('a later 401 can refresh again — the guard is not a latch',
        () async {
      final backend = _Backend();
      final api = await _signedIn(backend);
      var refreshes = 0;
      api.sessionRefresher = () async {
        refreshes++;
        return 'fresh-token';
      };

      await api.get('/customer/orders');
      expect(refreshes, 1);

      // Token goes stale again later in the session.
      await api.setToken('stale-again');
      await api.get('/customer/orders');
      expect(refreshes, 2, reason: 'the in-flight guard must release');
    });
  });

  // =========================================================================
  // Observability — every silent exit now says WHICH one it was
  // =========================================================================
  //
  // Five of these paths logged nothing in any build and two logged only under
  // kDebugMode, so a forced re-login on a real phone produced no evidence at
  // all. That is the same shape as the FCM registration bug. These assert the
  // lines exist AND that behaviour is unchanged — a diagnostic that alters what
  // it measures is worse than none.
  group('failure paths are observable', () {
    test('no refresher wired is named, and still logs out', () async {
      final backend = _Backend();
      late ApiClient api;
      final logs = await captureLogs(() async {
        api = await _signedIn(backend);
        await expectLater(api.get('/customer/orders'),
            throwsA(isA<AuthExpiredException>()));
      });

      expect(logs.where((l) => l.contains('refresh UNAVAILABLE')), isNotEmpty);
      expect(logs.where((l) => l.contains('no refresher wired')), isNotEmpty);
      // Behaviour unchanged.
      expect(api.isAuthenticated, isFalse);
      expect(api.authFailures.value, 1);
    });

    test('a null return is named as such, distinct from a throw', () async {
      final backend = _Backend();
      late ApiClient api;
      final logs = await captureLogs(() async {
        api = await _signedIn(backend);
        api.sessionRefresher = () async => null;
        await expectLater(api.get('/customer/orders'),
            throwsA(isA<AuthExpiredException>()));
      });

      expect(logs.where((l) => l.contains('refresh FAILED')), isNotEmpty);
      expect(logs.where((l) => l.contains('returned null')), isNotEmpty);
      expect(logs.where((l) => l.contains('refresh THREW')), isEmpty,
          reason: 'a null return must not be reported as a crash');
      expect(api.isAuthenticated, isFalse);
    });

    test('an empty-string return is distinguished from null', () async {
      final backend = _Backend();
      final logs = await captureLogs(() async {
        final api = await _signedIn(backend);
        api.sessionRefresher = () async => '';
        await expectLater(api.get('/customer/orders'),
            throwsA(isA<AuthExpiredException>()));
      });
      expect(logs.where((l) => l.contains('an empty token')), isNotEmpty);
    });

    test('a throw is named, and carries the cause', () async {
      final backend = _Backend();
      late ApiClient api;
      final logs = await captureLogs(() async {
        api = await _signedIn(backend);
        api.sessionRefresher = () async => throw StateError('firebase exploded');
        await expectLater(api.get('/customer/orders'),
            throwsA(isA<AuthExpiredException>()));
      });

      expect(logs.where((l) => l.contains('refresh THREW')), isNotEmpty);
      expect(logs.where((l) => l.contains('firebase exploded')), isNotEmpty,
          reason: 'the cause is the whole diagnostic value');
      expect(api.isAuthenticated, isFalse);
    });

    test('the attempt itself is logged, before any outcome', () async {
      // Half of the race evidence: this line is what gets compared against
      // "firebase user restored" to tell a race from an ordinary failure.
      final backend = _Backend();
      final logs = await captureLogs(() async {
        final api = await _signedIn(backend);
        api.sessionRefresher = () async => 'fresh-token';
        await api.get('/customer/orders');
      });

      final triggered = logs.indexWhere((l) => l.contains('refresh triggered by a 401'));
      final succeeded = logs.indexWhere((l) => l.contains('refresh SUCCEEDED'));
      expect(triggered, isNonNegative);
      expect(succeeded, greaterThan(triggered),
          reason: 'the attempt must be logged before its outcome');
    });

    test('every line is tagged and carries an elapsed stamp', () async {
      final logs = await captureLogs(() async {
        final api = await _signedIn(_Backend());
        api.sessionRefresher = () async => null;
        await expectLater(api.get('/customer/orders'),
            throwsA(isA<AuthExpiredException>()));
      });
      final ours = logs.where((l) => l.startsWith('[session]')).toList();
      expect(ours, isNotEmpty);
      for (final l in ours) {
        expect(l, matches(RegExp(r'^\[session\] \+\d+ms ')),
            reason: 'a stamp is what makes the sequence readable: $l');
      }
    });

    test('a SUCCESSFUL refresh is quiet about failure', () async {
      // The logs must not cry wolf — a renewed session should read as success.
      final backend = _Backend();
      final logs = await captureLogs(() async {
        final api = await _signedIn(backend);
        api.sessionRefresher = () async => 'fresh-token';
        await api.get('/customer/orders');
      });
      expect(logs.where((l) => l.contains('FAILED')), isEmpty);
      expect(logs.where((l) => l.contains('THREW')), isEmpty);
      expect(logs.where((l) => l.contains('UNAVAILABLE')), isEmpty);
    });

    test('logging did not change the concurrent-401 coalescing', () async {
      // The in-flight guard is the one behaviour a per-attempt log line could
      // plausibly have disturbed.
      final backend = _Backend();
      var refreshes = 0;
      final logs = await captureLogs(() async {
        final api = await _signedIn(backend);
        api.sessionRefresher = () async {
          refreshes++;
          return 'fresh-token';
        };
        await Future.wait(List.generate(5, (_) => api.get('/customer/orders')));
      });

      expect(refreshes, 1, reason: 'still exactly one exchange for five 401s');
      expect(logs.where((l) => l.contains('refresh triggered by a 401')),
          hasLength(1), reason: 'and exactly one attempt line');
    });
  });
}
