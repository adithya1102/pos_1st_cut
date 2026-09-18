import 'package:flutter/material.dart';

import '../theme/app_colors.dart';
import '../theme/app_theme.dart';
import '../theme/widgets/neo_button.dart';

/// Time-of-day bands used to label arrival and pickup times.
///
/// CONFIRMED RANGES (these replaced the earlier assumed ones, which had no
/// Midnight band at all and ran Evening to 20:59):
///   Midnight   00:00–04:59
///   Morning    05:00–11:59
///   Afternoon  12:00–15:59
///   Evening    16:00–18:59
///   Night      19:00–23:59
///
/// No band wraps the day boundary any more — Midnight owns the small hours
/// outright, so this is a straight ascending ladder. That is the whole reason
/// Midnight exists: "12:00 AM (Night)" was the one label that could still be
/// read as tonight when it meant the early hours of tomorrow.
enum DayPart {
  midnight('Midnight'),
  morning('Morning'),
  afternoon('Afternoon'),
  evening('Evening'),
  night('Night');

  const DayPart(this.label);
  final String label;

  /// The band a 24-hour [hour] falls in.
  static DayPart forHour(int hour) {
    final h = hour % 24;
    if (h <= 4) return DayPart.midnight;    // 00:00–04:59
    if (h <= 11) return DayPart.morning;    // 05:00–11:59
    if (h <= 15) return DayPart.afternoon;  // 12:00–15:59
    if (h <= 18) return DayPart.evening;    // 16:00–18:59
    return DayPart.night;                   // 19:00–23:59
  }
}

/// "2:00 PM (Afternoon)" — the 12-hour clock plus the band that disambiguates it.
///
/// The parenthesised band is the point: on a 12-hour clock 12:00 AM and 12:00 PM
/// are one character apart and mean opposite ends of the day, which is exactly
/// the pair a customer is most likely to mis-set when scheduling a pickup. The
/// AM/PM is kept rather than replaced because that is the form the rest of the
/// app — and the phone's own locale formatting — already speaks.
String formatWithDayPart(BuildContext context, TimeOfDay time) =>
    '${time.format(context)} (${DayPart.forHour(time.hour).label})';

