/// A menu category (from GET /pos/categories), used by the dish form's picker.
class Category {
  final String id;
  final String name;

  const Category({required this.id, required this.name});

  factory Category.fromJson(Map<String, dynamic> json) {
    return Category(
      id: json['id'] as String,
      name: (json['name'] as String?) ?? '',
    );
  }
}
