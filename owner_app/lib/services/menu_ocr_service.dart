import 'dart:convert';

import 'package:http/http.dart' as http;

import '../config/app_config.dart';
import '../models/menu_candidate.dart';
import 'api_client.dart';

/// Uploads menu photos and gets back SUGGESTED dishes.
///
/// Creates nothing. Approved candidates are created by [MenuService.createItem]
/// — the same `POST /pos/menu-items` the Add-dish form uses — so there is no
/// second creation path to keep in step.
///
/// Multipart is built here rather than through [ApiClient]'s JSON verbs, since
/// none of them carry files. The token is read from the same ApiClient, so the
/// auth story is unchanged.
class MenuOcrService {
  MenuOcrService(this._client, {http.Client? httpClient})
      : _http = httpClient ?? http.Client();

  final ApiClient _client;
  final http.Client _http;

  /// Product cap, mirrored from the server's MAX_IMAGES. Enforced in the app
  /// too so the owner is stopped at the picker rather than by a 422 after
  /// uploading several megabytes.
  static const int maxImages = 10;

  /// `GET /pos/menu-import/status` — can this deploy OCR at all?
  ///
  /// Asked before the photo button is offered. The dependency is heavy and
  /// gated server-side, so a deploy without it must show manual entry rather
  /// than a button that can only fail.
  Future<bool> available() async {
    try {
      final data = await _client.get('/pos/menu-import/status');
      return (data as Map?)?['enabled'] == true;
    } catch (_) {
      // An older backend has no such route. Treat anything unexpected as "no
      // OCR" — the empty state still offers Add dish, so nothing is lost.
      return false;
    }
  }

  /// `POST /pos/menu-import/ocr` — up to [maxImages] photos.
  ///
  /// The long timeout is deliberate: this is CPU-bound inference over up to
  /// ten photographs on a shared instance, which is a different order of wait
  /// from a database read, on top of the usual free-tier cold start.
  Future<MenuOcrResult> extract(List<String> imagePaths) async {
    if (imagePaths.isEmpty) {
      return const MenuOcrResult(candidates: []);
    }
    final paths = imagePaths.take(maxImages).toList();

    final request = http.MultipartRequest(
      'POST',
      Uri.parse('${AppConfig.baseUrl}/pos/menu-import/ocr'),
    );

    final token = await _client.readToken();
    if (token != null && token.isNotEmpty) {
      request.headers['Authorization'] = 'Bearer $token';
    }
    request.headers['Accept'] = 'application/json';

    for (final path in paths) {
      // Field name 'images' repeated per file — FastAPI binds a repeated
      // field to list[UploadFile].
      request.files.add(await http.MultipartFile.fromPath('images', path));
    }

    final streamed = await _http.send(request).timeout(ocrTimeout);
    final response = await http.Response.fromStream(streamed);

    if (response.statusCode < 200 || response.statusCode >= 300) {
      Map<String, dynamic>? parsed;
      try {
        parsed = jsonDecode(response.body) as Map<String, dynamic>;
      } catch (_) {
        parsed = null;
      }
      throw ApiException(
        response.statusCode,
        parsed?['detail']?.toString() ?? 'Could not read the photos',
        body: parsed,
      );
    }

    return MenuOcrResult.fromJson(
        jsonDecode(response.body) as Map<String, dynamic>);
  }

  /// Ten photographs of a menu, uploaded and OCR'd on a free-tier CPU, is a
  /// genuinely long operation — much longer than ApiClient.requestTimeout,
  /// which is sized for a cold start plus a query.
  static const Duration ocrTimeout = Duration(seconds: 180);
}
