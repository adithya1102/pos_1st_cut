/// One owner-defined meal time and the dishes it switches on (migration 043).
///
/// [startTime] and [endTime] are DISPLAY ONLY — the label under the chip. The
/// server does not read them to decide anything and no slot is ever applied
/// because a clock reached one; applying is always an explicit tap. The times
/// that genuinely gate behaviour are the outlet's opening/closing hours
/// (migration 024), which gate whether customers can ORDER at all.
class MealSlot {
  /// One of 'morning', 'afternoon', 'evening', 'night'. The server refuses
  /// anything else with a 422 and the database has a matching CHECK.
  final String slotKey;

  /// 'HH:MM', or null when the owner has not set a range.
  final String? startTime;
  final String? endTime;

  /// The dishes this slot turns on. Empty for a slot that has never been
  /// saved, which is what makes its chip read "Set up" rather than vanish.
  final List<String> itemIds;

  const MealSlot({
    required this.slotKey,
    this.startTime,
    this.endTime,
    this.itemIds = const [],
  });

  /// The four keys, in the order the chips are laid out. Matches
  /// `MEAL_SLOT_KEYS` in the backend schema.
  static const keys = <String>['morning', 'afternoon', 'evening', 'night'];

  /// 'Morning', 'Afternoon', ... for display.
  String get label => switch (slotKey) {
        'morning' => 'Morning',
        'afternoon' => 'Afternoon',
        'evening' => 'Evening',
        'night' => 'Night',
        // Not reachable through the four keys above, and shown verbatim rather
        // than blanked if the server ever grows a fifth.
        _ => slotKey,
      };

  /// True when this slot has no dishes, so it cannot be applied — the server
  /// refuses an empty apply with 422 SLOT_EMPTY rather than turning the whole
  /// menu off, and the chip is disabled for the same reason.
  bool get isEmpty => itemIds.isEmpty;

  /// '7:00 am - 11:00 am', or null when either end is unset.
  String? get rangeLabel {
    final s = _friendly(startTime);
    final e = _friendly(endTime);
    if (s == null || e == null) return null;
    return '$s - $e';
  }

  /// 'HH:MM' (24h) -> '7:00 am'. Null for anything unparseable, so a malformed
  /// value leaves the chip without a range instead of rendering 'null:null'.
  static String? _friendly(String? hhmm) {
    final raw = (hhmm ?? '').trim();
    if (raw.isEmpty) return null;
    final parts = raw.split(':');
    if (parts.length < 2) return null;
    final h = int.tryParse(parts[0]);
    final m = int.tryParse(parts[1]);
    if (h == null || m == null || h < 0 || h > 23 || m < 0 || m > 59) {
      return null;
    }
    final suffix = h < 12 ? 'am' : 'pm';
    final h12 = h % 12 == 0 ? 12 : h % 12;
    return '$h12:${m.toString().padLeft(2, '0')} $suffix';
  }

  factory MealSlot.fromJson(Map<String, dynamic> json) {
    return MealSlot(
      slotKey: (json['slot_key'] as String?) ?? '',
      startTime: _nonEmpty(json['start_time']),
      endTime: _nonEmpty(json['end_time']),
      // `?? const []` rather than a cast: a slot the owner has never saved
      // comes back with an empty list, and an older backend would omit the
      // key entirely. Both read as "no dishes yet".
      itemIds: ((json['item_ids'] as List<dynamic>?) ?? const [])
          .map((e) => e.toString())
          .toList(growable: false),
    );
  }

  static String? _nonEmpty(dynamic value) {
    final s = (value as String?)?.trim();
    return (s == null || s.isEmpty) ? null : s;
  }

  MealSlot copyWith({
    String? startTime,
    String? endTime,
    List<String>? itemIds,
    bool clearTimes = false,
  }) {
    return MealSlot(
      slotKey: slotKey,
      startTime: clearTimes ? null : (startTime ?? this.startTime),
      endTime: clearTimes ? null : (endTime ?? this.endTime),
      itemIds: itemIds ?? this.itemIds,
    );
  }
}

/// What one tap of a slot actually changed, from POST .../apply.
///
/// [skippedOutOfStock] is the one that matters: a dish in the slot that was
/// NOT turned on because it is tracked and sitting at zero. The owner is told
/// rather than discovering it from a customer.
class ApplySlotResult {
  final int turnedOn;
  final int turnedOff;
  final int skippedOutOfStock;

  const ApplySlotResult({
    required this.turnedOn,
    required this.turnedOff,
    required this.skippedOutOfStock,
  });

  factory ApplySlotResult.fromJson(Map<String, dynamic> json) {
    return ApplySlotResult(
      turnedOn: (json['turned_on'] as num?)?.toInt() ?? 0,
      turnedOff: (json['turned_off'] as num?)?.toInt() ?? 0,
      skippedOutOfStock: (json['skipped_out_of_stock'] as num?)?.toInt() ?? 0,
    );
  }

  /// The snackbar line. Mentions the skip only when there was one, so the
  /// common case stays short.
  String get summary {
    final base = '$turnedOn on, $turnedOff off';
    if (skippedOutOfStock == 0) return base;
    return '$base, $skippedOutOfStock skipped (out of stock)';
  }
}
