/// Indian mobile number normalization — THE one rule (TASK 2).
///
/// The backend carries the identical rule in app/core/phones.py and the
/// customer app in its own lib/utils/in_mobile.dart; the three are kept in
/// step by identical test vectors.
///
/// Rule: strip everything that is not a digit, keep the LAST ten digits, and
/// accept the result only when it is exactly ten digits starting 6-9 (the
/// TRAI mobile space). Everything else is null.
library;

/// The ten subscriber digits of [raw], or null when it is not a usable
/// Indian mobile number.
///
/// "919499956612", "+919499956612", "09499956612", "9499956612",
/// "94999 56612" and "+91-94999-56612" all return "9499956612".
String? normalizeInMobile(String raw) {
  var digits = raw.replaceAll(RegExp(r'\D'), '');
  if (digits.length > 10) {
    // A garbled or doubled prefix corrupts the FRONT of the string, never
    // the subscriber number at the end.
    digits = digits.substring(digits.length - 10);
  }
  if (digits.length != 10) return null;
  if (!'6789'.contains(digits[0])) return null;
  return digits;
}

/// Canonical wire/dial spelling: '+91' + the ten digits, or null.
String? canonicalInMobile(String raw) {
  final ten = normalizeInMobile(raw);
  return ten == null ? null : '+91$ten';
}
