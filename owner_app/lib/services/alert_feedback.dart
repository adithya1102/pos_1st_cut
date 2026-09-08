import 'package:flutter/foundation.dart';
import 'package:flutter/services.dart';

/// Sound + vibration for the IN-APP new-order alert.
///
/// This is not a notification and has nothing to do with Firebase. It fires
/// only while the app is on screen; delivery to a backgrounded or closed app is
/// the push path's job and is deliberately untouched here.
///
/// Built on Flutter's own platform services rather than an audio/vibration
/// package on purpose: [SystemSound] and [HapticFeedback] already ride the
/// engine channel, so this adds no dependency, no per-platform setup and no
/// asset. Both degrade to a no-op on hardware that cannot do them, which is
/// exactly the "if the device supports it" behaviour wanted — a phone with no
/// vibration motor still chimes, and a muted phone still buzzes.
class AlertFeedback {
  const AlertFeedback();

  /// Chime and buzz for one newly-arrived order.
  ///
  /// Never throws. An owner whose device refuses one of these must still see
  /// the banner: the alert is the message, this is only its loudness.
  Future<void> newOrder() async {
    // Fired as two independent calls rather than one awaited chain, so a
    // platform that rejects the sound cannot also swallow the vibration.
    await Future.wait([_chime(), _buzz()]);
  }

  Future<void> _chime() async {
    try {
      await SystemSound.play(SystemSoundType.alert);
    } catch (e) {
      if (kDebugMode) debugPrint('AlertFeedback._chime: $e');
    }
  }

  Future<void> _buzz() async {
    try {
      // heavyImpact over vibrate(): a counter phone in a noisy kitchen needs
      // this to be felt through an apron pocket, not a polite tick.
      await HapticFeedback.heavyImpact();
    } catch (e) {
      if (kDebugMode) debugPrint('AlertFeedback._buzz: $e');
    }
  }
}
