// Home's walking-figure footer.
//
// The footer is decorative: it draws the walk cycle and nothing else. What
// needs pinning is that the art actually appears, that it keeps playing round
// the loop, that it holds its shape at any screen width, and that it stays
// independent of app state.
//
// Unlike the earlier version of this file, these tests decode the real GIF.
// There is no test seam to drive instead — the frame index is no longer
// observable from outside, because nothing is positioned against it.
import 'dart:ui' as ui;

import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';

import 'package:customer_app/widgets/walking_footer.dart';

Widget _host({double width = 400}) => MaterialApp(
      home: Scaffold(
        body: Center(
          child: SizedBox(width: width, child: const WalkingFooter()),
        ),
      ),
    );

/// The decoded frame currently on screen, or null before the first one lands.
ui.Image? _currentFrame(WidgetTester tester) {
  final f = find.byType(RawImage);
  if (f.evaluate().isEmpty) return null;
  return tester.widget<RawImage>(f).image;
}

/// Let real time pass so the asset load and first decode actually run — pumps
/// cannot drive those, they are real I/O rather than timers.
Future<void> _realWait(WidgetTester tester, Duration d) async {
  await tester.runAsync(() => Future<void>.delayed(d));
  await tester.pump();
}

/// Step [n] frames on.
///
/// Playback starts in `initState`, so its inter-frame `Timer` belongs to the
/// test's fake-async zone and only fires when the test clock is advanced —
/// real waiting will not move it. Each step therefore pumps the clock past the
/// frame delay, then gives the real decode that follows a moment to land.
Future<void> _advanceFrames(WidgetTester tester, int n) async {
  for (var i = 0; i < n; i++) {
    await tester.pump(const Duration(milliseconds: 80));
    await tester.runAsync(
        () => Future<void>.delayed(const Duration(milliseconds: 15)));
    await tester.pump();
  }
}

Size _frameBox(WidgetTester tester) =>
    tester.getSize(find.byKey(WalkingFooter.frameKey));

void main() {
  // =========================================================================
  // the art on screen
  // =========================================================================
  group('playback', () {
    testWidgets('renders the walking figure once the first frame decodes',
        (tester) async {
      await tester.pumpWidget(_host());
      await _realWait(tester, const Duration(seconds: 2));

      expect(find.byType(RawImage), findsOneWidget);
      expect(_currentFrame(tester), isNotNull);
    });

    testWidgets('holds its box BEFORE the first frame — Home must not jump',
        (tester) async {
      await tester.pumpWidget(_host());
      await tester.pump();

      // Sized from the start, but nothing drawn into it yet.
      final box = _frameBox(tester);
      expect(box.width, greaterThan(0));
      expect(box.width / box.height, closeTo(WalkingFooter.aspect, 0.001));

      await _realWait(tester, const Duration(seconds: 2));

      // Same box once the art arrives — the layout never changed size.
      expect(_frameBox(tester), box);
    });

    testWidgets('the animation ADVANCES — a frozen first frame would defeat it',
        (tester) async {
      await tester.pumpWidget(_host());
      await _realWait(tester, const Duration(seconds: 2));
      final first = _currentFrame(tester);
      expect(first, isNotNull);

      await _advanceFrames(tester, 3);
      final later = _currentFrame(tester);

      expect(later, isNotNull);
      expect(identical(first, later), isFalse,
          reason: 'the frame on screen should have swapped by now');
    });

    testWidgets('LOOPS — still playing after a full cycle has elapsed',
        (tester) async {
      await tester.pumpWidget(_host());
      await _realWait(tester, const Duration(seconds: 2));

      // The clip is 70 frames. Stepping past that wraps the codec back to the
      // start at least once — the point where a non-looping decoder would stall.
      await _advanceFrames(tester, 75);
      final afterWrap = _currentFrame(tester);
      expect(afterWrap, isNotNull, reason: 'playback stalled at the loop point');

      await _advanceFrames(tester, 3);
      expect(identical(afterWrap, _currentFrame(tester)), isFalse,
          reason: 'still advancing after the wrap, not stuck on a last frame');

      expect(tester.takeException(), isNull);
    });

    testWidgets('disposing mid-playback stops cleanly', (tester) async {
      await tester.pumpWidget(_host());
      await _realWait(tester, const Duration(milliseconds: 300));

      // Navigate the footer away while the decode loop is mid-flight.
      await tester.pumpWidget(const MaterialApp(home: Scaffold(body: Text('x'))));
      await _realWait(tester, const Duration(milliseconds: 400));

      expect(find.byType(WalkingFooter), findsNothing);
      expect(tester.takeException(), isNull);
    });
  });

  // =========================================================================
  // it is decoration, not UI
  // =========================================================================
  group('independence from app state', () {
    testWidgets('needs no AuthState — no provider in the tree at all',
        (tester) async {
      // Deliberately hosted without ChangeNotifierProvider. Before the letter
      // was removed this threw ProviderNotFoundException.
      await tester.pumpWidget(_host());
      await _realWait(tester, const Duration(seconds: 2));

      expect(find.byType(WalkingFooter), findsOneWidget);
      expect(tester.takeException(), isNull);
    });

    testWidgets('draws NO text — the figure carries no letter', (tester) async {
      await tester.pumpWidget(_host());
      await _realWait(tester, const Duration(seconds: 2));

      expect(
        find.descendant(
          of: find.byType(WalkingFooter),
          matching: find.byType(Text),
        ),
        findsNothing,
      );
    });
  });

  // =========================================================================
  // sizing
  // =========================================================================
  group('responsive sizing', () {
    testWidgets('keeps the native aspect ratio and never stretches',
        (tester) async {
      for (final w in <double>[320, 400, 800]) {
        await tester.pumpWidget(_host(width: w));
        await tester.pump();

        final rendered = _frameBox(tester);
        expect(rendered.width / rendered.height,
            closeTo(WalkingFooter.aspect, 0.001),
            reason: 'ratio must hold at width $w');
        expect(rendered.height, lessThanOrEqualTo(WalkingFooter.maxHeight + 0.5),
            reason: 'the footer must not grow taller than its cap at width $w');
      }
    });

    testWidgets('a wide screen is capped by height, not filled by width',
        (tester) async {
      await tester.pumpWidget(_host(width: 800));
      await tester.pump();

      final rendered = _frameBox(tester);
      expect(rendered.height, closeTo(WalkingFooter.maxHeight, 0.5));
      expect(rendered.width, lessThan(800));
    });

    testWidgets('narrow screens shrink by width instead of overflowing',
        (tester) async {
      await tester.pumpWidget(_host(width: 90));
      await tester.pump();

      final rendered = _frameBox(tester);
      expect(rendered.width, lessThanOrEqualTo(90.0));
      expect(rendered.width / rendered.height,
          closeTo(WalkingFooter.aspect, 0.001));
      expect(tester.takeException(), isNull);
    });

    testWidgets('the decoded art fills the box exactly — no letterboxing',
        (tester) async {
      await tester.pumpWidget(_host());
      await _realWait(tester, const Duration(seconds: 2));

      final raw = tester.widget<RawImage>(find.byType(RawImage));
      expect(raw.fit, BoxFit.fill);
      expect(tester.getSize(find.byType(RawImage)), _frameBox(tester));
    });
  });
}