/// Convenience for the common case of formatting a [DateTime].
String formatDateTimeWithDayPart(BuildContext context, DateTime when) =>
    formatWithDayPart(context, TimeOfDay.fromDateTime(when));

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
  /// The vehicle the heading names ("train", "metro").
  ///
  /// Defaults to 'train' so every existing caller is unchanged. It exists
  /// because the sheet used to hardcode "train" while the page that opens it
  /// names the mode the customer actually picked — so choosing Metro read
  /// "When does your metro arrive?" on the page and "…your train arrive?" the
  /// instant you tapped it. Two names for one journey, one tap apart.
  const ArrivalTimePicker({
    super.key,
    required this.initial,
    required this.maxAhead,
    this.vehicleNoun = 'train',
    this.latest,
    this.minAhead = Duration.zero,
    this.title,
    this.confirmLabel = 'Set arrival time',
  });

  /// Where the wheels start. Usually now + a short lead time.
  final DateTime initial;

  /// Arrivals further ahead than this are rejected, matching the caller's own
  /// cap so the sheet cannot return a value the screen would then refuse.
  ///
  /// Superseded by [latest] when that is supplied. Kept because the declared-
  /// arrival callers genuinely think in "within the next 6 hours", while
  /// scheduled pickup thinks in "before this restaurant closes" — a duration
  /// and an instant, and forcing either into the other's shape loses meaning.
  final Duration maxAhead;

  /// See the note on the constructor. 'train' | 'metro'.
  final String vehicleNoun;

  /// Hard upper bound as an ABSOLUTE instant. Wins over [maxAhead].
  ///
  /// Absolute rather than a duration because scheduled pickup's ceiling is the
  /// outlet's closing time, and that has to survive the roll-to-tomorrow below.
  /// An outlet whose window crosses midnight (18:00 -> 02:00) legitimately
  /// accepts a 00:30 pickup: by the calendar that is tomorrow, by the
  /// restaurant's own day it is tonight. Expressing the cap as an instant makes
  /// that one comparison instead of a special case.
  final DateTime? latest;

  /// Minimum lead time. A pick closer than this is refused rather than silently
  /// accepted and then released immediately by the server.
  final Duration minAhead;

  /// Overrides the "When does your train arrive?" heading. Scheduled pickup is
  /// not asking about a vehicle at all.
  final String? title;

  final String confirmLabel;

  /// Shows the sheet. Resolves to null if dismissed.
  static Future<DateTime?> show(
    BuildContext context, {
    required DateTime initial,
    required Duration maxAhead,
    String vehicleNoun = 'train',
    DateTime? latest,
    Duration minAhead = Duration.zero,
    String? title,
    String confirmLabel = 'Set arrival time',
  }) {
    return showModalBottomSheet<DateTime>(
      context: context,
      isScrollControlled: true,
      backgroundColor: Colors.transparent,
      builder: (_) => ArrivalTimePicker(
        initial: initial,
        maxAhead: maxAhead,
        vehicleNoun: vehicleNoun,
        latest: latest,
        minAhead: minAhead,
        title: title,
        confirmLabel: confirmLabel,
      ),
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
  ///
  /// The roll is kept for scheduled pickup too, and deliberately: an outlet
  /// open 18:00 -> 02:00 is still having "today" at 00:30. What stops that
  /// becoming an accidental booking for tomorrow lunchtime is [_latestAllowed]
  /// below, not a ban on rolling — a rolled time simply fails the ceiling
  /// unless the restaurant is genuinely still open then.
  DateTime get _resolved {
    final now = DateTime.now();
    var when = DateTime(now.year, now.month, now.day, _hour, _minute);
    if (when.isBefore(now)) when = when.add(const Duration(days: 1));
    return when;
  }

  /// The ceiling, as an instant. An explicit [latest] wins; otherwise the
  /// caller's duration cap is projected from now.
  DateTime get _latestAllowed =>
      widget.latest ?? DateTime.now().add(widget.maxAhead);

  bool get _tooFar => _resolved.isAfter(_latestAllowed);

  bool get _tooSoon =>
      _resolved.difference(DateTime.now()) < widget.minAhead;

  /// "10:30 pm" — the same 12-hour shape the outlet card's hours line uses, so
  /// a customer comparing the two is not reading two clocks.
  static String _clock(DateTime t) {
    final suffix = t.hour < 12 ? 'am' : 'pm';
    final h = t.hour % 12 == 0 ? 12 : t.hour % 12;
    return '$h:${t.minute.toString().padLeft(2, '0')} $suffix';
  }

  /// "45 minutes" / "2 hours" / "1 hour 30 minutes". Replaces the old
  /// `maxAhead.inHours` interpolation, which rendered any sub-hour bound as
  /// "within the next 0 hours" — advice that cannot be followed.
  static String _spell(Duration d) {
    final total = d.inMinutes;
    if (total < 60) return '$total minute${total == 1 ? '' : 's'}';
    final h = total ~/ 60;
    final m = total % 60;
    final hours = '$h hour${h == 1 ? '' : 's'}';
    if (m == 0) return hours;
    return '$hours $m minute${m == 1 ? '' : 's'}';
  }

  @override
  Widget build(BuildContext context) {
    final c = AppColors.of(context);
    final textTheme = Theme.of(context).textTheme;

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
              widget.title ?? 'When does your ${widget.vehicleNoun} arrive?',
              textAlign: TextAlign.center,
              style: textTheme.titleLarge?.copyWith(fontWeight: FontWeight.w500),
            ),
            const SizedBox(height: 4),
            // The live label. Updates on every tick, so the wheel always says
            // both what time it is pointing at and what part of the day that
            // is. The wheels themselves are 24-hour (00–23), which is
            // unambiguous but not how anyone says a time out loud — this line
            // is where the selection is echoed back in the 12-hour form the
            // customer will actually recognise on their own clock.
            Text(
              key: const Key('arrival_day_part'),
              formatWithDayPart(
                  context, TimeOfDay(hour: _hour, minute: _minute)),
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
                // Names the actual boundary rather than a duration. For a
                // scheduled pickup that boundary IS the restaurant's closing
                // time, which is the one fact that makes the refusal make
                // sense; for a train it still reads naturally.
                'Pick a time before ${_clock(_latestAllowed)}.',
                key: const Key('arrival_too_far'),
                textAlign: TextAlign.center,
                style: textTheme.bodyMedium?.copyWith(color: AppColors.tomato),
              ),
              const SizedBox(height: 10),
            ] else if (_tooSoon) ...[
              Text(
                'Pick a time at least ${_spell(widget.minAhead)} from now.',
                key: const Key('arrival_too_soon'),
                textAlign: TextAlign.center,
                style: textTheme.bodyMedium?.copyWith(color: AppColors.tomato),
              ),
              const SizedBox(height: 10),
            ],
            NeoButton(
              key: const Key('arrival_confirm'),
              label: widget.confirmLabel,
              icon: Icons.check,
              onPressed: (_tooFar || _tooSoon)
                  ? null
                  : () => Navigator.of(context).pop(_resolved),
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
