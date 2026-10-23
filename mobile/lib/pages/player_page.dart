import 'dart:async';
import 'dart:math' as math;

import 'package:flutter/material.dart';
import 'package:just_audio/just_audio.dart';
import 'package:just_audio_background/just_audio_background.dart';
import 'package:scrollable_positioned_list/scrollable_positioned_list.dart';

import '../app_config.dart';
import '../library_api.dart';
import '../models.dart';
import '../theme.dart';
import 'library_page.dart';

const _speeds = [0.75, 0.9, 1.0, 1.1, 1.25, 1.5, 2.0];
const _modes = {'en': 'English', 'both': 'English + original', 'src': 'Original only'};
const _modeShort = {'en': 'English', 'both': 'EN + original', 'src': 'Original'};

class PlayerPage extends StatefulWidget {
  const PlayerPage({super.key, required this.api, required this.config, required this.collection, required this.track});

  final LibraryApi api;
  final AppConfig config;
  final Collection collection;
  final Track track;

  @override
  State<PlayerPage> createState() => _PlayerPageState();
}

class _PlayerPageState extends State<PlayerPage> {
  final _player = AudioPlayer();
  final _scroll = ItemScrollController();
  final _active = ValueNotifier<int?>(null);
  final _posMs = ValueNotifier<int>(0); // what the phone currently reads from the player (shown in the transcript header)
  StreamSubscription<Duration>? _posSub;
  Timer? _ticker;

  List<Cue> _cues = const [];
  bool _loading = true;
  String? _error; // problem with the audio (subtitles may still show)
  String? _cuesError;
  bool _follow = true;
  bool _dragging = false;
  double _dragValue = 0;
  int _tab = 0; // 0 = now playing, 1 = transcript

  late String _mode = widget.config.displayMode;
  late double _fontSize = widget.config.fontSize;
  late int _offsetMs = widget.config.offsetMs; // positive = show subtitles later

  bool get _hasSource => _cues.any((c) => c.src.isNotEmpty);

  @override
  void initState() {
    super.initState();
    _active.addListener(_onActiveChanged);
    // The same feed the seek bar uses: always running, so playing before the lines finish loading is fine.
    _posSub = _player.positionStream.listen(_onPosition);
    // Belt and braces: poll the clock too, so the highlighted line never depends on a stream firing.
    _ticker = Timer.periodic(const Duration(milliseconds: 100), (_) {
      if (_cues.isNotEmpty && _player.playing) _onPosition(_player.position);
    });
    _load();
  }

  @override
  void dispose() {
    _posSub?.cancel();
    _ticker?.cancel();
    _active.dispose();
    _posMs.dispose();
    _player.dispose();
    super.dispose();
  }

  Future<void> _load() async {
    final cuesFuture = widget.api.cues(widget.track.id).then<List<Cue>?>((c) => c).catchError((Object e) {
      _cuesError = '$e';
      return null;
    });
    final audioFuture = _loadAudio();
    final cues = await cuesFuture;
    await audioFuture;
    if (!mounted) return;
    setState(() {
      // the line lookup is a binary search: it needs them ordered by start time
      _cues = (cues ?? const <Cue>[]).toList()..sort((a, b) => a.startMs.compareTo(b.startMs));
      _loading = false;
    });
    _onPosition(_player.position); // catch up if playback already started
  }

  Future<void> _loadAudio() async {
    final t = widget.track;
    if (!t.hasAudio) {
      _error = 'The audio for this track has not been uploaded yet.';
      return;
    }
    try {
      final url = await widget.api.signedUrl('audio', t.audioPath!);
      Uri? art;
      if (widget.collection.coverPath != null) {
        art = Uri.tryParse(await widget.api.signedUrl('covers', widget.collection.coverPath!));
      }
      await _player.setAudioSource(
        AudioSource.uri(Uri.parse(url), tag: MediaItem(id: t.id, title: t.title, album: widget.collection.name, artUri: art)),
      );
    } catch (e) {
      _error = 'Could not load the audio: $e';
    }
  }

  void _onPosition(Duration pos) {
    _posMs.value = pos.inMilliseconds;
    if (_cues.isEmpty) return;
    _active.value = activeCueIndex(_cues, pos.inMilliseconds - _offsetMs);
  }

