// Forgot password, end to end on the app side.
//
// The flow was a dead end in two places at once, and these hold both shut:
//
//   1. NOTHING IN THE APP CALLED /auth/password/reset. The server minted
//      single-use codes and no screen could spend one, so even a delivered
//      email left the owner locked out. `the code is redeemed against
//      /auth/password/reset` is the test that would have caught it.
//   2. THE SCREEN CLAIMED A SEND REGARDLESS. It rendered "we've sent reset
//      instructions" on a server with no mail transport at all. It now words
//      the panel from `email_configured`, which describes the deploy.
//
// Driven through the real AuthState/AuthService over a MockClient, so the JSON
// contract is exercised rather than mocked away. The request log is the proof
// the endpoints were actually hit.
import 'dart:convert';

import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:http/http.dart' as http;
import 'package:http/testing.dart';
import 'package:provider/provider.dart';
import 'package:shared_preferences/shared_preferences.dart';

import 'package:owner_app/screens/forgot_password_screen.dart';
import 'package:owner_app/screens/reset_password_screen.dart';
import 'package:owner_app/services/api_client.dart';
import 'package:owner_app/services/auth_service.dart';
import 'package:owner_app/state/auth_state.dart';

late List<String> requestLog;
late Map<String, dynamic> lastBody;

/// A backend whose mail capability and reset outcome are both dialable, since
/// those are exactly the two axes the screens branch on.
http.Client _backend({
  bool emailConfigured = true,
  String? emailHint = 'a*****a@g***l.com',
  bool needsAdminHelp = false,
  int resetStatus = 200,
}) {
  http.Response json(Object b, [int code = 200]) => http.Response(
      jsonEncode(b), code, headers: {'content-type': 'application/json'});

  return MockClient((req) async {
    final path = req.url.path;
    requestLog.add('${req.method} $path');
    if (req.body.isNotEmpty) {
      lastBody = jsonDecode(req.body) as Map<String, dynamic>;
    }

    if (path.endsWith('/auth/password/forgot')) {
      return json({
        'ok': true,
        'message': emailConfigured
            ? "If that account exists, we've sent reset instructions to the "
                "email on file."
            : 'Email delivery is not configured on this server, so no reset '
                'mail can be sent. Contact your CareVo admin to recover the '
                'account.',
        'email_hint': emailHint,
        'needs_admin_help': needsAdminHelp,
        'email_configured': emailConfigured,
      });
    }

    if (path.endsWith('/auth/password/reset')) {
      if (resetStatus != 200) {
        return json({'detail': 'That reset link is invalid or has expired.'},
            resetStatus);
      }
      return json({'ok': true, 'message': 'Password reset.'});
    }

    return json({'detail': 'unexpected ${req.url}'}, 404);
  });
}

AuthState _authState(http.Client backend) {
  SharedPreferences.setMockInitialValues({});
  return AuthState(AuthService(ApiClient(httpClient: backend)));
}

Widget _hostForgot(http.Client backend) =>
    ChangeNotifierProvider<AuthState>.value(
      value: _authState(backend),
      child: const MaterialApp(home: ForgotPasswordScreen()),
    );

Widget _hostReset(http.Client backend) =>
    ChangeNotifierProvider<AuthState>.value(
      value: _authState(backend),
      child: const MaterialApp(home: ResetPasswordScreen()),
    );

int _count(String entry) => requestLog.where((e) => e == entry).length;

const _forgot = 'POST /api/v1/auth/password/forgot';
const _reset = 'POST /api/v1/auth/password/reset';

/// Fill in the username and submit.
Future<void> _requestReset(WidgetTester tester, {String user = 'anand'}) async {
  await tester.enterText(find.byType(TextFormField), user);
  await tester.tap(find.byKey(ForgotPasswordScreen.submitKey));
  await tester.pumpAndSettle();
}

