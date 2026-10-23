import 'package:flutter/material.dart';

import '../app_config.dart';
import '../library_api.dart';
import '../models.dart';
import '../theme.dart';
import 'library_page.dart';
import 'player_page.dart';

const _langLabel = {'ja': 'JA', 'ko': 'KO', 'en': 'EN'};

class CollectionPage extends StatefulWidget {
  const CollectionPage({super.key, required this.api, required this.config, required this.collection});

  final LibraryApi api;
  final AppConfig config;
  final Collection collection;

  @override
  State<CollectionPage> createState() => _CollectionPageState();
}

class _CollectionPageState extends State<CollectionPage> {
  late Future<List<Track>> _future = widget.api.tracks(widget.collection.id);

  Future<void> _refresh() async {
    final next = widget.api.tracks(widget.collection.id);
    setState(() => _future = next);
    try {
      await next;
    } catch (_) {/* shown by the builder */}
  }

  void _play(Track t) => Navigator.of(context).push(
        MaterialPageRoute(builder: (_) => PlayerPage(api: widget.api, config: widget.config, collection: widget.collection, track: t)),
      );

  @override
  Widget build(BuildContext context) {
    final c = widget.collection;
    return Scaffold(
      body: RefreshIndicator(
        onRefresh: _refresh,
        edgeOffset: 100,
        child: CustomScrollView(
          physics: const AlwaysScrollableScrollPhysics(),
          slivers: [
            SliverAppBar(
              pinned: true,
              stretch: true,
              expandedHeight: 320,
              backgroundColor: Palette.bg,
              flexibleSpace: FlexibleSpaceBar(
                titlePadding: const EdgeInsetsDirectional.only(start: 56, bottom: 14, end: 16),
                title: Text(c.name, maxLines: 1, overflow: TextOverflow.ellipsis, style: const TextStyle(fontSize: 18, fontWeight: FontWeight.w700)),
                background: Stack(
                  fit: StackFit.expand,
                  children: [
                    Hero(tag: 'cover-${c.id}', child: CoverImage(api: widget.api, path: c.coverPath, name: c.name)),
                    const DecoratedBox(
                      decoration: BoxDecoration(
                        gradient: LinearGradient(
                          begin: Alignment.topCenter,
                          end: Alignment.bottomCenter,
                          colors: [Color(0x66000000), Color(0x00000000), Palette.bg],
                          stops: [0, 0.35, 1],
                        ),
                      ),
                    ),
                  ],
                ),
              ),
            ),
            FutureBuilder<List<Track>>(
              future: _future,
              builder: (context, snap) {
                if (snap.connectionState != ConnectionState.done) {
                  return const SliverFillRemaining(hasScrollBody: false, child: Center(child: CircularProgressIndicator()));
                }
                final tracks = snap.data ?? const <Track>[];
                final playable = tracks.where((t) => t.hasAudio).toList();
                return SliverList(
                  delegate: SliverChildListDelegate([
                    Padding(
                      padding: const EdgeInsets.fromLTRB(20, 4, 20, 8),
                      child: Column(
                        crossAxisAlignment: CrossAxisAlignment.start,
                        children: [
                          Text(
                            '${tracks.length} track${tracks.length == 1 ? '' : 's'}'
                            '${tracks.fold<int>(0, (a, t) => a + t.durationMs) > 0 ? '  ·  ${_total(tracks)}' : ''}',
                            style: const TextStyle(color: Palette.muted),
                          ),
                          if (c.description.isNotEmpty) ...[
                            const SizedBox(height: 8),
                            Text(c.description, style: const TextStyle(color: Palette.text, height: 1.4)),
                          ],
                          if (playable.isNotEmpty) ...[
                            const SizedBox(height: 16),
                            FilledButton.icon(onPressed: () => _play(playable.first), icon: const Icon(Icons.play_arrow_rounded), label: const Text('Play')),
                          ],
                        ],
                      ),
                    ),
                    if (snap.hasError)
                      Padding(padding: const EdgeInsets.all(20), child: Text('Could not load tracks.\n${snap.error}', style: const TextStyle(color: Palette.error))),
                    for (var i = 0; i < tracks.length; i++) _TrackTile(index: i + 1, track: tracks[i], onTap: () => _play(tracks[i])),
                    const SizedBox(height: 32),
                  ]),
                );
              },
            ),
          ],
        ),
      ),
    );
  }

  static String _total(List<Track> tracks) => formatClock(Duration(milliseconds: tracks.fold<int>(0, (a, t) => a + t.durationMs)));
}

class _TrackTile extends StatelessWidget {
  const _TrackTile({required this.index, required this.track, required this.onTap});

  final int index;
  final Track track;
  final VoidCallback onTap;

  @override
  Widget build(BuildContext context) {
    final lang = _langLabel[track.srcLang];
    return Padding(
      padding: const EdgeInsets.symmetric(horizontal: 14, vertical: 4),
      child: Material(
        color: Palette.panel,
        borderRadius: BorderRadius.circular(18),
        child: InkWell(
          borderRadius: BorderRadius.circular(18),
          onTap: onTap,
          child: Padding(
            padding: const EdgeInsets.fromLTRB(12, 12, 14, 12),
            child: Row(
              children: [
                Container(
                  width: 38,
                  height: 38,
                  decoration: BoxDecoration(color: Palette.panelHi, borderRadius: BorderRadius.circular(12)),
                  alignment: Alignment.center,
                  child: Text('$index', style: const TextStyle(color: Palette.muted, fontWeight: FontWeight.w600)),
                ),
                const SizedBox(width: 14),
                Expanded(
                  child: Column(
                    crossAxisAlignment: CrossAxisAlignment.start,
                    children: [
                      Text(track.title, maxLines: 2, overflow: TextOverflow.ellipsis, style: const TextStyle(fontWeight: FontWeight.w600, height: 1.25)),
                      const SizedBox(height: 4),
                      Wrap(
                        spacing: 8,
                        crossAxisAlignment: WrapCrossAlignment.center,
                        children: [
                          if (track.durationMs > 0) Text(formatClock(Duration(milliseconds: track.durationMs)), style: const TextStyle(color: Palette.muted, fontSize: 13)),
                          if (lang != null) _Chip(lang),
                          if (!track.hasAudio) const _Chip('no audio yet', warn: true),
                        ],
                      ),
                    ],
                  ),
                ),
                Icon(track.hasAudio ? Icons.play_circle_fill_rounded : Icons.subtitles_outlined, size: 32, color: track.hasAudio ? Palette.accent : Palette.muted),
              ],
            ),
          ),
        ),
      ),
    );
  }
}

class _Chip extends StatelessWidget {
  const _Chip(this.text, {this.warn = false});

  final String text;
  final bool warn;

  @override
  Widget build(BuildContext context) => Container(
        padding: const EdgeInsets.symmetric(horizontal: 8, vertical: 2),
        decoration: BoxDecoration(
          color: (warn ? Palette.error : Palette.accent).withValues(alpha: 0.14),
          borderRadius: BorderRadius.circular(8),
        ),
        child: Text(text, style: TextStyle(fontSize: 11, fontWeight: FontWeight.w600, color: warn ? Palette.error : Palette.accent)),
      );
}
