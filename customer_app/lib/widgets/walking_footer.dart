import 'dart:async';
import 'dart:math' as math;
import 'dart:ui' as ui;

import 'package:flutter/material.dart';
import 'package:flutter/services.dart' show rootBundle;

/// The walking CareVo figure at the foot of Home.
///
/// Decorative only: it draws the walk-cycle art and nothing else. It carries no
/// text, reads no customer state, and has no configuration.
///
/// ## Why the codec is stepped by hand rather than left to `Image.asset`
///
/// This GIF's frames do not share a duration — 23 run at 60ms and 47 at 70ms.
/// Stepping the codec honours each frame's own delay, so the cycle plays at the
/// cadence it was authored at.
class WalkingFooter extends StatefulWidget {
  const WalkingFooter({super.key});

  static const String asset = 'assets/animation/final_walk.gif';

  /// Native size of the GIF. The rendered box always keeps this ratio.
  static const double gifWidth = 400;
  static const double gifHeight = 623;
  static const double aspect = gifWidth / gifHeight;

  /// Tallest the figure is allowed to draw, in logical pixels.
  ///
  /// The art is portrait (623:400), so sizing it by the full screen width
  /// would make it about 1.6 screen-widths tall — a footer that is taller than
  /// the page it sits under. Height is capped and the width follows the ratio;
  /// on a narrower screen the width constraint takes over instead. Either way
  /// the ratio is preserved and the art is never stretched.
  static const double maxHeight = 260;

  /// Key on the box the art is drawn into. The box keeps its size before the
  /// first frame decodes, so Home does not jump when the figure appears.
  @visibleForTesting
  static const Key frameKey = Key('walking_footer_frame');

  @override
  State<WalkingFooter> createState() => _WalkingFooterState();
}

class _WalkingFooterState extends State<WalkingFooter> {
  ui.Codec? _codec;
  ui.Image? _image;
  bool _stopped = false;

  /// The inter-frame delay in flight, held so it can be cancelled.
  ///
  /// A bare `Future.delayed` would keep ticking for up to a frame after the
  /// widget is gone; a test tears the tree down and then trips on the timer
  /// that outlived it.
  Timer? _tick;
  Completer<void>? _tickDone;

  @override
  void initState() {
    super.initState();
    unawaited(_startPlayback());
  }

  @override
  void dispose() {
    _stopped = true;
    _tick?.cancel();
    // Release the loop so it can observe _stopped and fall out, rather than
    // parking forever on a delay that will now never fire.
    if (_tickDone?.isCompleted == false) _tickDone!.complete();
    _image?.dispose();
    _codec?.dispose();
    super.dispose();
  }

  Future<void> _waitFrame(Duration d) {
    final done = Completer<void>();
    _tickDone = done;
    _tick = Timer(d, () {
      if (!done.isCompleted) done.complete();
    });
    return done.future;
  }

  Future<void> _startPlayback() async {
    try {
      final data = await rootBundle.load(WalkingFooter.asset);
      if (_stopped) return;
      final codec = await ui.instantiateImageCodec(
        data.buffer.asUint8List(),
      );
      if (_stopped) {
        codec.dispose();
        return;
      }
      _codec = codec;

      while (!_stopped) {
        final info = await codec.getNextFrame();
        if (_stopped) {
          info.image.dispose();
          return;
        }
        final previous = _image;
        setState(() => _image = info.image);
        previous?.dispose();
        // Each frame carries its own delay — this GIF's are not uniform.
        await _waitFrame(
          info.duration == Duration.zero
              ? const Duration(milliseconds: 66)
              : info.duration,
        );
      }
    } catch (e) {
      // A decorative footer must never take down Home. If the asset is missing
      // or undecodable the figure simply does not appear.
      debugPrint('WalkingFooter: playback stopped: $e');
    }
  }

  @override
  Widget build(BuildContext context) {
    return LayoutBuilder(
      builder: (context, constraints) {
        final available = constraints.maxWidth.isFinite
            ? constraints.maxWidth
            : WalkingFooter.gifWidth;
        // Height-capped, width-derived — see [WalkingFooter.maxHeight].
        final width = math.min(
          available,
          WalkingFooter.maxHeight * WalkingFooter.aspect,
        );
        final height = width / WalkingFooter.aspect;

        return Center(
          child: SizedBox(
            key: WalkingFooter.frameKey,
            width: width,
            height: height,
            child: _image == null
                ? null
                : RawImage(
                    image: _image,
                    // The box already carries the native ratio, so filling it
                    // is exactly "do not stretch".
                    fit: BoxFit.fill,
                    isAntiAlias: true,
                  ),
          ),
        );
      },
    );
  }
}
