import 'dart:convert';

import 'package:http/http.dart' as http;

import '../config/app_config.dart';

/// Uploads dish images to Cloudinary using an *unsigned* upload preset.
/// No API secret is embedded — the unsigned preset is the only credential,
/// and Cloudinary is configured to accept it from the client.
class CloudinaryService {
  final http.Client _http;

  CloudinaryService({http.Client? httpClient}) : _http = httpClient ?? http.Client();

  bool get configured => AppConfig.cloudinaryConfigured;

  /// Uploads the file at [filePath] and returns the secure (https) URL.
  /// Throws [Exception] on any non-2xx response or missing config.
  Future<String> uploadImage(String filePath) async {
    if (!configured) {
      throw Exception('Image upload is not configured.');
    }
    final uri = Uri.parse(
      'https://api.cloudinary.com/v1_1/${AppConfig.cloudinaryCloudName}/image/upload',
    );
    final req = http.MultipartRequest('POST', uri)
      ..fields['upload_preset'] = AppConfig.cloudinaryUploadPreset
      ..files.add(await http.MultipartFile.fromPath('file', filePath));

    final streamed = await _http.send(req);
    final res = await http.Response.fromStream(streamed);

    if (res.statusCode < 200 || res.statusCode >= 300) {
      throw Exception('Image upload failed (${res.statusCode}).');
    }
    final body = jsonDecode(res.body) as Map<String, dynamic>;
    final url = body['secure_url'] as String?;
    if (url == null || url.isEmpty) {
      throw Exception('Upload succeeded but no URL was returned.');
    }
    return url;
  }
}
