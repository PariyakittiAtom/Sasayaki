import 'package:flutter/material.dart';
import 'package:supabase_flutter/supabase_flutter.dart';

import '../app_config.dart';
import '../library_api.dart';
import '../models.dart';
import '../theme.dart';
import 'collection_page.dart';

/// Cover art from a signed URL; a violet gradient with the first letter stands in until it loads (or if there is none).
class CoverImage extends StatelessWidget {
  const CoverImage({super.key, required this.api, required this.path, required this.name, this.size, this.radius = 0});

  final LibraryApi api;
  final String? path;
  final String name;
  final double? size;
  final double radius;

  @override
  Widget build(BuildContext context) {
    final letter = name.isEmpty ? '?' : name.characters.first.toUpperCase();
    final placeholder = Container(
      width: size,
      height: size,
      decoration: const BoxDecoration(gradient: Palette.accentGradient),
      alignment: Alignment.center,
      child: Text(letter, style: TextStyle(fontSize: (size ?? 96) * 0.4, fontWeight: FontWeight.w700, color: const Color(0xFF1A1030))),
    );
    Widget child = placeholder;
    if (path != null) {
      child = FutureBuilder<String>(
        future: api.signedUrl('covers', path!),
        builder: (context, snap) {
          if (!snap.hasData) return placeholder;
          return Image.network(
            snap.data!,
            width: size,
            height: size,
            fit: BoxFit.cover,
            frameBuilder: (context, img, frame, sync) =>
                AnimatedOpacity(opacity: frame == null ? 0 : 1, duration: const Duration(milliseconds: 250), child: img),
            errorBuilder: (_, __, ___) => placeholder,
          );
        },
      );
    }
    return radius > 0 ? ClipRRect(borderRadius: BorderRadius.circular(radius), child: child) : child;
  }
}

class LibraryPage extends StatefulWidget {
  const LibraryPage({super.key, required this.api, required this.config});

  final LibraryApi api;
  final AppConfig config;

  @override
  State<LibraryPage> createState() => _LibraryPageState();
}

class _LibraryPageState extends State<LibraryPage> {
  late Future<List<Collection>> _future = widget.api.collections();
  String _query = '';

  Future<void> _refresh() async {
    final next = widget.api.collections();
    setState(() => _future = next);
    try {
      await next;
    } catch (_) {/* shown by the builder */}
  }

  void _openAccount() {
    final email = Supabase.instance.client.auth.currentUser?.email ?? '';
    showModalBottomSheet<void>(
      context: context,
      builder: (ctx) => SafeArea(
        child: Padding(
          padding: const EdgeInsets.fromLTRB(24, 4, 24, 20),
          child: Column(
            mainAxisSize: MainAxisSize.min,
            crossAxisAlignment: CrossAxisAlignment.start,
            children: [
              const Text('Signed in as', style: TextStyle(color: Palette.muted)),
              const SizedBox(height: 2),
              Text(email, style: const TextStyle(fontSize: 17, fontWeight: FontWeight.w600)),
              const SizedBox(height: 20),
              OutlinedButton.icon(
                style: OutlinedButton.styleFrom(minimumSize: const Size.fromHeight(48), shape: RoundedRectangleBorder(borderRadius: BorderRadius.circular(14))),
                onPressed: () async {
                  Navigator.pop(ctx);
                  await Supabase.instance.client.auth.signOut();
                },
                icon: const Icon(Icons.logout),
                label: const Text('Sign out'),
              ),
            ],
          ),
        ),
      ),
    );
  }

