import 'dart:async';

import 'package:flutter/material.dart';
import 'package:provider/provider.dart';

import '../services/places_service.dart';
import '../theme/app_colors.dart';
import '../theme/widgets/neo_card.dart';

/// Places Autocomplete search. Pops a [PlaceLocation] when the user picks a
/// result, or null if they back out. One Google session token per visit
/// (managed by [PlacesService]).
class PlaceSearchScreen extends StatefulWidget {
  const PlaceSearchScreen({super.key});

  @override
  State<PlaceSearchScreen> createState() => _PlaceSearchScreenState();
}

class _PlaceSearchScreenState extends State<PlaceSearchScreen> {
  final _controller = TextEditingController();
  Timer? _debounce;
  List<PlaceSuggestion> _results = const [];
  bool _loading = false;
  bool _resolving = false;
  String? _error;

  @override
  void initState() {
    super.initState();
    context.read<PlacesService>().startSession();
  }

  @override
  void dispose() {
    _debounce?.cancel();
    _controller.dispose();
    super.dispose();
  }

  void _onChanged(String value) {
    _debounce?.cancel();
    if (value.trim().length < 3) {
      setState(() {
        _results = const [];
        _loading = false;
      });
      return;
    }
    setState(() => _loading = true);
    // Debounce so we don't fire (and bill) a prediction on every keystroke.
    _debounce = Timer(const Duration(milliseconds: 350), () => _search(value));
  }

  Future<void> _search(String value) async {
    final places = context.read<PlacesService>();
    try {
      final res = await places.predictions(value);
      if (!mounted) return;
      setState(() {
        _results = res;
        _loading = false;
        _error = null;
      });
    } catch (_) {
      if (!mounted) return;
      setState(() {
        _loading = false;
        _error = 'Search failed. Check your connection and try again.';
      });
    }
  }

  Future<void> _pick(PlaceSuggestion s) async {
    final places = context.read<PlacesService>();
    final navigator = Navigator.of(context);
    setState(() => _resolving = true);
    try {
      final loc = await places.selectPlace(s.placeId);
      if (!mounted) return;
      if (loc != null) {
        navigator.pop(loc);
      } else {
        setState(() {
          _resolving = false;
          _error = 'Could not resolve that place. Try another.';
        });
      }
    } catch (_) {
      if (!mounted) return;
      setState(() {
        _resolving = false;
        _error = 'Could not resolve that place. Try another.';
      });
    }
  }

  @override
  Widget build(BuildContext context) {
    final c = AppColors.of(context);
    final textTheme = Theme.of(context).textTheme;
    final enabled = context.read<PlacesService>().isEnabled;

    return Scaffold(
      appBar: AppBar(title: const Text('Search location')),
      body: SafeArea(
        child: Column(
          children: [
            Padding(
              padding: const EdgeInsets.fromLTRB(16, 12, 16, 8),
              child: TextField(
                controller: _controller,
                autofocus: enabled,
                enabled: enabled,
                textInputAction: TextInputAction.search,
                onChanged: _onChanged,
                decoration: InputDecoration(
                  hintText: 'Area, landmark or address',
                  prefixIcon: const Icon(Icons.search),
                  suffixIcon: _loading
                      ? const Padding(
                          padding: EdgeInsets.all(12),
                          child: SizedBox(
                              width: 18, height: 18,
                              child: CircularProgressIndicator(strokeWidth: 2)),
                        )
                      : (_controller.text.isNotEmpty
                          ? IconButton(
                              icon: const Icon(Icons.clear),
                              onPressed: () {
                                _controller.clear();
                                _onChanged('');
                              },
                            )
                          : null),
                ),
              ),
            ),
            if (!enabled)
              Expanded(
                child: Center(
                  child: Padding(
                    padding: const EdgeInsets.all(24),
                    child: Text(
                      'Location search is unavailable in this build.\n'
                      'Use "Use GPS" instead.',
                      textAlign: TextAlign.center,
                      style: textTheme.bodyMedium?.copyWith(color: c.inkSoft),
                    ),
                  ),
                ),
              )
            else if (_error != null)
              Padding(
                padding: const EdgeInsets.all(16),
                child: Text(_error!,
                    style: textTheme.bodyMedium?.copyWith(color: c.ink)),
              )
            else
              Expanded(
                child: Stack(
                  children: [
                    ListView.separated(
                      padding: const EdgeInsets.fromLTRB(16, 8, 16, 24),
                      itemCount: _results.length,
                      separatorBuilder: (_, _) => const SizedBox(height: 10),
                      itemBuilder: (_, i) {
                        final s = _results[i];
                        return NeoCard(
                          onTap: _resolving ? null : () => _pick(s),
                          child: Row(
                            children: [
                              Icon(Icons.place_outlined, color: c.primary),
                              const SizedBox(width: 12),
                              Expanded(
                                child: Column(
                                  crossAxisAlignment: CrossAxisAlignment.start,
                                  children: [
                                    Text(s.primary,
                                        style: textTheme.titleMedium,
                                        maxLines: 1,
                                        overflow: TextOverflow.ellipsis),
                                    if (s.secondary.isNotEmpty)
                                      Text(s.secondary,
                                          style: textTheme.bodySmall
                                              ?.copyWith(color: c.inkSoft),
                                          maxLines: 1,
                                          overflow: TextOverflow.ellipsis),
                                  ],
                                ),
                              ),
                            ],
                          ),
                        );
                      },
                    ),
                    if (_resolving)
                      Container(
                        color: c.surface.withValues(alpha: 0.6),
                        child: const Center(child: CircularProgressIndicator()),
                      ),
                  ],
                ),
              ),
          ],
        ),
      ),
    );
  }
}
