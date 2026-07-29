import '../models/category.dart';
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

  /// `GET /pos/categories` — categories of the outlet's latest menu.
  Future<List<Category>> getCategories() async {
    final data = await _client.get('/pos/categories');
    final list = (data as List<dynamic>?) ?? const [];
    return list
        .map((e) => Category.fromJson(e as Map<String, dynamic>))
        .toList();
  }

  /// `POST /pos/menu-items` — create a dish.
  Future<MenuItem> createItem({
    required String name,
    required double basePrice,
    required String categoryId,
    required bool isVeg,
    int? prepTimeMinutes,
    String? imageUrl,
  }) async {
    final data = await _client.post('/pos/menu-items', body: {
      'name': name,
      'base_price': basePrice,
      'category_id': categoryId,
      'is_veg': isVeg,
      if (prepTimeMinutes != null) 'prep_time_minutes': prepTimeMinutes,
      if (imageUrl != null) 'image_url': imageUrl,
    });
    return MenuItem.fromJson(data as Map<String, dynamic>);
  }

  /// `PATCH /pos/menu-items/{id}` — update only the provided fields.
  Future<MenuItem> updateItem(
    String itemId, {
    String? name,
    double? basePrice,
    String? categoryId,
    bool? isVeg,
    int? prepTimeMinutes,
    String? imageUrl,
  }) async {
    final data = await _client.patch('/pos/menu-items/$itemId', body: {
      if (name != null) 'name': name,
      if (basePrice != null) 'base_price': basePrice,
      if (categoryId != null) 'category_id': categoryId,
      if (isVeg != null) 'is_veg': isVeg,
      if (prepTimeMinutes != null) 'prep_time_minutes': prepTimeMinutes,
      if (imageUrl != null) 'image_url': imageUrl,
    });
    return MenuItem.fromJson(data as Map<String, dynamic>);
  }

  /// `DELETE /pos/menu-items/{id}` — soft delete (deactivate).
  Future<void> deleteItem(String itemId) async {
    await _client.delete('/pos/menu-items/$itemId');
  }

  /// `PATCH /pos/menu-items/{id}/availability`
  Future<bool> setAvailability(String itemId, bool isAvailable) async {
    final data = await _client.patch(
      '/pos/menu-items/$itemId/availability',
      body: {'is_available': isAvailable},
    );
    final map = data as Map<String, dynamic>;
    return (map['is_available'] as bool?) ?? isAvailable;
  }
}
