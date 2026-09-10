// FCM token registration must never fail invisibly again.
//
// Production sat at ZERO stored tokens across 45 customer accounts for a month.
// The code was wired correctly end to end — login called it, the endpoint
// existed, the UPDATE worked — but every failure path inside PushService was a
// bare `return` with no log line, so nothing anywhere said which path was
// taken, and the fix could not even be aimed.
//
// These tests drive PushService through injected permission/token seams and a
// MockClient backend, which is the whole reason those seams exist: registration
// is assertable without a Firebase app.
//
// The load-bearing case is `permission denied still registers`. That single
// early return is what made the failure permanent — Android stops showing the
// permission dialog after two dismissals, so once denied, every subsequent
// login took the same silent path forever.
import 'dart:async';
import 'dart:convert';

import 'package:flutter/foundation.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:http/http.dart' as http;
import 'package:http/testing.dart';
import 'package:shared_preferences/shared_preferences.dart';

import 'package:customer_app/services/api_client.dart';
import 'package:customer_app/services/push_service.dart';

http.Response _json(Object body, {int status = 200}) =>
    http.Response(jsonEncode(body), status,
        headers: {'content-type': 'application/json'});

/// Records what actually reached the backend, so a test can assert the token
/// was sent rather than merely that no exception escaped.
class _Backend {
  _Backend({this.status = 200});

  final int status;
  final List<String> paths = [];
  final List<String?> tokens = [];

  http.Client client() => MockClient((req) async {
        paths.add(req.url.path);
        if (req.method == 'POST' && req.url.path.contains('push/register')) {
          final body = jsonDecode(req.body) as Map<String, dynamic>;
          tokens.add(body['fcm_token'] as String?);
          if (status != 200) {
            return _json({'detail': 'nope'}, status: status);
          }
          return _json({'ok': true, 'push_configured': true});
        }
        return _json({'ok': true});
      });
}

/// Captures debugPrint so "is this observable?" is a real assertion and not a
/// matter of trusting that a log line exists.
Future<List<String>> _captureLogs(Future<void> Function() body) async {
  final logs = <String>[];
  final previous = debugPrint;
  debugPrint = (String? message, {int? wrapWidth}) {
    if (message != null) logs.add(message);
  };
  try {
    await body();
  } finally {
    debugPrint = previous;
  }
  return logs;
}

Future<ApiClient> _authedClient(_Backend backend) async {
  SharedPreferences.setMockInitialValues({});
  final api = ApiClient(client: backend.client());
  await api.setToken('a-customer-jwt');
  return api;
}