  @override
  Widget build(BuildContext context) {
    return Scaffold(
      body: DecoratedBox(
        decoration: BoxDecoration(gradient: Palette.glow(0.35)),
        child: RefreshIndicator(
          onRefresh: _refresh,
          edgeOffset: 110,
          child: CustomScrollView(
            physics: const AlwaysScrollableScrollPhysics(),
            slivers: [
              SliverAppBar.large(
                backgroundColor: Colors.transparent,
                title: const Text('Library', style: TextStyle(fontWeight: FontWeight.w700)),
                actions: [
                  IconButton(onPressed: _openAccount, icon: const Icon(Icons.account_circle_outlined), tooltip: 'Account'),
                  const SizedBox(width: 6),
                ],
              ),
              SliverToBoxAdapter(
                child: Padding(
                  padding: const EdgeInsets.fromLTRB(16, 0, 16, 12),
                  child: TextField(
                    onChanged: (v) => setState(() => _query = v.trim().toLowerCase()),
                    decoration: const InputDecoration(hintText: 'Search collections', prefixIcon: Icon(Icons.search), isDense: true),
                  ),
                ),
              ),
              FutureBuilder<List<Collection>>(
                future: _future,
                builder: (context, snap) {
                  if (snap.connectionState != ConnectionState.done) {
                    return const SliverFillRemaining(hasScrollBody: false, child: Center(child: CircularProgressIndicator()));
                  }
                  if (snap.hasError) {
                    return SliverFillRemaining(hasScrollBody: false, child: _Message(Icons.cloud_off, 'Could not load your library', '${snap.error}', onRetry: _refresh));
                  }
                  final items = snap.data!.where((c) => _query.isEmpty || c.name.toLowerCase().contains(_query)).toList();
                  if (items.isEmpty) {
                    return SliverFillRemaining(
                      hasScrollBody: false,
                      child: _Message(
                        _query.isEmpty ? Icons.library_music_outlined : Icons.search_off,
                        _query.isEmpty ? 'Nothing here yet' : 'No matches',
                        _query.isEmpty ? 'Add audio in the desktop app and let it sync.' : 'Try a different word.',
                      ),
                    );
                  }
                  return SliverPadding(
                    padding: const EdgeInsets.fromLTRB(16, 4, 16, 32),
                    sliver: SliverGrid.builder(
                      gridDelegate: const SliverGridDelegateWithMaxCrossAxisExtent(
                        maxCrossAxisExtent: 240,
                        mainAxisSpacing: 20,
                        crossAxisSpacing: 16,
                        childAspectRatio: 0.78,
                      ),
                      itemCount: items.length,
                      itemBuilder: (context, i) => _CollectionTile(api: widget.api, config: widget.config, c: items[i]),
                    ),
                  );
                },
              ),
            ],
          ),
        ),
      ),
    );
  }
}

class _CollectionTile extends StatelessWidget {
  const _CollectionTile({required this.api, required this.config, required this.c});

  final LibraryApi api;
  final AppConfig config;
  final Collection c;

  @override
  Widget build(BuildContext context) {
    final n = c.trackCount;
    return GestureDetector(
      onTap: () => Navigator.of(context).push(
        MaterialPageRoute(builder: (_) => CollectionPage(api: api, config: config, collection: c)),
      ),
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          Expanded(
            child: Hero(
              tag: 'cover-${c.id}',
              child: Container(
                decoration: BoxDecoration(
                  borderRadius: BorderRadius.circular(22),
                  boxShadow: [BoxShadow(color: Colors.black.withValues(alpha: 0.35), blurRadius: 18, offset: const Offset(0, 8))],
                ),
                child: ClipRRect(
                  borderRadius: BorderRadius.circular(22),
                  child: SizedBox.expand(child: CoverImage(api: api, path: c.coverPath, name: c.name)),
                ),
              ),
            ),
          ),
          const SizedBox(height: 10),
          Text(c.name, maxLines: 2, overflow: TextOverflow.ellipsis, style: const TextStyle(fontSize: 15, fontWeight: FontWeight.w600, height: 1.2)),
          if (n != null) Text('$n track${n == 1 ? '' : 's'}', style: const TextStyle(color: Palette.muted, fontSize: 13)),
        ],
      ),
    );
  }
}

class _Message extends StatelessWidget {
  const _Message(this.icon, this.title, this.detail, {this.onRetry});

  final IconData icon;
  final String title;
  final String detail;
  final Future<void> Function()? onRetry;

  @override
  Widget build(BuildContext context) {
    return Padding(
      padding: const EdgeInsets.all(32),
      child: Column(
        mainAxisAlignment: MainAxisAlignment.center,
        children: [
          Icon(icon, size: 56, color: Palette.accentDim),
          const SizedBox(height: 16),
          Text(title, style: const TextStyle(fontSize: 18, fontWeight: FontWeight.w600)),
          const SizedBox(height: 6),
          Text(detail, textAlign: TextAlign.center, style: const TextStyle(color: Palette.muted)),
          if (onRetry != null) ...[
            const SizedBox(height: 18),
            FilledButton.tonal(onPressed: onRetry, style: FilledButton.styleFrom(minimumSize: const Size(140, 44)), child: const Text('Try again')),
          ],
        ],
      ),
    );
  }
}