  void _onActiveChanged() {
    final i = _active.value;
    if (i != null && _follow && _tab == 1 && _scroll.isAttached) {
      _scroll.scrollTo(index: i, alignment: 0.35, duration: const Duration(milliseconds: 300), curve: Curves.easeOutCubic);
    }
  }

  void _setTab(int t) {
    if (t == _tab) return;
    setState(() => _tab = t);
    if (t == 1) {
      WidgetsBinding.instance.addPostFrameCallback((_) {
        final i = _active.value;
        if (i != null && _scroll.isAttached) _scroll.jumpTo(index: i, alignment: 0.35);
      });
    }
  }

  // ------------------------------------------------------------------ actions
  Future<void> _seekToCue(int i) async {
    await _player.seek(Duration(milliseconds: (_cues[i].startMs + _offsetMs).clamp(0, 1 << 40)));
    _onPosition(_player.position); // also updates while paused
  }

  void _jumpCue(int dir) {
    if (_cues.isEmpty) return;
    final now = _player.position.inMilliseconds - _offsetMs;
    if (dir > 0) {
      final i = _cues.indexWhere((c) => c.startMs > now);
      if (i >= 0) _seekToCue(i);
    } else {
      var i = _cues.lastIndexWhere((c) => c.startMs <= now);
      if (i >= 0 && now - _cues[i].startMs < 1500) i -= 1; // near the start of a line: go to the one before
      if (i >= 0) _seekToCue(i);
    }
  }

  void _seekBy(int ms) {
    final dur = _player.duration ?? Duration.zero;
    final target = _player.position + Duration(milliseconds: ms);
    _player.seek(target < Duration.zero ? Duration.zero : (dur > Duration.zero && target > dur ? dur : target)).then((_) => _onPosition(_player.position));
  }

  void _setMode(String m) {
    setState(() => _mode = m);
    widget.config.setDisplayMode(m);
  }

  void _setOffset(int v, [StateSetter? setSheet]) {
    setState(() => _offsetMs = v.clamp(-3000, 3000));
    widget.config.setOffsetMs(_offsetMs);
    setSheet?.call(() {});
    _onPosition(_player.position);
  }

  void _openSettings() {
    showModalBottomSheet<void>(
      context: context,
      builder: (_) => StatefulBuilder(
        builder: (context, setSheet) => SafeArea(
          child: Padding(
            padding: const EdgeInsets.fromLTRB(24, 0, 24, 20),
            child: Column(
              mainAxisSize: MainAxisSize.min,
              crossAxisAlignment: CrossAxisAlignment.start,
              children: [
                Row(
                  children: [
                    const Expanded(child: Text('Subtitle sync', style: TextStyle(fontSize: 16, fontWeight: FontWeight.w600))),
                    Text('${_offsetMs >= 0 ? '+' : ''}$_offsetMs ms', style: const TextStyle(color: Palette.accent, fontWeight: FontWeight.w600)),
                  ],
                ),
                const Text('Positive shows lines later, negative earlier.', style: TextStyle(color: Palette.muted, fontSize: 12.5)),
                Row(
                  children: [
                    IconButton(onPressed: () => _setOffset(_offsetMs - 50, setSheet), icon: const Icon(Icons.remove_circle_outline)),
                    Expanded(
                      child: Slider(min: -3000, max: 3000, divisions: 120, value: _offsetMs.clamp(-3000, 3000).toDouble(), onChanged: (v) => _setOffset(v.round(), setSheet)),
                    ),
                    IconButton(onPressed: () => _setOffset(_offsetMs + 50, setSheet), icon: const Icon(Icons.add_circle_outline)),
                  ],
                ),
                const SizedBox(height: 6),
                Row(
                  children: [
                    const Expanded(child: Text('Text size', style: TextStyle(fontSize: 16, fontWeight: FontWeight.w600))),
                    Text('${_fontSize.round()}', style: const TextStyle(color: Palette.accent, fontWeight: FontWeight.w600)),
                  ],
                ),
                Slider(
                  min: 14,
                  max: 44,
                  divisions: 30,
                  value: _fontSize,
                  onChanged: (v) {
                    setState(() => _fontSize = v);
                    setSheet(() {});
                  },
                  onChangeEnd: widget.config.setFontSize,
                ),
              ],
            ),
          ),
        ),
      ),
    );
  }

