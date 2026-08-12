import 'package:flutter/material.dart';

import '../theme/app_colors.dart';
import '../theme/app_theme.dart';
import '../theme/widgets/neo_button.dart';

/// Time-of-day bands used to label the arrival picker as the hour scrolls.
///
/// ASSUMED RANGES — reasonable defaults, NOT confirmed with the product owner:
///   Morning    05:00–11:59
///   Afternoon  12:00–16:59
///   Evening    17:00–20:59
///   Night      21:00–04:59  (wraps midnight)
///
/// The wrap is why this is a function over a list of ranges rather than a
/// simple lookup table: Night is the only band that spans the day boundary.
enum DayPart {
  morning('Morning'),
  afternoon('Afternoon'),
  evening('Evening'),
  night('Night');

  const DayPart(this.label);
  final String label;

  /// The band a 24-hour [hour] falls in.
  static DayPart forHour(int hour) {
    final h = hour % 24;
    if (h >= 5 && h <= 11) return DayPart.morning;
    if (h >= 12 && h <= 16) return DayPart.afternoon;
    if (h >= 17 && h <= 20) return DayPart.evening;
    return DayPart.night; // 21-23 and 0-4
  }
}

/// Scrollable arrival-time selector, replacing Flutter's clock-dial
/// `showTimePicker`.
///
/// The dial asks you to think in angles; a train arrival is a number you have
/// been told ("19:42"), so this is two scrolling columns of that number plus a
/// band label that updates live as the hour column moves. The label is what
/// makes a mis-scroll obvious — 07:30 and 19:30 sit far apart on the wheel but
/// read identically at a glance, and only one of them says "Evening".
///
/// Text here is deliberately LIGHTER in weight than the rest of the app, not
/// smaller: a wheel of numbers at the app's usual w700 reads as a wall.
class ArrivalTimePicker extends StatefulWidget {
  const ArrivalTimePicker({
    super.key,
    required this.initial,
    required this.maxAhead,
  });

  /// Where the wheels start. Usually now + a short lead time.
  final DateTime initial;

  /// Arrivals further ahead than this are rejected, matching the caller's own
  /// cap so the sheet cannot return a value the screen would then refuse.
  final Duration maxAhead;

  /// Shows the sheet. Resolves to null if dismissed.
  static Future<DateTime?> show(
    BuildContext context, {
    required DateTime initial,
    required Duration maxAhead,
  }) {
    return showModalBottomSheet<DateTime>(
      context: context,
      isScrollControlled: true,
      backgroundColor: Colors.transparent,
      builder: (_) => ArrivalTimePicker(initial: initial, maxAhead: maxAhead),
    );
  }

  @override
  State<ArrivalTimePicker> createState() => _ArrivalTimePickerState();
}

class _ArrivalTimePickerState extends State<ArrivalTimePicker> {
  late int _hour = widget.initial.hour;
  late int _minute = widget.initial.minute;

  late final FixedExtentScrollController _hourCtrl =
      FixedExtentScrollController(initialItem: _hour);
  late final FixedExtentScrollController _minuteCtrl =
      FixedExtentScrollController(initialItem: _minute);

  @override
  void dispose() {
    _hourCtrl.dispose();
    _minuteCtrl.dispose();
    super.dispose();
  }

  /// The chosen wall-clock time, rolled to tomorrow if it has already passed —
  /// the common case for a late-evening pick just after midnight, not an error.
  DateTime get _resolved {
    final now = DateTime.now();
    var when = DateTime(now.year, now.month, now.day, _hour, _minute);
    if (when.isBefore(now)) when = when.add(const Duration(days: 1));
    return when;
  }

  bool get _tooFar => _resolved.difference(DateTime.now()) > widget.maxAhead;

