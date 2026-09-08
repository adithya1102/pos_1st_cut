// The cold-start retry, the error classifier, and the CDN thumbnail fix.
//
// THE BUG BEHIND THE RETRY: the backend runs on Render's free plan, which
// sleeps a service after 15 minutes idle. A cold call was MEASURED at 32.4s
// against 0.27s warm, and AppConfig.requestTimeout is 20s — so a cold app open
// timed out and showed "couldn't load orders", and a manual retry seconds later
// succeeded because the server had finished booting by then. Not an auth race:
// the token is awaited in main() before runApp (main.dart:40).
import 'dart:async';
import 'dart:convert';
import 'dart:io';

import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:http/http.dart' as http;
import 'package:http/testing.dart';
import 'package:shared_preferences/shared_preferences.dart';

import 'package:customer_app/services/api_client.dart';
import 'package:customer_app/services/app_error.dart';
import 'package:customer_app/services/image_cdn.dart';
import 'package:customer_app/theme/app_theme.dart';
import 'package:customer_app/widgets/error_state.dart';

http.Response _ok(Object body) => http.Response(jsonEncode(body), 200,
    headers: {'content-type': 'application/json'});

ApiClient _client(http.Client inner) {
  SharedPreferences.setMockInitialValues({'carevo_access_token': 't'});
  return ApiClient(client: inner);
}

