import 'package:flutter/foundation.dart';
import 'package:flutter_local_notifications/flutter_local_notifications.dart';

/// The insistent "accept this order" notification (backend migration 032).
///
/// ## Why a LOCAL notification and not an FCM one
///
/// The server sends the acceptance alert DATA-ONLY, with no `notification`
/// block. Per Firebase's documentation a message carrying that block is
/// rendered by the Android system tray and the Dart background handler is NOT
/// invoked for it while the app is backgrounded or killed — the handler only
/// runs for data-only messages. Everything insistent about this alert needs
/// code to run:
///
///   * `ongoing: true` + `autoCancel: false`, so it cannot be swiped away by
///     someone clearing their tray without dealing with the order;
///   * FLAG_INSISTENT, so the sound repeats until it is dismissed rather than
///     playing once into an empty kitchen;
///   * and crucially CANCELLATION, when the order is settled on another
///     device. A system-rendered notification cannot be withdrawn by us.
///
/// ## The channel
///
/// Created at `Importance.max` with the bundled sound. On Android 8+ a
/// channel's importance and sound are FROZEN at creation: changing these
/// constants later has no effect on a device that already has the channel, and
/// the only remedies are a new channel id or a reinstall. So [channelId]
/// carries a version suffix — bump it rather than editing the settings in
/// place, or the change will appear to work in development (fresh install) and
/// silently not work for every existing restaurant.
class OrderAlertNotifications {
  OrderAlertNotifications({FlutterLocalNotificationsPlugin? plugin})
      : _plugin = plugin ?? FlutterLocalNotificationsPlugin();

  final FlutterLocalNotificationsPlugin _plugin;

  /// Versioned — see the class docstring. `_v1` is not decoration.
  static const String channelId = 'new_orders_v1';
  static const String channelName = 'New orders';
  static const String channelDescription =
      'Alerts that a paid order is waiting for you to accept it.';

  /// The synthesized beep at android/app/src/main/res/raw/order_alert.wav.
  /// Named WITHOUT its extension, which is how Android resource lookup works.
  static const String soundResource = 'order_alert';

  /// One notification id for ALL pending orders, deliberately.
  ///
  /// A per-order id would mean three unanswered orders stack three insistent,
  /// un-swipeable notifications, each with its own repeating alarm — which is
  /// not three times as useful, it is a tablet nobody can silence. Re-posting
  /// the same id replaces the previous one, so the tray always shows exactly
  /// one "orders need accepting" alert.
  static const int notificationId = 7001;

  bool _initialised = false;

  /// Idempotent. Safe to call from both `main()` and the background isolate,
  /// which have separate memory and therefore separate `_initialised` flags.
  Future<void> init({
    void Function(NotificationResponse)? onTap,
  }) async {
    if (_initialised) return;
    const android = AndroidInitializationSettings('@mipmap/ic_launcher');
    // v22 moved every one of these to NAMED parameters.
    await _plugin.initialize(
      settings: const InitializationSettings(android: android),
      onDidReceiveNotificationResponse: onTap,
    );

    // Created explicitly rather than left to the first notification, so the
    // channel exists (and is visible in system settings) before any order
    // arrives. Importance.max is what allows a heads-up banner at all.
    await _plugin
        .resolvePlatformSpecificImplementation<
            AndroidFlutterLocalNotificationsPlugin>()
        ?.createNotificationChannel(const AndroidNotificationChannel(
          channelId,
          channelName,
          description: channelDescription,
          importance: Importance.max,
          playSound: true,
          sound: RawResourceAndroidNotificationSound(soundResource),
          enableVibration: true,
          // A long, uneven pattern. A short buzz is indistinguishable from any
          // other notification in an apron pocket.
          vibrationPattern: null,
        ));
    _initialised = true;
  }

  /// Raise (or replace) the pending-order alert.
  Future<void> showPending({
    required String title,
    required String body,
    String? orderId,
  }) async {
    await _plugin.show(
      id: notificationId,
      title: title,
      body: body,
      notificationDetails: NotificationDetails(
        android: AndroidNotificationDetails(
          channelId,
          channelName,
          channelDescription: channelDescription,
          importance: Importance.max,
          priority: Priority.max,
          // ONGOING + no auto-cancel: this is a task, not an FYI. It goes away
          // when the order is dealt with, not when someone wipes their tray.
          ongoing: true,
          autoCancel: false,
          playSound: true,
          sound: const RawResourceAndroidNotificationSound(soundResource),
          enableVibration: true,
          // FLAG_INSISTENT (0x00000004). Repeats the sound until the
          // notification is cancelled or dismissed. Not exposed as a named
          // parameter by the plugin, so it is set as a raw flag — the same
          // mechanism an alarm clock uses, and the reason this alert can be
          // heard from a different room.
          additionalFlags: Int32List.fromList(<int>[4]),
          category: AndroidNotificationCategory.call,
          visibility: NotificationVisibility.public,
          ticker: 'Order waiting',
        ),
      ),
      payload: orderId,
    );
  }

  /// Withdraw it. Called on `order_resolved`, which the server sends to the
  /// whole outlet precisely so the OTHER devices stop ringing.
  Future<void> cancelPending() async {
    try {
      await _plugin.cancel(id: notificationId);
    } catch (e) {
      if (kDebugMode) debugPrint('cancelPending: $e');
    }
  }

  /// Android 13+ runtime notification permission.
  ///
  /// Returns false when it was refused, which the caller should surface rather
  /// than swallow: on this app a refused notification permission means orders
  /// expire unanswered, so it is not a cosmetic degradation.
  Future<bool> requestPermission() async {
    final android = _plugin.resolvePlatformSpecificImplementation<
        AndroidFlutterLocalNotificationsPlugin>();
    if (android == null) return true;
    return await android.requestNotificationsPermission() ?? false;
  }
}