  @override
  Widget build(BuildContext context) {
    final c = AppColors.of(context);
    final textTheme = Theme.of(context).textTheme;
    final part = DayPart.forHour(_hour);

    return Container(
      decoration: BoxDecoration(
        color: c.background,
        borderRadius: const BorderRadius.vertical(top: Radius.circular(20)),
        border: Border(top: BorderSide(color: c.border, width: 3)),
      ),
      padding: const EdgeInsets.fromLTRB(20, 14, 20, 20),
      child: SafeArea(
        top: false,
        child: Column(
          mainAxisSize: MainAxisSize.min,
          children: [
            Container(
              width: 46,
              height: 5,
              decoration: BoxDecoration(
                color: c.inkSoft,
                borderRadius: BorderRadius.circular(3),
              ),
            ),
            const SizedBox(height: 16),
            Text(
              'When does your train arrive?',
              style: textTheme.titleLarge?.copyWith(fontWeight: FontWeight.w500),
            ),
            const SizedBox(height: 4),
            // The live band label. Updates on every hour tick, so the wheel
            // always says what part of the day it is pointing at.
            Text(
              key: const Key('arrival_day_part'),
              part.label,
              style: textTheme.titleMedium?.copyWith(
                color: AppColors.brand,
                fontWeight: FontWeight.w400,
                letterSpacing: 2,
              ),
            ),
            const SizedBox(height: 14),
            SizedBox(
              height: 190,
              child: Stack(
                children: [
                  // Selection band behind the wheels.
                  Center(
                    child: Container(
                      height: 46,
                      decoration: BoxDecoration(
                        color: c.accent,
                        borderRadius: BorderRadius.circular(AppTheme.radius - 4),
                        border: Border.all(color: c.border, width: 2),
                      ),
                    ),
                  ),
                  Row(
                    children: [
                      Expanded(
                        child: _Wheel(
                          key: const Key('arrival_hour_wheel'),
                          controller: _hourCtrl,
                          count: 24,
                          format: (i) => i.toString().padLeft(2, '0'),
                          onChanged: (i) => setState(() => _hour = i),
                        ),
                      ),
                      Text(
                        ':',
                        style: textTheme.headlineSmall
                            ?.copyWith(fontWeight: FontWeight.w300),
                      ),
                      Expanded(
                        child: _Wheel(
                          key: const Key('arrival_minute_wheel'),
                          controller: _minuteCtrl,
                          count: 60,
                          format: (i) => i.toString().padLeft(2, '0'),
                          onChanged: (i) => setState(() => _minute = i),
                        ),
                      ),
                    ],
                  ),
                ],
              ),
            ),
            const SizedBox(height: 14),
            if (_tooFar) ...[
              Text(
                'Pick a time within the next ${widget.maxAhead.inHours} hours.',
                key: const Key('arrival_too_far'),
                textAlign: TextAlign.center,
                style: textTheme.bodyMedium?.copyWith(color: AppColors.tomato),
              ),
              const SizedBox(height: 10),
            ],
            NeoButton(
              key: const Key('arrival_confirm'),
              label: 'Set arrival time',
              icon: Icons.check,
              onPressed:
                  _tooFar ? null : () => Navigator.of(context).pop(_resolved),
            ),
          ],
        ),
      ),
    );
  }
}

/// One scrolling column. Lighter weight than the app's usual type, and the
/// off-centre rows fade so the selected value is unambiguous.
class _Wheel extends StatelessWidget {
  const _Wheel({
    super.key,
    required this.controller,
    required this.count,
    required this.format,
    required this.onChanged,
  });

  final FixedExtentScrollController controller;
  final int count;
  final String Function(int) format;
  final ValueChanged<int> onChanged;

  @override
  Widget build(BuildContext context) {
    final c = AppColors.of(context);
    return ListWheelScrollView.useDelegate(
      controller: controller,
      itemExtent: 46,
      physics: const FixedExtentScrollPhysics(),
      onSelectedItemChanged: onChanged,
      childDelegate: ListWheelChildBuilderDelegate(
        childCount: count,
        builder: (context, i) => Center(
          child: Text(
            format(i),
            style: Theme.of(context).textTheme.headlineSmall?.copyWith(
                  // w300 — thinner, not smaller. A wheel of numbers at the
                  // app's usual w700 reads as a wall of ink.
                  fontWeight: FontWeight.w300,
                  color: c.ink,
                ),
          ),
        ),
      ),
    );
  }
}