void main() {
  group('cold start: a read retries itself once, silently', () {
    test('a timed-out GET is retried and the retry\'s result is returned',
        () async {
      // Exactly the production shape: attempt 1 times out (server asleep),
      // attempt 2 succeeds (server now awake).
      var calls = 0;
      final api = _client(MockClient((req) async {
        calls++;
        if (calls == 1) throw TimeoutException('after 0:00:20');
        return _ok([
          {'order_id': 'o1'}
        ]);
      }));

      final result = await api.get('/customer/orders');

      expect(calls, 2, reason: 'the first failure must be retried');
      expect(result, isA<List>());
      expect((result as List).first['order_id'], 'o1');
    });

    test('an offline GET is retried too', () async {
      var calls = 0;
      final api = _client(MockClient((req) async {
        calls++;
        if (calls == 1) throw const SocketException('Failed host lookup');
        return _ok(const {'ok': true});
      }));

      await api.get('/customer/outlets');
      expect(calls, 2);
    });

    test('it retries ONCE, not forever — a real outage still surfaces',
        () async {
      var calls = 0;
      final api = _client(MockClient((req) async {
        calls++;
        throw TimeoutException('always down');
      }));

      await expectLater(
          api.get('/customer/orders'), throwsA(isA<NetworkException>()));
      expect(calls, 2, reason: 'one attempt plus one retry, then give up');
    });

    test('a 500 is NOT retried — the server answered, repeating gains nothing',
        () async {
      var calls = 0;
      final api = _client(MockClient((req) async {
        calls++;
        return http.Response('{"detail":"boom"}', 500,
            headers: {'content-type': 'application/json'});
      }));

      await expectLater(api.get('/x'), throwsA(isA<ApiException>()));
      expect(calls, 1);
    });

    test('POST is NEVER retried — it could place a second order', () async {
      // The safety rule that makes the retry acceptable at all.
      var calls = 0;
      final api = _client(MockClient((req) async {
        calls++;
        throw TimeoutException('lost the reply');
      }));

      await expectLater(
          api.post('/customer/orders', body: const {}), throwsA(isA<ApiException>()));
      expect(calls, 1,
          reason: 'retrying a write risks charging someone twice');
    });

    test('the cause survives for the classifier instead of being stringified',
        () async {
      final api = _client(MockClient((req) async {
        throw TimeoutException('after 0:00:20');
      }));
      try {
        await api.get('/x');
        fail('should have thrown');
      } on NetworkException catch (e) {
        expect(e.cause, isA<TimeoutException>());
        expect(AppError.from(e).kind, AppErrorKind.timeout);
      }
    });
  });

  group('error classifier: each category gets its exact copy', () {
    void expectCopy(AppError e, AppErrorKind kind, String title, String msg) {
      expect(e.kind, kind);
      expect(e.title, title);
      expect(e.message, msg);
    }

    test('offline', () {
      expectCopy(
        AppError.from(NetworkException(const SocketException('no route'))),
        AppErrorKind.offline,
        "Looks like you're offline.",
        "Get connected and we'll bring the menu right back.",
      );
    });

    test('timeout', () {
      expectCopy(
        AppError.from(NetworkException(TimeoutException('slow'))),
        AppErrorKind.timeout,
        'Almost there...',
        'The menu took a little longer than expected.',
      );
    });

    test('server 5xx', () {
      expectCopy(
        AppError.from(ApiException('boom', statusCode: 503)),
        AppErrorKind.server,
        'We hit a little roadblock.',
        'Your menu is just a moment away. Please try again.',
      );
    });

    test('request 4xx', () {
      expectCopy(
        AppError.from(ApiException('nope', statusCode: 404)),
        AppErrorKind.request,
        'The menu is taking a little longer than expected.',
        'Hang tight and try again.',
      );
    });

    test('empty is not an error and offers no retry', () {
      final e = AppError.empty();
      expectCopy(e, AppErrorKind.empty, 'Nothing here yet.',
          'Try another location or explore a different menu.');
      expect(e.canRetry, isFalse,
          reason: 'the request worked; there is nothing to try again');
    });

    test('unknown fallback', () {
      expectCopy(
        AppError.from(StateError('who knows')),
        AppErrorKind.unknown,
        "We won't keep you hungry for long.",
        "You're just one tap away from exploring the menu.",
      );
    });

    test('every non-empty category can be retried', () {
      for (final kind in AppErrorKind.values) {
        final e = kind == AppErrorKind.empty
            ? AppError.empty()
            : AppError.from(ApiException('x', statusCode: 500));
        expect(e.canRetry, kind != AppErrorKind.empty);
      }
    });

    test('the technical detail is captured but is NOT the shown copy', () {
      final e = AppError.from(NetworkException(TimeoutException('after 20s')));
      expect(e.technical, contains('TimeoutException'));
      expect(e.title, isNot(contains('TimeoutException')));
      expect(e.message, isNot(contains('TimeoutException')));
    });
  });

  group('ErrorStateView renders the copy and retries', () {
    Widget host(AppError e, {Future<void> Function()? onRetry}) => MaterialApp(
          theme: AppTheme.light(),
          home: Scaffold(body: ErrorStateView(error: e, onRetry: onRetry)),
        );

    testWidgets('shows title and message, never the technical detail',
        (tester) async {
      final e = AppError.from(NetworkException(TimeoutException('after 20s')));
      await tester.pumpWidget(host(e, onRetry: () async {}));

      expect(find.text('Almost there...'), findsOneWidget);
      expect(find.text('The menu took a little longer than expected.'),
          findsOneWidget);
      expect(find.textContaining('TimeoutException'), findsNothing,
          reason: 'internals must never reach the screen');
    });

    testWidgets('Try Again re-fires the original request', (tester) async {
      var fired = 0;
      await tester.pumpWidget(host(
        AppError.from(ApiException('down', statusCode: 500)),
        onRetry: () async => fired++,
      ));

      await tester.tap(find.byKey(const Key('error_state_retry')));
      await tester.pump();
      expect(fired, 1);
    });

    testWidgets('the empty state offers no Try Again', (tester) async {
      await tester.pumpWidget(host(AppError.empty(), onRetry: () async {}));
      expect(find.text('Nothing here yet.'), findsOneWidget);
      expect(find.byKey(const Key('error_state_retry')), findsNothing);
    });
  });

  group('nearby latency: thumbnails instead of full-size originals', () {
    const real =
        'https://res.cloudinary.com/dglpn1zyi/image/upload/v1787260661/abc.jpg';

    test('a Cloudinary URL gains a resize + auto quality/format', () {
      final out = cdnThumbnail(real)!;
      expect(out, contains('/image/upload/w_200,h_200,c_fill,q_auto,f_auto/'));
      expect(out, endsWith('v1787260661/abc.jpg'),
          reason: 'the asset itself must be unchanged');
    });

    test('a non-Cloudinary URL is returned untouched', () {
      const other = 'https://example.com/pics/a.jpg';
      expect(cdnThumbnail(other), other);
    });

    test('an already-transformed URL is left alone', () {
      const done =
          'https://res.cloudinary.com/c/image/upload/w_50,h_50/v1/a.jpg';
      expect(cdnThumbnail(done), done);
      const single = 'https://res.cloudinary.com/c/image/upload/w_50/v1/a.jpg';
      expect(cdnThumbnail(single), single);
    });

    test('null and empty pass through rather than throwing', () {
      expect(cdnThumbnail(null), isNull);
      expect(cdnThumbnail(''), '');
    });

    test('an unparseable or odd URL still renders rather than breaking', () {
      // The important half: this may only make an image cheaper, never absent.
      const weird = 'not a url at all';
      expect(cdnThumbnail(weird), weird);
    });
  });
}
