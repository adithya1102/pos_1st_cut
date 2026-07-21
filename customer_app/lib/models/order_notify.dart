/// A one-directional "notify" push sent by staff over the order WebSocket.
///
/// Wire shape (only `event == "notify"` messages are parsed into this):
/// ```json
/// {"event":"notify","order_id":"<uuid>","type":"ready_now"|"delayed_10"
///  |"item_unavailable","item_id":<uuid|null>,"item_name":<str|null>,
///  "message":"<text>","ts":"<iso>"}
/// ```
class OrderNotify {
  const OrderNotify({
    required this.type,
    this.itemName,
    this.message,
    this.ts,
  });

  final String type;
  final String? itemName;
  final String? message;
  final String? ts;

  static const ready = 'ready_now';
  static const delayed = 'delayed_10';
  static const itemUnavailable = 'item_unavailable';

  factory OrderNotify.fromJson(Map<String, dynamic> json) {
    String? str(Object? v) {
      if (v == null) return null;
      final s = v.toString().trim();
      return s.isEmpty ? null : s;
    }

    return OrderNotify(
      type: (json['type'] ?? '').toString(),
      itemName: str(json['item_name']),
      message: str(json['message']),
      ts: str(json['ts']),
    );
  }

  /// Human-facing banner copy. Prefers a type-specific message and falls back
  /// to the server-provided `message`.
  String get bannerText {
    switch (type) {
      case ready:
        return message ?? '🎉 Your order is ready for pickup!';
      case delayed:
        return message ?? '⏳ Slight delay — about 10 more minutes.';
      case itemUnavailable:
        final name = itemName;
        if (name != null) return '😞 "$name" is unavailable.';
        return message ?? '😞 An item is unavailable.';
      default:
        return message ?? 'Update from the kitchen.';
    }
  }

  /// item_unavailable is important, so it stays until manually dismissed.
  /// ready/delayed auto-dismiss after a few seconds.
  bool get isPersistent => type == itemUnavailable;
}
