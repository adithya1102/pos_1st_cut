// A structured FastAPI `detail` must reach the customer as prose, not as a
// Dart Map dump.
//
// THE BUG: ApiClient did `body['detail'].toString()`. `detail` is a STRING for
// most errors, but the server deliberately raises STRUCTURED details for the
// cases a customer most needs explained — ITEM_SOLD_OUT carries the item name
// and the remaining count, UNPAID_ORDER_PENDING carries the order id. On those,
// `.toString()` renders Dart's debug form of a Map:
//
//   {error: ITEM_SOLD_OUT, menu_item_id: 9f2…, name: Masala Dosa,
//    requested: 2, remaining: 1, message: Masala Dosa: only 1 left, …}
//
// and checkout_screen.dart shows ApiException.message verbatim in a SnackBar,
// so that string is what the customer reads at the moment their order fails.
//
// Every structured detail carries a `message` written for a human. That is what
// is surfaced now.
import 'dart:convert';

import 'package:flutter_test/flutter_test.dart';
import 'package:http/http.dart' as http;
import 'package:http/testing.dart';
import 'package:shared_preferences/shared_preferences.dart';

import 'package:customer_app/services/api_client.dart';

ApiClient _client(Object body, {int status = 409}) {
  SharedPreferences.setMockInitialValues({'carevo_access_token': 't'});
  return ApiClient(
    client: MockClient((req) async => http.Response(
          jsonEncode(body),
          status,
          headers: {'content-type': 'application/json'},
        )),
  );
}

Future<ApiException> _capture(ApiClient api) async {
  try {
    await api.get('/customer/orders');
    fail('the request did not throw');
  } on ApiException catch (e) {
    return e;
  }
}

void main() {
  group('a structured detail surfaces its message', () {
    test('UNPAID_ORDER_PENDING shows the sentence, not the map', () async {
      const message = 'You already have an unpaid order at this restaurant. '
          'Finish paying for it, or cancel it, before placing another.';
      final e = await _capture(_client({
        'detail': {
          'error': 'UNPAID_ORDER_PENDING',
          'order_id': '9f2c8a10-0000-4000-8000-000000000001',
          'message': message,
        }
      }));

      expect(e.message, message);
      expect(e.statusCode, 409);
      // The three tells of the old behaviour.
      expect(e.message, isNot(contains('{')));
      expect(e.message, isNot(contains('error:')));
      expect(e.message, isNot(contains('9f2c8a10')));
    });

    test('ITEM_SOLD_OUT shows the sentence, not the map', () async {
      const message = 'Masala Dosa: only 1 left, you asked for 2.';
      final e = await _capture(_client({
        'detail': {
          'error': 'ITEM_SOLD_OUT',
          'menu_item_id': '9f2c8a10-0000-4000-8000-000000000002',
          'name': 'Masala Dosa',
          'requested': 2,
          'remaining': 1,
          'message': message,
        }
      }));

      expect(e.message, message);
      expect(e.message, isNot(contains('requested:')));
    });

    test('a detail with no message falls back to the error CODE', () async {
      // Still not a dump. A short code is something a support conversation can
      // work with; Dart's Map form is not.
      final e = await _capture(_client({
        'detail': {'error': 'SOMETHING_SPECIFIC'}
      }));
      expect(e.message, 'SOMETHING_SPECIFIC');
    });

    test('a detail with neither key does not dump the map', () async {
      final e = await _capture(_client({
        'detail': {'unexpected': 'shape', 'nested': {'a': 1}}
      }, status: 500));
      expect(e.message, isNot(contains('unexpected')));
      expect(e.message, contains('500'));
    });

    test('a plain string detail is unchanged', () async {
      // The common case, and the one that already worked — this is the
      // regression guard for it.
      final e = await _capture(_client({'detail': 'Item unavailable: Dosa'}));
      expect(e.message, 'Item unavailable: Dosa');
    });

    test('a FastAPI validation list is not rendered at customers', () async {
      // 422 bodies are a LIST of per-field objects whose msgs are framework
      // prose ("field required"). The generic fallback is more honest.
      final e = await _capture(_client({
        'detail': [
          {'loc': ['body', 'items'], 'msg': 'field required',
           'type': 'value_error.missing'}
        ]
      }, status: 422));
      expect(e.message, isNot(contains('value_error')));
      expect(e.message, isNot(contains('loc')));
      expect(e.message, contains('422'));
    });

    test('a body with no detail at all still reports something', () async {
      final e = await _capture(_client({'message': 'Upstream exploded'},
          status: 502));
      expect(e.message, 'Upstream exploded');
    });
  });
}
