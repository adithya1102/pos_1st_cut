// Staff FCM registration must never fail invisibly again.
//
// All nine `users` rows sat at fcm_token = NULL for a month. Worse than the
// customer side: not one staff row had even a fcm_token_updated_at stamp, so
// `/pos/push/register` had never once been reached successfully — and because
// every debugPrint in StaffPushService was wrapped in `if (kDebugMode)`, the
// release build running on the actual tablet logged precisely nothing.
//
// This matters more here than for customers. There is no Accept gate on an
// order: a paid order goes straight to RECEIVED, so this notification is the
// entire mechanism by which staff learn in time to reject one they cannot make.
import 'dart:async';
import 'dart:convert';

import 'package:flutter/foundation.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:http/http.dart' as http;
import 'package:http/testing.dart';
import 'package:shared_preferences/shared_preferences.dart';

import 'package:owner_app/services/api_client.dart';
import 'package:owner_app/services/order_service.dart';
import 'package:owner_app/services/staff_push_service.dart';

http.Response _json(Object body, {int status = 200}) =>
    http.Response(jsonEncode(body), status,
        headers: {'content-type': 'application/json'});

class _Backend {
  _Backend({this.status = 200});

  final int status;
  final List<String> tokens = [];

  http.Client client() => MockClient((req) async {
        if (req.method == 'POST' && req.url.path.contains('push/register')) {
          tokens.add((jsonDecode(req.body) as Map)['fcm_token'] as String);
          if (status != 200) return _json({'detail': 'nope'}, status: status);
          return _json({'ok': true, 'registered': true});
        }
        return _json({'ok': true});
      });
}

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

Future<OrderService> _orders(_Backend backend) async {
  SharedPreferences.setMockInitialValues({});
  final api = ApiClient(httpClient: backend.client());
  await api.saveToken('a-staff-jwt');
  return OrderService(api);
}

void main() {
  TestWidgetsFlutterBinding.ensureInitialized();

  group('permission denied', () {
    test('still registers — the outlet must not lose its only alert', () async {
      final backend = _Backend();
      final push = StaffPushService(
        await _orders(backend),
        requestPermission: () async => false,
        fetchToken: () async => 'staff-token-despite-denial',
        tokenRefreshes: () => const Stream<String>.empty(),
      );

      await push.registerAfterLogin();

      expect(backend.tokens, ['staff-token-despite-denial']);
      expect(push.status.value, StaffPushStatus.registered);
      expect(push.granted, isFalse);
    });

    test('leaves a log line in release builds, not only debug', () async {
      final backend = _Backend();
      final push = StaffPushService(
        await _orders(backend),
        requestPermission: () async => false,
        fetchToken: () async => 'tok',
        tokenRefreshes: () => const Stream<String>.empty(),
      );

      final logs = await _captureLogs(push.registerAfterLogin);

      expect(logs.any((l) => l.contains('permission denied')), isTrue);
    });
  });

  group('getToken failure', () {
    test('null token is observable', () async {
      final backend = _Backend();
      final push = StaffPushService(
        await _orders(backend),
        requestPermission: () async => true,
        fetchToken: () async => null,
        tokenRefreshes: () => const Stream<String>.empty(),
      );

      final logs = await _captureLogs(push.registerAfterLogin);

      expect(push.status.value, StaffPushStatus.noToken);
      expect(logs.any((l) => l.contains('null')), isTrue);
      expect(backend.tokens, isEmpty);
    });

    test('a throwing getToken does not escape into the login flow', () async {
      final backend = _Backend();
      final push = StaffPushService(
        await _orders(backend),
        requestPermission: () async => true,
        fetchToken: () async => throw Exception('SERVICE_NOT_AVAILABLE'),
        tokenRefreshes: () => const Stream<String>.empty(),
      );

      final logs = await _captureLogs(
          () => expectLater(push.registerAfterLogin(), completes));

      expect(push.status.value, StaffPushStatus.unavailable);
      expect(logs.any((l) => l.contains('SERVICE_NOT_AVAILABLE')), isTrue);
    });
  });

  group('POST failure', () {
    test('a non-200 is marked and logged', () async {
      final backend = _Backend(status: 500);
      final push = StaffPushService(
        await _orders(backend),
        requestPermission: () async => true,
        fetchToken: () async => 'tok',
        tokenRefreshes: () => const Stream<String>.empty(),
      );

      final logs = await _captureLogs(push.registerAfterLogin);

      expect(push.status.value, StaffPushStatus.sendFailed);
      expect(logs.any((l) => l.contains('POST failed')), isTrue);
    });

    test('is retried on the next attempt rather than given up on', () async {
      var fail = true;
      SharedPreferences.setMockInitialValues({});
      final sent = <String>[];
      final api = ApiClient(httpClient: MockClient((req) async {
        if (req.method == 'POST' && req.url.path.contains('push/register')) {
          sent.add((jsonDecode(req.body) as Map)['fcm_token'] as String);
          if (fail) return _json({'detail': 'boom'}, status: 503);
        }
        return _json({'ok': true});
      }));
      await api.saveToken('jwt');

      final push = StaffPushService(
        OrderService(api),
        requestPermission: () async => true,
        fetchToken: () async => 'same-token',
        tokenRefreshes: () => const Stream<String>.empty(),
      );

      await push.registerAfterLogin();
      expect(push.status.value, StaffPushStatus.sendFailed);

      fail = false;
      await push.ensureRegistered();

      expect(sent, ['same-token', 'same-token']);
      expect(push.status.value, StaffPushStatus.registered);
    });
  });

  group('happy path — no regression', () {
    test('permission granted registers exactly once', () async {
      final backend = _Backend();
      final push = StaffPushService(
        await _orders(backend),
        requestPermission: () async => true,
        fetchToken: () async => 'good-staff-token',
        tokenRefreshes: () => const Stream<String>.empty(),
      );

      await push.registerAfterLogin();

      expect(push.granted, isTrue);
      expect(push.status.value, StaffPushStatus.registered);
      expect(backend.tokens, ['good-staff-token']);
    });

    test('a rotated token is sent', () async {
      final backend = _Backend();
      final rotations = StreamController<String>.broadcast();
      addTearDown(rotations.close);

      final push = StaffPushService(
        await _orders(backend),
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
    test('ensureRegistered covers a tablet already logged in', () async {
      // HomeScreen calls this on mount. Staff log a tablet in once and it stays
      // logged in for weeks, so the login screen alone was never going to run
      // again — which is exactly how all nine rows stayed NULL.
      final backend = _Backend();
      final push = StaffPushService(
        await _orders(backend),
        requestPermission: () async =>
            fail('app start must not raise the OS permission dialog'),
        fetchToken: () async => 'restored-staff-token',
        tokenRefreshes: () => const Stream<String>.empty(),
      );

      await push.ensureRegistered();

      expect(backend.tokens, ['restored-staff-token']);
      expect(push.status.value, StaffPushStatus.registered);
    });

    test('is a no-op once already registered', () async {
      final backend = _Backend();
      final push = StaffPushService(
        await _orders(backend),
        requestPermission: () async => true,
        fetchToken: () async => 'tok',
        tokenRefreshes: () => const Stream<String>.empty(),
      );

      await push.registerAfterLogin();
      await push.ensureRegistered();

      expect(backend.tokens, ['tok']);
    });
  });
}
