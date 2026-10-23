// Plain data classes mirroring the rows the desktop app syncs (see supabase/schema.sql).

class Collection {
  Collection({required this.id, required this.name, required this.description, this.coverPath, this.trackCount});

  final String id;
  final String name;
  final String description;
  final String? coverPath;
  final int? trackCount;

  factory Collection.fromJson(Map<String, dynamic> j) => Collection(
        id: j['id'] as String,
        name: j['name'] as String,
        description: (j['description'] as String?) ?? '',
        coverPath: j['cover_path'] as String?,
        trackCount: _embeddedCount(j['tracks']),
      );
}

/// PostgREST returns an embedded count as `[{"count": 3}]`.
int? _embeddedCount(Object? v) {
  if (v is List && v.isNotEmpty && v.first is Map) return (v.first as Map)['count'] as int?;
  return null;
}

class Track {
  Track({
    required this.id,
    required this.collectionId,
    required this.title,
    required this.durationMs,
    required this.srcLang,
    this.audioPath,
  });

  final String id;
  final String collectionId;
  final String title;
  final int durationMs;
  final String srcLang;
  final String? audioPath;

  bool get hasAudio => audioPath != null && audioPath!.isNotEmpty;

  factory Track.fromJson(Map<String, dynamic> j) => Track(
        id: j['id'] as String,
        collectionId: j['collection_id'] as String,
        title: j['title'] as String,
        durationMs: (j['duration_ms'] as num?)?.toInt() ?? 0,
        srcLang: (j['src_lang'] as String?) ?? 'auto',
        audioPath: j['audio_path'] as String?,
      );
}

class Cue {
  const Cue({required this.idx, required this.startMs, required this.endMs, required this.src, required this.en});

  final int idx;
  final int startMs;
  final int endMs;
  final String src;
  final String en;

  factory Cue.fromJson(Map<String, dynamic> j) => Cue(
        idx: (j['idx'] as num).toInt(),
        startMs: (j['start_ms'] as num).toInt(),
        endMs: (j['end_ms'] as num).toInt(),
        src: (j['src_text'] as String?) ?? '',
        en: (j['en_text'] as String?) ?? '',
      );
}

/// Index of the cue showing at [posMs], or null in a gap. [cues] must be sorted by start time.
int? activeCueIndex(List<Cue> cues, int posMs) {
  int lo = 0, hi = cues.length - 1, found = -1;
  while (lo <= hi) {
    final mid = (lo + hi) >> 1;
    if (cues[mid].startMs <= posMs) {
      found = mid;
      lo = mid + 1;
    } else {
      hi = mid - 1;
    }
  }
  if (found < 0) return null;
  return posMs < cues[found].endMs ? found : null;
}

String formatClock(Duration d) {
  final s = d.inSeconds < 0 ? 0 : d.inSeconds;
  final h = s ~/ 3600, m = (s ~/ 60) % 60, sec = s % 60;
  final mm = m.toString().padLeft(h > 0 ? 2 : 1, '0'), ss = sec.toString().padLeft(2, '0');
  return h > 0 ? '$h:$mm:$ss' : '$mm:$ss';
}
