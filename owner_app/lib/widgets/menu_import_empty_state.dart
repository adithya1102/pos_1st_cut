import 'package:flutter/material.dart';
import 'package:image_picker/image_picker.dart';
import 'package:provider/provider.dart';

import '../models/menu_candidate.dart';
import '../screens/menu_import_review_screen.dart';
import '../services/api_client.dart';
import '../services/menu_ocr_service.dart';
import '../state/home_state.dart';

/// What a brand-new restaurant sees instead of an empty dish list.
///
/// A freshly verified outlet has no dishes and typing twenty in by hand on a
/// phone is the moment an owner gives up. So the empty state leads with
/// photographing the printed menu they already have.
///
/// ## It degrades to the old empty state
/// OCR is an optional, heavy server dependency. [MenuOcrService.available]
/// is asked FIRST, and when the answer is no this shows the plain "No dishes
/// yet" message plus Add dish — never a photo button that can only fail.
class MenuImportEmptyState extends StatefulWidget {
  const MenuImportEmptyState({
    super.key,
    required this.onAddManually,
    this.picker,
    this.ocrService,
  });

  /// Opens the ordinary dish editor, so manual entry is always available.
  final VoidCallback onAddManually;

  /// Injectable for tests — there is no camera on a test runner.
  final ImagePicker? picker;
  final MenuOcrService? ocrService;

  static const takePhotoKey = Key('empty_take_photo');
  static const addManuallyKey = Key('empty_add_manually');
  static const busyKey = Key('empty_busy');

  @override
  State<MenuImportEmptyState> createState() => _MenuImportEmptyStateState();
}

class _MenuImportEmptyStateState extends State<MenuImportEmptyState> {
  bool? _ocrAvailable;
  bool _busy = false;
  String _busyLabel = '';

  MenuOcrService get _ocr =>
      widget.ocrService ?? context.read<MenuOcrService>();

  @override
  void initState() {
    super.initState();
    WidgetsBinding.instance.addPostFrameCallback((_) => _checkAvailability());
  }

  Future<void> _checkAvailability() async {
    final ok = await _ocr.available();
    if (!mounted) return;
    setState(() => _ocrAvailable = ok);
  }

  Future<void> _startImport() async {
    final source = await _chooseSource();
    if (source == null || !mounted) return;

    final picker = widget.picker ?? ImagePicker();
    List<String> paths;

    try {
      if (source == ImageSource.camera) {
        // One shot per trip to the camera; the sheet reopens so several pages
        // can be taken in a row.
        final shot = await picker.pickImage(
          source: ImageSource.camera,
          // Downscaled before upload: a modern phone photo is 4-12 MB, ten of
          // them would be a ~100 MB request, and OCR gains nothing above this
          // width for printed text.
          maxWidth: 2000,
          imageQuality: 85,
        );
        paths = shot == null ? [] : [shot.path];
      } else {
        final shots = await picker.pickMultiImage(
          maxWidth: 2000,
          imageQuality: 85,
        );
        paths = shots.map((x) => x.path).toList();
      }
    } catch (_) {
      if (mounted) _snack('Could not open the camera or gallery.');
      return;
    }

    if (paths.isEmpty || !mounted) return;

    final capped = paths.length > MenuOcrService.maxImages;
    if (capped) {
      paths = paths.take(MenuOcrService.maxImages).toList();
    }

    await _runOcr(paths, capped: capped);
  }

