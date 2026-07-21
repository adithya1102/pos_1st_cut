import '../models/menu_item.dart';
import 'api_client.dart';

class MenuService {
  final ApiClient _client;

  MenuService(this._client);

  /// `GET /pos/menu-items` — flat list (no categories).
  Future<List<MenuItem>> getMenuItems() async {
    final data = await _client.get('/pos/menu-items');
    final list = (data as List<dynamic>?) ?? const [];
    return list
        .map((e) => MenuItem.fromJson(e as Map<String, dynamic>))
        .toList();
  }

  /// `PATCH /pos/menu-items/{id}/availability`
  Future<bool> setAvailability(int itemId, bool isAvailable) async {
    final data = await _client.patch(
      '/pos/menu-items/$itemId/availability',
      body: {'is_available': isAvailable},
    );
    final map = data as Map<String, dynamic>;
    return (map['is_available'] as bool?) ?? isAvailable;
  }
}
