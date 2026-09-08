/// Ask the CDN for the size we actually draw.
///
/// ## Why
///
/// Profiling the nearby page found the API was not the slow part: the outlets
/// query plans at 0.038ms over six rows and the offer summary at 0.101ms, both
/// already single batched queries. What the page actually waits on is SIX
/// full-size Cloudinary originals, fetched over the network to fill a ~76px
/// thumbnail box.
///
/// Cloudinary resizes on delivery from the URL itself, so asking for the small
/// version costs nothing but a path segment — no upload, no migration, no
/// backend change. `q_auto,f_auto` additionally let it pick the quality and
/// serve WebP/AVIF where the device supports it.
///
/// Deliberately a pure string function: no package, no cache layer, no new
/// dependency. Persistent disk caching (`cached_network_image`) is the obvious
/// next step and is NOT done here — it is a dependency decision, and this fix
/// is scoped to what the profiling actually showed.
library;

/// Cloudinary delivery URLs look like
/// `https://res.cloudinary.com/<cloud>/image/upload/<version>/<public_id>`
/// and accept transformations as a segment straight after `/upload/`.
const _cloudinaryHost = 'res.cloudinary.com';
const _uploadSegment = '/image/upload/';

/// A thumbnail-sized variant of [url], or [url] unchanged when it is not a
/// transformable Cloudinary delivery URL.
///
/// Returning the input untouched for anything unrecognised is the important
/// half: a self-hosted or third-party image must still render, so this can
/// only ever make an image cheaper, never missing.
String? cdnThumbnail(String? url, {int width = 200, int height = 200}) {
  if (url == null || url.isEmpty) return url;

  final uri = Uri.tryParse(url);
  if (uri == null || uri.host != _cloudinaryHost) return url;

  final i = url.indexOf(_uploadSegment);
  if (i < 0) return url;

  final head = url.substring(0, i + _uploadSegment.length);
  final tail = url.substring(i + _uploadSegment.length);

  // Already transformed? Cloudinary transformation segments are comma-joined
  // `k_v` pairs. Re-wrapping one would silently override a deliberate choice,
  // so it is left alone.
  final firstSegment = tail.split('/').first;
  if (firstSegment.contains(',') || _looksLikeTransform(firstSegment)) {
    return url;
  }

  // c_fill: the box is a fixed square and BoxFit.cover crops anyway, so the
  // crop may as well happen at the CDN and travel as fewer bytes.
  return '${head}w_$width,h_$height,c_fill,q_auto,f_auto/$tail';
}

/// A lone transformation directive such as `w_200` — no comma to give it away.
bool _looksLikeTransform(String segment) {
  const knownKeys = {'w', 'h', 'c', 'q', 'f', 'e', 'g', 'ar', 'dpr'};
  final underscore = segment.indexOf('_');
  if (underscore <= 0) return false;
  return knownKeys.contains(segment.substring(0, underscore));
}
