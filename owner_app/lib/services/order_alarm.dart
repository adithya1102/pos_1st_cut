import 'dart:async';

import 'package:audioplayers/audioplayers.dart';
import 'package:flutter/foundation.dart';
import 'package:flutter/services.dart';

/// The looping in-app alarm for an order awaiting acceptance.
///
/// Distinct from [AlertFeedback], which is the one-shot chime for a NEW order
/// arriving in auto mode. That one announces something; this one DEMANDS
/// something, and it keeps going until the server state changes — because an
/// unanswered order is cancelled and refunded, so a single chime that nobody
/// happened to hear costs a real sale.
///
/// ## Why the alarm AUDIO stream and not the notification stream
///
/// `AudioContext` is set to the alarm usage, which means the tone follows the
/// device's ALARM volume rather than its notification volume and is NOT
/// silenced by Do Not Disturb on most Android builds. A kitchen tablet
/// routinely sits on silent with DND on overnight; a notification-stream sound
/// on such a device is simply inaudible, which would make this feature look
/// like it works in testing and fail in a restaurant.
///
/// ## Why it is a timer and not a looping player
///
/// ReleaseMode.loop would play the clip back-to-back with no gap, which reads
/// as a drone and is easy to tune out. The clip already carries its own
/// trailing silence, and re-triggering it on a timer also lets the VIBRATION
/// fire in step with each beep — a player loop gives no hook for that.
class OrderAlarm {
  OrderAlarm({AudioPlayer? player, this.interval = const Duration(seconds: 2)})
      : _player = player ?? AudioPlayer();

  final AudioPlayer _player;

  /// Gap between repeats. The clip is ~0.83s, so two seconds leaves an audible
  /// pause — a continuous noise is what people learn to ignore.
  final Duration interval;

  Timer? _timer;
  bool _configured = false;

  bool get isRinging => _timer != null;

  /// Start, or do nothing if already ringing.
  ///
  /// Idempotent on purpose: the modal may rebuild several times for one pending
  /// order (a poll tick, a countdown rebuild), and restarting the alarm on each
  /// rebuild would retrigger the tone every few hundred milliseconds.
  Future<void> start() async {
    if (_timer != null) return;
    await _configure();
    await _beep();
    _timer = Timer.periodic(interval, (_) => _beep());
  }

  /// Stop and release. Safe to call when not ringing.
  Future<void> stop() async {
    _timer?.cancel();
    _timer = null;
    try {
      await _player.stop();
    } catch (e) {
      if (kDebugMode) debugPrint('OrderAlarm.stop: $e');
    }
  }

  Future<void> dispose() async {
    await stop();
    try {
      await _player.dispose();
    } catch (_) {}
  }

  Future<void> _configure() async {
    if (_configured) return;
    try {
      await _player.setAudioContext(AudioContext(
        android: const AudioContextAndroid(
          isSpeakerphoneOn: true,
          stayAwake: true,
          contentType: AndroidContentType.sonification,
          // THE load-bearing line. See the class docstring: alarm usage routes
          // to the alarm volume and survives DND.
          usageType: AndroidUsageType.alarm,
          audioFocus: AndroidAudioFocus.gainTransientMayDuck,
        ),
        iOS: AudioContextIOS(
          category: AVAudioSessionCategory.playback,
          options: const {AVAudioSessionOptions.defaultToSpeaker},
        ),
      ));
      await _player.setReleaseMode(ReleaseMode.stop);
      _configured = true;
    } catch (e) {
      // A device that refuses the audio context must still vibrate, and the
      // modal must still appear. Never fatal.
      if (kDebugMode) debugPrint('OrderAlarm._configure: $e');
    }
  }

  Future<void> _beep() async {
    // Sound and vibration fire INDEPENDENTLY, so a device that refuses one
    // still produces the other — a muted tablet still buzzes, and a tablet
    // with no vibration motor still chimes.
    try {
      await _player.play(AssetSource('audio/order_alert.wav'));
    } catch (e) {
      if (kDebugMode) debugPrint('OrderAlarm tone: $e');
    }
    try {
      // heavyImpact rather than vibrate(): this has to be felt through an
      // apron pocket in a noisy kitchen, not politely ticked.
      await HapticFeedback.heavyImpact();
    } catch (e) {
      if (kDebugMode) debugPrint('OrderAlarm haptic: $e');
    }
  }
}
