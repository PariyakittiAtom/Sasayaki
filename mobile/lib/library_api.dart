import 'package:supabase_flutter/supabase_flutter.dart';

import 'models.dart';

/// Read-only access to the cloud library. Row-level security limits every query to the signed-in user.
class LibraryApi {
  LibraryApi(this._db);

  final SupabaseClient _db;

  static const _pageSize = 1000; // PostgREST returns at most 1000 rows per request
  static const _urlLifetime = 60 * 60 * 12; // seconds; long enough for a whole listening session

  final Map<String, String> _urlCache = {};

  Future<List<Collection>> collections() async {
    final rows = await _db.from('collections').select('id,name,description,cover_path,tracks(count)').order('name');
    return rows.map((r) => Collection.fromJson(r)).toList();
  }

  Future<List<Track>> tracks(String collectionId) async {
    final rows = await _db
        .from('tracks')
        .select('id,collection_id,title,duration_ms,src_lang,audio_path')
        .eq('collection_id', collectionId)
        .order('sort_order')
        .order('title');
    return rows.map((r) => Track.fromJson(r)).toList();
  }

  Future<List<Cue>> cues(String trackId) async {
    final out = <Cue>[];
    for (var from = 0;; from += _pageSize) {
      final rows = await _db
          .from('cues')
          .select('idx,start_ms,end_ms,src_text,en_text')
          .eq('track_id', trackId)
          .order('idx')
          .range(from, from + _pageSize - 1);
      out.addAll(rows.map((r) => Cue.fromJson(r)));
      if (rows.length < _pageSize) break;
    }
    return out;
  }

  Future<String> signedUrl(String bucket, String path) async {
    final key = '$bucket/$path';
    return _urlCache[key] ??= await _db.storage.from(bucket).createSignedUrl(path, _urlLifetime);
  }
}