  // ------------------------------------------------------------------ UI
  @override
  Widget build(BuildContext context) {
    return Scaffold(
      body: DecoratedBox(
        decoration: BoxDecoration(gradient: Palette.glow(0.8)),
        child: SafeArea(
          child: Column(
            children: [
              _topBar(),
              if (_error != null) _Banner(_error!),
              if (_cuesError != null) _Banner('Could not load subtitles: $_cuesError'),
              if (!_loading) _tabs(),
              Expanded(
                child: _loading
                    ? const Center(child: CircularProgressIndicator())
                    : AnimatedSwitcher(duration: const Duration(milliseconds: 220), child: _tab == 0 ? _nowPlaying() : _transcript()),
              ),
              _controls(),
            ],
          ),
        ),
      ),
    );
  }

  Widget _topBar() => Padding(
        padding: const EdgeInsets.fromLTRB(4, 4, 4, 0),
        child: Row(
          children: [
            IconButton(onPressed: () => Navigator.of(context).maybePop(), icon: const Icon(Icons.keyboard_arrow_down_rounded, size: 32)),
            Expanded(
              child: Column(
                children: [
                  Text('PLAYING FROM', style: TextStyle(fontSize: 10.5, letterSpacing: 1.4, color: Palette.muted.withValues(alpha: 0.9))),
                  Text(widget.collection.name, maxLines: 1, overflow: TextOverflow.ellipsis, style: const TextStyle(fontWeight: FontWeight.w600)),
                ],
              ),
            ),
            IconButton(tooltip: 'Sync and text size', onPressed: _openSettings, icon: const Icon(Icons.tune_rounded)),
          ],
        ),
      );

  Widget _tabs() {
    Widget item(String label, int i) => Expanded(
          child: GestureDetector(
            behavior: HitTestBehavior.opaque,
            onTap: () => _setTab(i),
            child: AnimatedContainer(
              duration: const Duration(milliseconds: 200),
              padding: const EdgeInsets.symmetric(vertical: 9),
              decoration: BoxDecoration(color: _tab == i ? Palette.panelHi : Colors.transparent, borderRadius: BorderRadius.circular(14)),
              alignment: Alignment.center,
              child: Text(label, style: TextStyle(fontWeight: FontWeight.w600, color: _tab == i ? Palette.text : Palette.muted)),
            ),
          ),
        );
    return Container(
      margin: const EdgeInsets.fromLTRB(40, 8, 40, 4),
      padding: const EdgeInsets.all(4),
      decoration: BoxDecoration(color: Palette.panel, borderRadius: BorderRadius.circular(18)),
      child: Row(children: [item('Now playing', 0), item('Transcript', 1)]),
    );
  }

  Widget _nowPlaying() {
    return LayoutBuilder(
      key: const ValueKey('now'),
      builder: (context, box) {
        final art = math.max(110.0, math.min(box.maxWidth * 0.62, box.maxHeight * 0.36));
        return Column(
          children: [
            const SizedBox(height: 14),
            Hero(
              tag: 'cover-${widget.collection.id}',
              child: Container(
                width: art,
                height: art,
                decoration: BoxDecoration(
                  borderRadius: BorderRadius.circular(26),
                  boxShadow: [BoxShadow(color: Palette.accent.withValues(alpha: 0.25), blurRadius: 36, offset: const Offset(0, 14))],
                ),
                child: ClipRRect(
                  borderRadius: BorderRadius.circular(26),
                  child: CoverImage(api: widget.api, path: widget.collection.coverPath, name: widget.collection.name),
                ),
              ),
            ),
            Padding(
              padding: const EdgeInsets.fromLTRB(24, 14, 24, 0),
              child: Text(widget.track.title, maxLines: 2, overflow: TextOverflow.ellipsis, textAlign: TextAlign.center, style: const TextStyle(fontSize: 17, fontWeight: FontWeight.w700, height: 1.2)),
            ),
            Expanded(child: SubtitleView(cues: _cues, active: _active, mode: _mode, fontSize: _fontSize, hasSource: _hasSource)),
          ],
        );
      },
    );
  }

