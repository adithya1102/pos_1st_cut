// TASK 3 — a phone-less (Google-only) account is ASKED for a mobile number
// when it picks a non-prepaid method, instead of having the method withheld.
//
// The field lives on ConfirmContactScreen (the existing confirm-your-details
// step before every non-prepaid order): numeric keypad, validated by the one
// shared rule (utils/in_mobile.dart), blocking Confirm until valid, and the
// canonical +91 number is handed back for checkout to send as contact_phone.
// An account that HAS a phone keeps the read-only card exactly as before.
import 'dart:convert';

import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:http/http.dart' as http;
import 'package:http/testing.dart';
import 'package:provider/provider.dart';
import 'package:shared_preferences/shared_preferences.dart';

import 'package:customer_app/screens/confirm_contact_screen.dart';
import 'package:customer_app/services/api_client.dart';
import 'package:customer_app/services/customer_service.dart';
import 'package:customer_app/services/google_auth_service.dart';
import 'package:customer_app/services/otp_auth_service.dart';
import 'package:customer_app/services/push_service.dart';
import 'package:customer_app/state/auth_state.dart';
import 'package:customer_app/theme/app_theme.dart';

http.Response _json(Object body) => http.Response(jsonEncode(body), 200,
    headers: {'content-type': 'application/json'});

Future<AuthState> _authWith(Map<String, dynamic> customer) async {
  SharedPreferences.setMockInitialValues({});
  final api = ApiClient(client: MockClient((req) async {
    if (req.url.path.contains('request-otp')) return _json({'request_id': 'r'});
    if (req.url.path.contains('verify-otp')) {
      return _json({'access_token': 'tok', 'customer': customer});
    }
    return _json(const {});
  }));
  final auth = AuthState(
      api, StubOtpService(api), GoogleAuthService(api), PushService(api));
  await auth.requestOtp('+919876543210');
  await auth.verifyOtp('123456');
  return auth;
}

Widget _host(AuthState auth,
    {required ValueChanged<String> onContactPhone,
    required VoidCallback onConfirmed}) {
  final api = ApiClient(client: MockClient((_) async => _json(const {})));
  return MultiProvider(
    providers: [
      Provider<ApiClient>.value(value: api),
      Provider<CustomerService>(create: (_) => CustomerService(api)),
      ChangeNotifierProvider<AuthState>.value(value: auth),
    ],
    child: MaterialApp(
      theme: AppTheme.light(),
      home: ConfirmContactScreen(
        onConfirmed: onConfirmed,
        onContactPhone: onContactPhone,
      ),
    ),
  );
}

void main() {
  testWidgets('a phone-less account gets an editable number field that blocks '
      'Confirm until the number is valid', (tester) async {
    final auth = await _authWith({'id': 'c1', 'name': 'Googler'});
    String? handed;
    var confirmed = false;
    await tester.pumpWidget(_host(auth,
        onContactPhone: (p) => handed = p, onConfirmed: () => confirmed = true));
    await tester.pump();

    final field = find.byKey(const Key('confirm_contact_phone_field'));
    expect(field, findsOneWidget);
    // And the read-only card is gone — there is nothing to read.
    expect(find.byKey(const Key('confirm_contact_phone_value')), findsNothing);

    // Empty: blocked with a message, nothing handed back.
    await tester.tap(find.byKey(const Key('confirm_contact_continue')));
    await tester.pumpAndSettle();
    expect(confirmed, isFalse);
    expect(find.byKey(const Key('confirm_contact_error')), findsOneWidget);

    // Invalid: still blocked.
    await tester.enterText(field, '12345');
    await tester.tap(find.byKey(const Key('confirm_contact_continue')));
    await tester.pumpAndSettle();
    expect(confirmed, isFalse);

    // Valid in a messy spelling: confirmed, canonical +91 handed back.
    await tester.enterText(field, '94999 56612');
    await tester.tap(find.byKey(const Key('confirm_contact_continue')));
    await tester.pumpAndSettle();
    expect(confirmed, isTrue);
    expect(handed, '+919499956612');
  });

  testWidgets('the number field uses a phone keypad', (tester) async {
    final auth = await _authWith({'id': 'c1', 'name': 'Googler'});
    await tester.pumpWidget(
        _host(auth, onContactPhone: (_) {}, onConfirmed: () {}));
    await tester.pump();

    final tf = tester.widget<TextField>(find.descendant(
        of: find.byKey(const Key('confirm_contact_phone_field')),
        matching: find.byType(TextField)));
    expect(tf.keyboardType, TextInputType.phone);
  });

  testWidgets('an account with a phone keeps the read-only card',
      (tester) async {
    final auth = await _authWith(
        {'id': 'c1', 'name': 'Asha', 'phone_number': '+919876543210'});
    var confirmed = false;
    await tester.pumpWidget(_host(auth,
        onContactPhone: (_) {}, onConfirmed: () => confirmed = true));
    await tester.pump();

    expect(find.byKey(const Key('confirm_contact_phone_field')), findsNothing);
    expect(find.byKey(const Key('confirm_contact_phone_value')), findsOneWidget);
    expect(find.text('+919876543210'), findsOneWidget);

    await tester.tap(find.byKey(const Key('confirm_contact_continue')));
    await tester.pumpAndSettle();
    expect(confirmed, isTrue, reason: 'unchanged flow for phone accounts');
  });
}