  Future<void> _runOcr(List<String> paths, {required bool capped}) async {
    // Resolved before the awaits below — reading providers off `context`
    // across an async gap is exactly what the lint is for.
    final navigator = Navigator.of(context);
    final home = context.read<HomeState>();
    final ocr = _ocr;

    setState(() {
      _busy = true;
      _busyLabel = 'Reading ${paths.length} photo'
          '${paths.length == 1 ? '' : 's'}…';
    });

    if (capped) {
      _snack('Only the first ${MenuOcrService.maxImages} photos are used.');
    }

    MenuOcrResult result;
    try {
      result = await ocr.extract(paths);
    } on ApiException catch (e) {
      if (!mounted) return;
      setState(() => _busy = false);
      _snack(switch (e.statusCode) {
        503 => 'Menu photo import is not enabled on this server.',
        413 => 'Those photos are too large. Try fewer, or retake them.',
        504 => 'Reading took too long. Try fewer photos at a time.',
        _ => 'Could not read the photos (${e.statusCode}).',
      });
      return;
    } catch (_) {
      if (!mounted) return;
      setState(() => _busy = false);
      _snack('Could not reach the server. Check your connection.');
      return;
    }

    if (!mounted) return;
    setState(() => _busy = false);

    if (result.candidates.isEmpty) {
      _snack('Nothing readable was found. Try a straight-on, well-lit photo.');
      return;
    }

    // Approved dishes need a category. A new outlet is seeded with a default
    // set at signup, so this is populated — but it is fetched rather than
    // assumed, and a genuinely empty list is reported instead of sending a
    // null category the server would reject per item.
    final categories = await home.ensureCategories();
    if (!mounted) return;
    if (categories.isEmpty) {
      _snack('No menu categories exist yet. Add one dish manually first.');
      return;
    }

    final created = await navigator.push<int>(
      MaterialPageRoute(
        builder: (_) => MenuImportReviewScreen(
          result: result,
          categoryId: categories.first.id,
        ),
      ),
    );

    // HomeState.createDish already reloads per dish, so the list behind this
    // is current; the message is the only thing left to say.
    if (mounted && (created ?? 0) > 0) {
      _snack('Added $created dish${created == 1 ? '' : 'es'} from your photos.');
    }
  }

  Future<ImageSource?> _chooseSource() => showModalBottomSheet<ImageSource>(
        context: context,
        builder: (ctx) => SafeArea(
          child: Column(
            mainAxisSize: MainAxisSize.min,
            children: [
              ListTile(
                key: const Key('empty_source_camera'),
                leading: const Icon(Icons.photo_camera_outlined),
                title: const Text('Take a photo'),
                onTap: () => Navigator.of(ctx).pop(ImageSource.camera),
              ),
              ListTile(
                key: const Key('empty_source_gallery'),
                leading: const Icon(Icons.photo_library_outlined),
                title: Text('Choose photos (up to '
                    '${MenuOcrService.maxImages})'),
                onTap: () => Navigator.of(ctx).pop(ImageSource.gallery),
              ),
            ],
          ),
        ),
      );

  void _snack(String message) {
    if (!mounted) return;
    ScaffoldMessenger.of(context)
      ..hideCurrentSnackBar()
      ..showSnackBar(SnackBar(content: Text(message)));
  }

  @override
  Widget build(BuildContext context) {
    final theme = Theme.of(context);

    if (_busy) {
      return Padding(
        key: MenuImportEmptyState.busyKey,
        padding: const EdgeInsets.all(32),
        child: Column(
          mainAxisSize: MainAxisSize.min,
          children: [
            const CircularProgressIndicator(),
            const SizedBox(height: 16),
            Text(_busyLabel, textAlign: TextAlign.center),
            const SizedBox(height: 6),
            Text(
              'This can take up to a minute.',
              style: theme.textTheme.bodySmall
                  ?.copyWith(color: theme.colorScheme.outline),
            ),
          ],
        ),
      );
    }

    return Padding(
      padding: const EdgeInsets.all(32),
      child: Column(
        mainAxisSize: MainAxisSize.min,
        children: [
          Icon(Icons.restaurant_menu,
              size: 44, color: theme.colorScheme.outline),
          const SizedBox(height: 12),
          Text('No dishes yet', style: theme.textTheme.titleMedium),
          const SizedBox(height: 6),
          Text(
            _ocrAvailable == true
                ? 'Photograph your printed menu and we\'ll read the dishes off '
                    'it. You check everything before anything is added.'
                : 'Add your first dish to get started.',
            textAlign: TextAlign.center,
            style: theme.textTheme.bodySmall,
          ),
          const SizedBox(height: 20),
          if (_ocrAvailable == true) ...[
            FilledButton.icon(
              key: MenuImportEmptyState.takePhotoKey,
              onPressed: _startImport,
              icon: const Icon(Icons.photo_camera_outlined),
              label: const Text('Take or upload photo'),
            ),
            const SizedBox(height: 8),
          ],
          TextButton.icon(
            key: MenuImportEmptyState.addManuallyKey,
            onPressed: widget.onAddManually,
            icon: const Icon(Icons.add),
            label: const Text('Add a dish manually'),
          ),
        ],
      ),
    );
  }
}