  Widget _transcript() {
    if (_cues.isEmpty) {
      return const Center(key: ValueKey('tr'), child: Text('No subtitles for this track.', style: TextStyle(color: Palette.muted)));
    }
    return Column(
      key: const ValueKey('tr'),
      children: [
        Padding(
          padding: const EdgeInsets.fromLTRB(20, 6, 12, 0),
          child: Row(
            children: [
              Expanded(
                child: ValueListenableBuilder<int?>(
                  valueListenable: _active,
                  builder: (context, a, _) => ValueListenableBuilder<int>(
                    valueListenable: _posMs,
                    builder: (context, ms, _) => Text(
                      '${_cues.length} lines  ·  ${(ms / 1000).toStringAsFixed(1)} s  ·  ${a == null ? 'between lines' : 'line ${a + 1}'}',
                      style: const TextStyle(color: Palette.muted, fontSize: 13),
                    ),
                  ),
                ),
              ),
              const Text('Follow', style: TextStyle(color: Palette.muted, fontSize: 13)),
              Switch(value: _follow, onChanged: (v) => setState(() => _follow = v)),
            ],
          ),
        ),
        Expanded(
          child: ValueListenableBuilder<int?>(
            valueListenable: _active,
            builder: (context, active, _) => ScrollablePositionedList.builder(
              itemScrollController: _scroll,
              itemCount: _cues.length,
              initialScrollIndex: active ?? 0,
              initialAlignment: 0.35,
              padding: const EdgeInsets.fromLTRB(12, 0, 12, 24),
              itemBuilder: (context, i) => _TranscriptRow(
                cue: _cues[i],
                on: i == active,
                mode: _mode,
                onTap: () => _seekToCue(i),
              ),
            ),
          ),
        ),
      ],
    );
  }

  Widget _controls() {
    return Container(
      padding: const EdgeInsets.fromLTRB(20, 6, 20, 10),
      decoration: BoxDecoration(
        color: Palette.bg.withValues(alpha: 0.85),
        border: const Border(top: BorderSide(color: Palette.border, width: 0.6)),
      ),
      child: Column(
        mainAxisSize: MainAxisSize.min,
        children: [
          _seekBar(),
          Row(
            mainAxisAlignment: MainAxisAlignment.spaceBetween,
            children: [
              _icon(Icons.skip_previous_rounded, 'Previous line', () => _jumpCue(-1), 34),
              _icon(Icons.replay_10_rounded, 'Back 10 s', () => _seekBy(-10000), 32),
              _playButton(),
              _icon(Icons.forward_10_rounded, 'Forward 10 s', () => _seekBy(10000), 32),
              _icon(Icons.skip_next_rounded, 'Next line', () => _jumpCue(1), 34),
            ],
          ),
          const SizedBox(height: 4),
          Row(
            mainAxisAlignment: MainAxisAlignment.center,
            children: [
              PopupMenuButton<double>(
                tooltip: 'Speed',
                initialValue: _player.speed,
                onSelected: (v) => setState(() => _player.setSpeed(v)),
                itemBuilder: (_) => [for (final s in _speeds) PopupMenuItem(value: s, child: Text('$s×'))],
                child: _Pill(Icons.speed_rounded, '${_player.speed}×'),
              ),
              const SizedBox(width: 10),
              PopupMenuButton<String>(
                tooltip: 'Subtitle language',
                initialValue: _mode,
                onSelected: _setMode,
                itemBuilder: (_) => [for (final e in _modes.entries) PopupMenuItem(value: e.key, child: Text(e.value))],
                child: _Pill(Icons.translate_rounded, _modeShort[_mode] ?? _mode),
              ),
              const SizedBox(width: 10),
              GestureDetector(onTap: _openSettings, child: _Pill(Icons.av_timer_rounded, '${_offsetMs >= 0 ? '+' : ''}$_offsetMs ms')),
            ],
          ),
        ],
      ),
    );
  }

  Widget _icon(IconData icon, String tip, VoidCallback onTap, double size) =>
      IconButton(tooltip: tip, onPressed: onTap, iconSize: size, color: Palette.text, icon: Icon(icon));

