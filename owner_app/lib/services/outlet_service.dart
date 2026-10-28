import '../models/outlet.dart';
import '../models/payment_settings.dart';
import 'api_client.dart';

class OutletService {
  final ApiClient _client;

  OutletService(this._client);

  /// `GET /pos/outlet`
  Future<Outlet> getOutlet() async {
    final data = await _client.get('/pos/outlet');
    return Outlet.fromJson(data as Map<String, dynamic>);
  }

  /// `PATCH /pos/outlet/image` — store the Cloudinary URL for the storefront
  /// photo. Scoped server-side to the caller's own outlet; pass null to clear.
  ///
  /// The upload itself goes through [CloudinaryService], the same unsigned
  /// pipeline dish images already use — no second upload path was built.
  Future<Outlet> setImage(String? imageUrl) async {
    final data = await _client.patch('/pos/outlet/image', body: {
      'image_url': imageUrl,
    });
    return Outlet.fromJson((data as Map).cast<String, dynamic>());
  }

  /// `POST /pos/outlets/{id}/visibility`
  Future<bool> setVisibility(String outletId, bool isVisible) async {
    final data = await _client.post(
      '/pos/outlets/$outletId/visibility',
      body: {'is_visible': isVisible},
    );
    final map = data as Map<String, dynamic>;
    return (map['is_visible'] as bool?) ?? isVisible;
  }

  /// `PATCH /pos/outlet/hours` — set/clear the daily schedule (migration 024).
  /// Times are "HH:MM" (24h) or null to clear. Scoped server-side to the
  /// caller's own outlet. Returns the full refreshed outlet.
  Future<Outlet> setHours(String? openingTime, String? closingTime) async {
    final data = await _client.patch('/pos/outlet/hours', body: {
      'opening_time': openingTime,
      'closing_time': closingTime,
    });
    return Outlet.fromJson((data as Map).cast<String, dynamic>());
  }

  /// `PATCH /pos/outlet/location` — pin the outlet's coordinates from the
  /// owner's own device. Scoped server-side to the caller's own outlet, so no
  /// outlet id is sent. Returns the full refreshed outlet.
  Future<Outlet> setLocation(double latitude, double longitude) async {
    final data = await _client.patch('/pos/outlet/location', body: {
      'latitude': latitude,
      'longitude': longitude,
    });
    return Outlet.fromJson((data as Map).cast<String, dynamic>());
  }

  /// `POST /pos/outlet/closed` — flip the "temporarily closed" toggle
  /// (migration 024). Returns the full refreshed outlet.
  /// `GET /pos/outlet/payment-methods` (backend migration 035).
  ///
  /// OWNER / MANAGER only server-side; a waiter or kitchen account gets a 403,
  /// which is what hides the Payment modes entry from them.
  Future<PaymentSettings> getPaymentSettings() async {
    final data = await _client.get('/pos/outlet/payment-methods');
    return PaymentSettings.fromJson((data as Map).cast<String, dynamic>());
  }

  /// `PATCH /pos/outlet/payment-methods`.
  ///
  /// Sends the FULL desired state, as the server requires: a partial update is
  /// how an outlet ends up accepting nothing.
  ///
  /// Errors are deliberately NOT normalised here. The server refuses with
  /// prose written for the owner — "Cashfree is currently unavailable for your
  /// restaurant", "Send yourself Rs 1 using this UPI ID..." — and the screen
  /// shows it verbatim, so an ApiException is allowed to propagate.
  Future<PaymentSettings> setPaymentSettings({
    required bool prepaid,
    required bool payAtPickup,
    required bool upiManual,
    String? upiVpa,
    String? upiPayeeName,
    bool upiAttested = false,
  }) async {
    final data = await _client.patch('/pos/outlet/payment-methods', body: {
      'prepaid': prepaid,
      'pay_at_pickup': payAtPickup,
      'upi_manual': upiManual,
      'upi_vpa': upiVpa,
      'upi_payee_name': upiPayeeName,
      'upi_attested': upiAttested,
    });
    return PaymentSettings.fromJson((data as Map).cast<String, dynamic>());
  }

  Future<Outlet> setManualClosed(bool isClosed) async {
    final data = await _client.post('/pos/outlet/closed', body: {
      'is_manually_closed': isClosed,
    });
    return Outlet.fromJson((data as Map).cast<String, dynamic>());
  }
}
