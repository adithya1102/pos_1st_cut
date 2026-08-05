/// Authenticated customer profile returned by the auth endpoints.
///
/// A customer has at least one identity but not necessarily both: phone-OTP
/// sign-in yields a phone and no email, Google sign-in yields an email and no
/// phone (a standalone identity — the customer verifies a phone separately, if
/// ever). Both fields are therefore nullable.
class Customer {
  const Customer({
    required this.id,
    required this.name,
    this.phoneNumber,
    this.email,
    this.pointsBalance = 0,
    this.premiumUntil,
    this.plan = 'Free',
  });

  final String id;
  final String name;
  final String? phoneNumber;
  final String? email;

  /// Loyalty balance (migration 010).
  final double pointsBalance;

  /// End of the premium window granted by a free-trial coupon, or null if the
  /// customer has never had one. Purely informational today: no paid plan
  /// exists yet and premium does not unlock anything.
  final DateTime? premiumUntil;

  /// Server-derived label ("Free" / "Premium"). Derived there rather than here
  /// so the app, the admin dashboard and the API can never disagree.
  final String plan;

  /// What to render wherever a phone number is shown. Google-only customers
  /// have none yet, so they get an em dash rather than a blank.
  String get phoneDisplay =>
      (phoneNumber != null && phoneNumber!.isNotEmpty) ? phoneNumber! : '—';

  /// Mirror of [phoneDisplay] for phone-only customers, who have no email.
  String get emailDisplay =>
      (email != null && email!.isNotEmpty) ? email! : '—';

  Customer copyWith({String? name, double? pointsBalance}) => Customer(
        id: id,
        name: name ?? this.name,
        phoneNumber: phoneNumber,
        email: email,
        pointsBalance: pointsBalance ?? this.pointsBalance,
        premiumUntil: premiumUntil,
        plan: plan,
      );

  factory Customer.fromJson(Map<String, dynamic> json) {
    String? nonEmpty(Object? v) {
      final s = v?.toString();
      return (s == null || s.isEmpty) ? null : s;
    }

    return Customer(
      id: json['id']?.toString() ?? '',
      name: (json['name'] ?? '') as String,
      phoneNumber: nonEmpty(json['phone_number']),
      email: nonEmpty(json['email']),
      // Absent on the auth endpoints, which predate migration 010 — default
      // rather than throw, so an older response still parses.
      pointsBalance:
          double.tryParse(json['points_balance']?.toString() ?? '') ?? 0,
      premiumUntil: DateTime.tryParse(json['premium_until']?.toString() ?? ''),
      plan: nonEmpty(json['plan']) ?? 'Free',
    );
  }

  Map<String, dynamic> toJson() => {
        'id': id,
        'name': name,
        'phone_number': phoneNumber,
        'email': email,
        'points_balance': pointsBalance,
        'premium_until': premiumUntil?.toIso8601String(),
        'plan': plan,
      };
}