  Widget _playButton() => StreamBuilder<PlayerState>(
        stream: _player.playerStateStream,
        builder: (context, snap) {
          final st = snap.data;
          final loading = st?.processingState == ProcessingState.loading || st?.processingState == ProcessingState.buffering;
          final playing = st?.playing ?? false;
          final disabled = !widget.track.hasAudio || (_error != null && !playing);
          return GestureDetector(
            onTap: disabled ? null : (playing ? _player.pause : _player.play),
            child: Container(
              width: 68,
              height: 68,
              decoration: BoxDecoration(
                gradient: disabled ? null : Palette.accentGradient,
                color: disabled ? Palette.panelHi : null,
                shape: BoxShape.circle,
                boxShadow: disabled ? null : [BoxShadow(color: Palette.accent.withValues(alpha: 0.4), blurRadius: 20, offset: const Offset(0, 6))],
              ),
              alignment: Alignment.center,
              child: loading && playing
                  ? const SizedBox(width: 28, height: 28, child: CircularProgressIndicator(strokeWidth: 3, color: Color(0xFF1A1030)))
                  : Icon(playing ? Icons.pause_rounded : Icons.play_arrow_rounded, size: 40, color: disabled ? Palette.muted : const Color(0xFF1A1030)),
            ),
          );
        },
      );

  Widget _seekBar() => StreamBuilder<Duration?>(
        stream: _player.durationStream,
        builder: (context, durSnap) {
          final dur = durSnap.data ?? Duration.zero;
          return StreamBuilder<Duration>(
            stream: _player.positionStream,
            builder: (context, posSnap) {
              final pos = posSnap.data ?? Duration.zero;
              final max = dur.inMilliseconds.toDouble();
              final value = _dragging ? _dragValue : pos.inMilliseconds.toDouble().clamp(0, max <= 0 ? 1 : max).toDouble();
              return Row(
                children: [
                  SizedBox(width: 44, child: Text(formatClock(Duration(milliseconds: value.round())), style: const TextStyle(color: Palette.muted, fontSize: 12))),
                  Expanded(
                    child: Slider(
                      min: 0,
                      max: max <= 0 ? 1 : max,
                      value: value,
                      onChangeStart: (v) => setState(() {
                        _dragging = true;
                        _dragValue = v;
                      }),
                      onChanged: (v) => setState(() => _dragValue = v),
                      onChangeEnd: (v) {
                        _player.seek(Duration(milliseconds: v.round())).then((_) => _onPosition(_player.position));
                        setState(() => _dragging = false);
                      },
                    ),
                  ),
                  SizedBox(width: 44, child: Text(formatClock(dur), textAlign: TextAlign.right, style: const TextStyle(color: Palette.muted, fontSize: 12))),
                ],
              );
            },
          );
        },
      );
}

class _Pill extends StatelessWidget {
  const _Pill(this.icon, this.label);

  final IconData icon;
  final String label;

  @override
  Widget build(BuildContext context) => Container(
        padding: const EdgeInsets.symmetric(horizontal: 12, vertical: 8),
        decoration: BoxDecoration(color: Palette.panel, borderRadius: BorderRadius.circular(20), border: Border.all(color: Palette.border, width: 0.8)),
        child: Row(
          mainAxisSize: MainAxisSize.min,
          children: [
            Icon(icon, size: 16, color: Palette.accent),
            const SizedBox(width: 6),
            Text(label, style: const TextStyle(fontSize: 12.5, fontWeight: FontWeight.w600)),
          ],
        ),
      );
}

class _Banner extends StatelessWidget {
  const _Banner(this.text);

  final String text;

  @override
  Widget build(BuildContext context) => Container(
        width: double.infinity,
        margin: const EdgeInsets.fromLTRB(16, 6, 16, 0),
        padding: const EdgeInsets.symmetric(horizontal: 14, vertical: 10),
        decoration: BoxDecoration(color: Palette.error.withValues(alpha: 0.12), borderRadius: BorderRadius.circular(12)),
        child: Text(text, style: const TextStyle(color: Palette.error, fontSize: 13)),
      );
}

/// The current line, big, with a soft cross-fade between lines. The original-language line gets its own, readable row.
class SubtitleView extends StatelessWidget {
  const SubtitleView({super.key, required this.cues, required this.active, required this.mode, required this.fontSize, required this.hasSource});

  final List<Cue> cues;
  final ValueNotifier<int?> active;
  final String mode;
  final double fontSize;
  final bool hasSource;

