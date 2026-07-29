import '../models/outlet.dart';
import 'api_client.dart';

class OutletService {
  final ApiClient _client;

  OutletService(this._client);

  /// `GET /pos/outlet`
  Future<Outlet> getOutlet() async {
    final data = await _client.get('/pos/outlet');
    return Outlet.fromJson(data as Map<String, dynamic>);
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
}
