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
  });

  final String id;
  final String name;
  final String? phoneNumber;
  final String? email;

  /// What to render wherever a phone number is shown. Google-only customers
  /// have none yet, so they get an em dash rather than a blank.
  String get phoneDisplay =>
      (phoneNumber != null && phoneNumber!.isNotEmpty) ? phoneNumber! : '—';

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
    );
  }

  Map<String, dynamic> toJson() => {
        'id': id,
        'name': name,
        'phone_number': phoneNumber,
        'email': email,
      };
}
