/// One dish SUGGESTED by OCR of a menu photo.
///
/// Deliberately NOT a [MenuItem]: nothing exists in the database for a
/// candidate. It has no id, because there is no row to have one. It becomes a
/// real menu item only when the owner ticks it and approves, at which point
/// the app calls the ordinary `POST /pos/menu-items`.
///
/// Mutable-by-copy: the review screen lets the owner correct both fields
/// before approving, because the parse is best-effort and frequently needs it.
class MenuCandidate {
  const MenuCandidate({
    required this.name,
    required this.price,
    this.selected = true,
  });

  final String name;
  final double price;

  /// Ticked in the review list. Candidates arrive PRE-SELECTED: the common
  /// case is "most of this is right", so the owner unticks the few misreads
  /// rather than ticking twenty correct rows one at a time.
  final bool selected;

  /// A candidate can only be approved if it would make a valid menu item —
  /// the server requires a non-empty name and a non-negative price, and
  /// finding that out one failed POST at a time would be a poor review screen.
  bool get isValid => name.trim().isNotEmpty && price >= 0;

  MenuCandidate copyWith({String? name, double? price, bool? selected}) =>
      MenuCandidate(
        name: name ?? this.name,
        price: price ?? this.price,
        selected: selected ?? this.selected,
      );

  factory MenuCandidate.fromJson(Map<String, dynamic> json) => MenuCandidate(
        name: (json['name'] as String?)?.trim() ?? '',
        price: (json['price'] as num?)?.toDouble() ?? 0.0,
      );
}

/// The result of one OCR upload.
class MenuOcrResult {
  const MenuOcrResult({
    required this.candidates,
    this.imagesReceived = 0,
    this.imagesRead = 0,
  });

  final List<MenuCandidate> candidates;

  /// How many photos were sent, and how many yielded any text. The gap is
  /// worth showing: a short list because two photos were blurry is a
  /// different problem from a short list because the menu is short.
  final int imagesReceived;
  final int imagesRead;

  int get imagesUnread => imagesReceived - imagesRead;

  factory MenuOcrResult.fromJson(Map<String, dynamic> json) => MenuOcrResult(
        candidates: ((json['candidates'] as List?) ?? const [])
            .whereType<Map>()
            .map((m) => MenuCandidate.fromJson(m.cast<String, dynamic>()))
            .toList(),
        imagesReceived: (json['images_received'] as num?)?.toInt() ?? 0,
        imagesRead: (json['images_read'] as num?)?.toInt() ?? 0,
      );
}