void main() {
  TestWidgetsFlutterBinding.ensureInitialized();

  group('permission denied', () {
    test('still registers the token — a denial must not be permanent', () async {
      final backend = _Backend();
      final api = await _authedClient(backend);
      final push = PushService(
        api,
        requestPermission: () async => false,
        fetchToken: () async => 'token-despite-denial',
        tokenRefreshes: () => const Stream<String>.empty(),
      );

      await push.registerAfterLogin();

      // The regression this whole fix exists for: POST_NOTIFICATIONS governs
      // whether an alert is DISPLAYED, not whether FCM will issue a token.
      // Skipping registration threw away a usable token forever.
      expect(backend.tokens, ['token-despite-denial'],
          reason: 'a denied permission must not stop the token registering');
      expect(push.status.value, PushRegistrationStatus.registered);
      expect(push.granted, isFalse,
          reason: 'granted still reports the real permission answer');
    });

    test('says so in the log rather than returning silently', () async {
      final backend = _Backend();
      final api = await _authedClient(backend);
      final push = PushService(
        api,
        requestPermission: () async => false,
        fetchToken: () async => 'tok',
        tokenRefreshes: () => const Stream<String>.empty(),
      );

      final logs = await _captureLogs(push.registerAfterLogin);

      expect(logs.any((l) => l.contains('permission denied')), isTrue,
          reason: 'the denial must leave a trace; it used to leave none');
    });

    test('does not crash when the permission request itself throws', () async {
      final backend = _Backend();
      final api = await _authedClient(backend);
      final push = PushService(
        api,
        requestPermission: () async => throw Exception('no play services'),
        fetchToken: () async => 'tok-anyway',
        tokenRefreshes: () => const Stream<String>.empty(),
      );

      await expectLater(push.registerAfterLogin(), completes);
      // A broken permission plugin must not cost us the token.
      expect(backend.tokens, ['tok-anyway']);
    });
  });

  group('getToken failure', () {
    test('null token is observable, not swallowed', () async {
      final backend = _Backend();
      final api = await _authedClient(backend);
      final push = PushService(
        api,
        requestPermission: () async => true,
        fetchToken: () async => null,
        tokenRefreshes: () => const Stream<String>.empty(),
      );

      final logs = await _captureLogs(push.registerAfterLogin);

      expect(push.status.value, PushRegistrationStatus.noToken);
      expect(logs.any((l) => l.contains('null')), isTrue);
      expect(backend.tokens, isEmpty,
          reason: 'nothing to send, so nothing should be sent');
    });

    test('empty token is treated as no token', () async {
      final backend = _Backend();
      final api = await _authedClient(backend);
      final push = PushService(
        api,
        requestPermission: () async => true,
        fetchToken: () async => '',
        tokenRefreshes: () => const Stream<String>.empty(),
      );

      await push.registerAfterLogin();

      expect(push.status.value, PushRegistrationStatus.noToken);
      expect(backend.tokens, isEmpty);
    });

    test('a throwing getToken is logged and does not escape', () async {
      final backend = _Backend();
      final api = await _authedClient(backend);
      final push = PushService(
        api,
        requestPermission: () async => true,
        fetchToken: () async => throw Exception('SERVICE_NOT_AVAILABLE'),
        tokenRefreshes: () => const Stream<String>.empty(),
      );

      final logs = await _captureLogs(
          () => expectLater(push.registerAfterLogin(), completes));

      expect(push.status.value, PushRegistrationStatus.unavailable);
      expect(logs.any((l) => l.contains('SERVICE_NOT_AVAILABLE')), isTrue);
    });
  });

  group('POST failure', () {
    test('a non-200 is logged and marked, not dropped', () async {
      final backend = _Backend(status: 500);
      final api = await _authedClient(backend);
      final push = PushService(
        api,
        requestPermission: () async => true,
        fetchToken: () async => 'tok',
        tokenRefreshes: () => const Stream<String>.empty(),
      );

      final logs = await _captureLogs(push.registerAfterLogin);

      expect(push.status.value, PushRegistrationStatus.sendFailed);
      expect(logs.any((l) => l.contains('POST failed')), isTrue);
    });

    test('a failed send is retried on the next attempt', () async {
      // The old code set _lastRegistered before knowing the POST succeeded on
      // the retry path, so a transient failure could mark a token as done.
      var fail = true;
      SharedPreferences.setMockInitialValues({});
      final sent = <String>[];
      final api = ApiClient(client: MockClient((req) async {
        if (req.method == 'POST' && req.url.path.contains('push/register')) {
          sent.add((jsonDecode(req.body) as Map)['fcm_token'] as String);
          if (fail) return _json({'detail': 'boom'}, status: 503);
        }
        return _json({'ok': true});
      }));
      await api.setToken('jwt');

      final push = PushService(
        api,
        requestPermission: () async => true,
        fetchToken: () async => 'same-token',
        tokenRefreshes: () => const Stream<String>.empty(),
      );

      await push.registerAfterLogin();
      expect(push.status.value, PushRegistrationStatus.sendFailed);

      fail = false;
      await push.ensureRegistered();

      expect(sent, ['same-token', 'same-token'],
          reason: 'the same token must be re-sent after a failure');
      expect(push.status.value, PushRegistrationStatus.registered);
    });
  });

  group('happy path — no regression', () {
    test('permission granted registers exactly once', () async {
      final backend = _Backend();
      final api = await _authedClient(backend);
      final push = PushService(
        api,
        requestPermission: () async => true,
        fetchToken: () async => 'good-token',
        tokenRefreshes: () => const Stream<String>.empty(),
      );

      await push.registerAfterLogin();

      expect(push.granted, isTrue);
      expect(push.status.value, PushRegistrationStatus.registered);
      expect(backend.tokens, ['good-token']);
    });

    test('a second attempt does not re-POST an unchanged token', () async {
      final backend = _Backend();
      final api = await _authedClient(backend);
      final push = PushService(
        api,
        requestPermission: () async => true,
        fetchToken: () async => 'good-token',
        tokenRefreshes: () => const Stream<String>.empty(),
      );

      await push.registerAfterLogin();
      await push.ensureRegistered();

      expect(backend.tokens, ['good-token'],
          reason: 'success is sticky; only failures retry');
    });

    test('a rotated token is sent', () async {
      final backend = _Backend();
      final api = await _authedClient(backend);
      final rotations = StreamController<String>.broadcast();
      addTearDown(rotations.close);

      final push = PushService(
        api,
        requestPermission: () async => true,
        fetchToken: () async => 'first',
        tokenRefreshes: () => rotations.stream,
      );

      await push.registerAfterLogin();
      rotations.add('rotated');
      await Future<void>.delayed(Duration.zero);

      expect(backend.tokens, ['first', 'rotated']);
    });
  });

  group('restored session', () {
    test('ensureRegistered registers a session that never saw login', () async {
      // The structural gap: registration only ever ran inside verifyOtp and
      // signInWithGoogle, but a customer logs in once and stays signed in for
      // weeks, so neither ran again.
      final backend = _Backend();
      final api = await _authedClient(backend);
      final push = PushService(
        api,
        requestPermission: () async =>
            fail('app start must not raise the OS permission dialog'),
        fetchToken: () async => 'restored-session-token',
        tokenRefreshes: () => const Stream<String>.empty(),
      );

      await push.ensureRegistered();

      expect(backend.tokens, ['restored-session-token']);
      expect(push.status.value, PushRegistrationStatus.registered);
    });

    test('does nothing when there is no session to register against', () async {
      SharedPreferences.setMockInitialValues({});
      final backend = _Backend();
      final api = ApiClient(client: backend.client()); // no token set

      final push = PushService(
        api,
        requestPermission: () async => true,
        fetchToken: () async => fail('must not fetch a token when signed out'),
        tokenRefreshes: () => const Stream<String>.empty(),
      );

      await push.ensureRegistered();

      expect(backend.tokens, isEmpty);
      expect(push.status.value, PushRegistrationStatus.notAttempted);
    });
  });
}
