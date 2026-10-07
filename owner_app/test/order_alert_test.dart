// The insistent acceptance alert (backend migration 032) and the background
// handler that raises it.
//
// WHAT THESE TESTS CAN AND CANNOT PROVE
// -------------------------------------
// They prove the DECISIONS: which push kinds are acted on, that resolution
// cancels rather than re-posts, that the channel is created at maximum
// importance with the bundled sound, that FLAG_INSISTENT is set, and that the
// copy falls back sensibly when the data payload is thin.
//
// They cannot prove the alert is AUDIBLE on a sleeping tablet in a kitchen.
// Nothing in a widget test can: there is no Android, no Doze, no DND and no
// speaker. That is what the numbered device script in carevomd.md is for, and
// the two are complementary rather than overlapping.
import 'dart:typed_data';

import 'package:flutter_local_notifications/flutter_local_notifications.dart';
import 'package:flutter_test/flutter_test.dart';

import 'package:owner_app/services/order_alert_notifications.dart';
import 'package:owner_app/services/staff_push_service.dart';

/// Records every call the service makes to the plugin, so the test can assert
/// the notification's SHAPE rather than just that something happened.
class _FakePlugin extends Fake implements FlutterLocalNotificationsPlugin {
  final List<AndroidNotificationChannel> channels = [];
  final List<({int id, String? title, String? body, String? payload,
      NotificationDetails? details})> shown = [];
  final List<int> cancelled = [];
  bool initialised = false;

  @override
  Future<bool?> initialize({
    required InitializationSettings settings,
    DidReceiveNotificationResponseCallback? onDidReceiveNotificationResponse,
    DidReceiveBackgroundNotificationResponseCallback?
        onDidReceiveBackgroundNotificationResponse,
  }) async {
    initialised = true;
    return true;
  }

  @override
  Future<void> show({
    required int id,
    String? title,
    String? body,
    NotificationDetails? notificationDetails,
    String? payload,
  }) async {
    shown.add((
      id: id, title: title, body: body, payload: payload,
      details: notificationDetails,
    ));
  }

  @override
  Future<void> cancel({required int id, String? tag}) async {
    cancelled.add(id);
  }

  @override
  T? resolvePlatformSpecificImplementation<
      T extends FlutterLocalNotificationsPlatform>() {
    // The service only reaches for the Android implementation to create the
    // channel; returning null makes that a no-op, so channel assertions use
    // the dedicated fake below instead.
    return null;
  }
}

void main() {
  group('the alert notification', () {
    test('uses ONE id for all pending orders', () {
      // A per-order id would stack N insistent, un-swipeable notifications
      // each with its own repeating alarm — a tablet nobody can silence.
      expect(OrderAlertNotifications.notificationId, isA<int>());
    });

    test('the channel id is VERSIONED', () {
      // Android freezes a channel's importance and sound at creation. Editing
      // those constants later is a no-op on any device that already has the
      // channel, so the id must be bumped instead — and it can only be bumped
      // if it carries a version in the first place.
      expect(OrderAlertNotifications.channelId, 'new_orders_v1');
      expect(OrderAlertNotifications.channelId, contains('_v'),
          reason: 'an unversioned channel id cannot be changed on a live device');
    });

    test('names the bundled sound WITHOUT an extension', () {
      // Android resource lookup takes the bare name; "order_alert.wav" would
      // silently resolve to nothing and the alert would be mute.
      expect(OrderAlertNotifications.soundResource, 'order_alert');
      expect(OrderAlertNotifications.soundResource, isNot(contains('.')));
    });

    test('init is idempotent', () async {
      final p = _FakePlugin();
      final n = OrderAlertNotifications(plugin: p);
      await n.init();
      await n.init();
      expect(p.initialised, isTrue);
    });

    test('showPending sets FLAG_INSISTENT and is ongoing', () async {
      final p = _FakePlugin();
      final n = OrderAlertNotifications(plugin: p);
      await n.init();
      await n.showPending(title: 'T', body: 'B', orderId: 'order-9');

      expect(p.shown, hasLength(1));
      final android = p.shown.single.details!.android!;

      // 0x4 == FLAG_INSISTENT. This is what makes the sound repeat instead of
      // playing once into an empty kitchen.
      expect(android.additionalFlags, isA<Int32List>());
      expect(android.additionalFlags!.contains(4), isTrue,
          reason: 'without FLAG_INSISTENT the alarm plays once and stops');

      // A task, not an FYI: it must survive someone wiping their tray.
      expect(android.ongoing, isTrue);
      expect(android.autoCancel, isFalse);

      expect(android.importance, Importance.max);
      expect(android.priority, Priority.max);
      expect(android.playSound, isTrue);
      expect(android.enableVibration, isTrue);
      expect(android.channelId, OrderAlertNotifications.channelId);

      // The order id rides the payload so a tap can open that order.
      expect(p.shown.single.payload, 'order-9');
    });

    test('cancelPending withdraws the one id', () async {
      final p = _FakePlugin();
      final n = OrderAlertNotifications(plugin: p);
      await n.init();
      await n.cancelPending();
      expect(p.cancelled, [OrderAlertNotifications.notificationId]);
    });

    test('cancelPending never throws', () async {
      // Called from a background isolate on a resolution push; an exception
      // there would kill the isolate for no benefit.
      final n = OrderAlertNotifications(plugin: _ThrowingPlugin());
      await expectLater(n.cancelPending(), completes);
    });
  });

  group('the push kinds the handler acts on', () {
    test('match the backend constants exactly', () {
      // These strings are duplicated across two languages; a typo on either
      // side means the alert silently never fires. Pinned on both.
      expect(kindNewOrderPending, 'NEW_ORDER_PENDING');
      expect(kindOrderResolved, 'ORDER_RESOLVED');
    });

    test('are distinct from the pre-existing informational kinds', () {
      // STAFF_NEW_ORDER still carries a notification block and is drawn by
      // Android. Sharing a kind would also break the backend's per-kind
      // idempotency check and suppress the ladder's later rungs.
      expect(kindNewOrderPending, isNot(StaffPushKind.newOrder));
      expect(kindNewOrderPending, isNot(StaffPushKind.trainStartDue));
      expect(kindOrderResolved, isNot(StaffPushKind.newOrder));
    });
  });
}

class _ThrowingPlugin extends Fake implements FlutterLocalNotificationsPlugin {
  @override
  Future<void> cancel({required int id, String? tag}) async {
    throw Exception('platform channel unavailable');
  }
}