void main() {
  setUp(() {
    requestLog = [];
    lastBody = {};
  });

  group('requesting the code', () {
    testWidgets('submitting a username hits /auth/password/forgot',
        (tester) async {
      await tester.pumpWidget(_hostForgot(_backend()));
      await tester.pumpAndSettle();
      await _requestReset(tester);

      expect(_count(_forgot), 1);
      expect(lastBody['username'], 'anand');
      expect(find.byKey(ForgotPasswordScreen.resultKey), findsOneWidget);
    });

    testWidgets('the masked address is shown so the owner knows which inbox',
        (tester) async {
      await tester.pumpWidget(_hostForgot(_backend()));
      await tester.pumpAndSettle();
      await _requestReset(tester);

      expect(find.text('a*****a@g***l.com'), findsOneWidget);
    });

    testWidgets('an empty username is refused before any request',
        (tester) async {
      await tester.pumpWidget(_hostForgot(_backend()));
      await tester.pumpAndSettle();

      await tester.tap(find.byKey(ForgotPasswordScreen.submitKey));
      await tester.pumpAndSettle();

      expect(_count(_forgot), 0, reason: 'nothing to look up');
      expect(find.text('Enter your username'), findsOneWidget);
    });
  });

  group('it does not promise mail the server cannot send', () {
    testWidgets('a server with no transport says so and offers the admin route',
        (tester) async {
      await tester.pumpWidget(_hostForgot(
          _backend(emailConfigured: false, emailHint: null, needsAdminHelp: true)));
      await tester.pumpAndSettle();
      await _requestReset(tester);

      expect(find.textContaining('not configured'), findsOneWidget);
      // Twice over: the server's own message, and the admin-route footnote.
      expect(find.textContaining('CareVo admin'), findsWidgets);
      // The regression: it must not claim a send that cannot happen.
      expect(find.textContaining("we've sent"), findsNothing);
    });

    testWidgets('and offers no code entry, because none is coming',
        (tester) async {
      await tester.pumpWidget(_hostForgot(
          _backend(emailConfigured: false, emailHint: null, needsAdminHelp: true)));
      await tester.pumpAndSettle();
      await _requestReset(tester);

      expect(find.byKey(ForgotPasswordScreen.enterCodeKey), findsNothing);
    });

    testWidgets('a configured server offers code entry', (tester) async {
      await tester.pumpWidget(_hostForgot(_backend()));
      await tester.pumpAndSettle();
      await _requestReset(tester);

      expect(find.byKey(ForgotPasswordScreen.enterCodeKey), findsOneWidget);
    });

    testWidgets('code entry is offered even with no hint, so the button itself '
        'reveals nothing', (tester) async {
      // A null hint covers BOTH an unknown username and a rate-limited real
      // one. Hiding the button here would tell the caller which they hit.
      await tester.pumpWidget(_hostForgot(_backend(emailHint: null)));
      await tester.pumpAndSettle();
      await _requestReset(tester);

      expect(find.byKey(ForgotPasswordScreen.enterCodeKey), findsOneWidget);
    });

    testWidgets('"I have a code" opens the reset screen', (tester) async {
      await tester.pumpWidget(_hostForgot(_backend()));
      await tester.pumpAndSettle();
      await _requestReset(tester);

      await tester.tap(find.byKey(ForgotPasswordScreen.enterCodeKey));
      await tester.pumpAndSettle();

      expect(find.byType(ResetPasswordScreen), findsOneWidget);
      // Carries the hint through, so the owner still knows which inbox.
      expect(find.textContaining('a*****a@g***l.com'), findsOneWidget);
    });
  });

  group('redeeming the code', () {
    Future<void> fill(
      WidgetTester tester, {
      String code = 'a-real-looking-reset-token',
      String password = 'brand-new-pw',
      String? confirm,
    }) async {
      await tester.enterText(find.byKey(ResetPasswordScreen.codeKey), code);
      await tester.enterText(
          find.byKey(ResetPasswordScreen.passwordKey), password);
      await tester.enterText(
          find.byKey(ResetPasswordScreen.confirmKey), confirm ?? password);
      await tester.tap(find.byKey(ResetPasswordScreen.submitKey));
      await tester.pumpAndSettle();
    }

    testWidgets('the code is redeemed against /auth/password/reset',
        (tester) async {
      // THE regression. Before ResetPasswordScreen existed nothing in the app
      // called this endpoint at all, so a delivered code had nowhere to go.
      await tester.pumpWidget(_hostReset(_backend()));
      await tester.pumpAndSettle();
      await fill(tester);

      expect(_count(_reset), 1);
      expect(lastBody['token'], 'a-real-looking-reset-token');
      expect(lastBody['new_password'], 'brand-new-pw');
    });

    testWidgets('a rejected code is reported, not swallowed', (tester) async {
      await tester.pumpWidget(_hostReset(_backend(resetStatus: 400)));
      await tester.pumpAndSettle();
      await fill(tester);

      expect(find.textContaining('invalid or has expired'), findsOneWidget);
      expect(find.byType(ResetPasswordScreen), findsOneWidget,
          reason: 'a failed reset must leave the owner on the screen to retry');
    });

    testWidgets('mismatched passwords never reach the server', (tester) async {
      await tester.pumpWidget(_hostReset(_backend()));
      await tester.pumpAndSettle();
      await fill(tester, password: 'brand-new-pw', confirm: 'something-else');

      expect(_count(_reset), 0);
      expect(find.text('Passwords do not match'), findsOneWidget);
    });

    testWidgets('a too-short password is caught before the round trip',
        (tester) async {
      // Mirrors the server's MIN_PASSWORD_LENGTH, so the owner is not made to
      // wait on a cold start to be told about eight characters.
      await tester.pumpWidget(_hostReset(_backend()));
      await tester.pumpAndSettle();
      await fill(tester, password: 'short');

      expect(_count(_reset), 0);
      expect(find.text('At least 8 characters'), findsOneWidget);
    });

    testWidgets('an empty code never reaches the server', (tester) async {
      await tester.pumpWidget(_hostReset(_backend()));
      await tester.pumpAndSettle();
      await fill(tester, code: '');

      expect(_count(_reset), 0);
      expect(find.text('Paste the code from the email'), findsOneWidget);
    });
  });
}
