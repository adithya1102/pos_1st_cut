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

import 'package:flutter_test/flutter_test.dart';
import 'package:http/http.dart' as http;
import 'package:http/testing.dart';
import 'package:shared_preferences/shared_preferences.dart';

import 'package:customer_app/services/api_client.dart';

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
}