  @override
  Widget build(BuildContext context) {
    final wantsSource = mode != 'en';
    return Padding(
      padding: const EdgeInsets.fromLTRB(22, 6, 22, 10),
      child: Column(
        children: [
          if (cues.isEmpty)
            const Padding(
              padding: EdgeInsets.only(bottom: 6),
              child: Text('No subtitle lines were loaded for this track.', textAlign: TextAlign.center, style: TextStyle(color: Palette.muted, fontSize: 12.5)),
            ),
          if (wantsSource && cues.isNotEmpty && !hasSource)
            const Padding(
              padding: EdgeInsets.only(bottom: 6),
              child: Text('No original-language text was saved for this track.', textAlign: TextAlign.center, style: TextStyle(color: Palette.muted, fontSize: 12.5)),
            ),
          Expanded(
            child: ValueListenableBuilder<int?>(
              valueListenable: active,
              builder: (context, i, _) => Center(
                child: SingleChildScrollView(
                  child: AnimatedSwitcher(
                    duration: const Duration(milliseconds: 220),
                    transitionBuilder: (child, anim) => FadeTransition(
                      opacity: anim,
                      child: SlideTransition(position: Tween(begin: const Offset(0, 0.06), end: Offset.zero).animate(anim), child: child),
                    ),
                    child: i == null ? const SizedBox(key: ValueKey('gap'), height: 1) : _line(cues[i], i),
                  ),
                ),
              ),
            ),
          ),
        ],
      ),
    );
  }

  Widget _line(Cue c, int i) {
    final showEn = mode != 'src';
    final showSrc = mode != 'en' && c.src.isNotEmpty;
    final srcSize = mode == 'src' ? fontSize : math.max(15.0, fontSize * 0.78);
    return Column(
      key: ValueKey(i),
      mainAxisSize: MainAxisSize.min,
      children: [
        if (showEn && c.en.isNotEmpty)
          Text(c.en, textAlign: TextAlign.center, style: TextStyle(fontSize: fontSize, fontWeight: FontWeight.w700, height: 1.28, letterSpacing: -0.2)),
        if (showEn && showSrc) const SizedBox(height: 12),
        if (showSrc)
          Text(
            c.src,
            textAlign: TextAlign.center,
            style: TextStyle(
              fontSize: srcSize,
              height: 1.35,
              fontWeight: mode == 'src' ? FontWeight.w700 : FontWeight.w500,
              color: mode == 'src' ? Palette.text : Palette.accent.withValues(alpha: 0.92),
              fontFamilyFallback: cjkFallback,
            ),
          ),
      ],
    );
  }
}

class _TranscriptRow extends StatelessWidget {
  const _TranscriptRow({required this.cue, required this.on, required this.mode, required this.onTap});

  final Cue cue;
  final bool on;
  final String mode;
  final VoidCallback onTap;

  @override
  Widget build(BuildContext context) {
    final showEn = mode != 'src';
    final showSrc = mode != 'en' && cue.src.isNotEmpty;
    return GestureDetector(
      behavior: HitTestBehavior.opaque,
      onTap: onTap,
      child: AnimatedContainer(
        duration: const Duration(milliseconds: 220),
        margin: const EdgeInsets.symmetric(vertical: 3),
        padding: const EdgeInsets.fromLTRB(14, 12, 14, 12),
        decoration: BoxDecoration(
          color: on ? Palette.accent.withValues(alpha: 0.14) : Colors.transparent,
          borderRadius: BorderRadius.circular(16),
          border: Border.all(color: on ? Palette.accent.withValues(alpha: 0.5) : Colors.transparent),
        ),
        child: Opacity(
          opacity: on ? 1 : 0.62,
          child: Column(
            crossAxisAlignment: CrossAxisAlignment.start,
            children: [
              Text(formatClock(Duration(milliseconds: cue.startMs)), style: TextStyle(fontSize: 11.5, fontWeight: FontWeight.w600, color: on ? Palette.accent : Palette.muted)),
              const SizedBox(height: 4),
              if (showEn) Text(cue.en.isEmpty ? '…' : cue.en, style: TextStyle(fontSize: 16.5, height: 1.3, fontWeight: on ? FontWeight.w700 : FontWeight.w500)),
              if (showSrc) ...[
                if (showEn) const SizedBox(height: 4),
                Text(cue.src, style: TextStyle(fontSize: 14.5, height: 1.3, color: showEn ? Palette.muted : Palette.text, fontFamilyFallback: cjkFallback)),
              ],
            ],
          ),
        ),
      ),
    );
  }
}
