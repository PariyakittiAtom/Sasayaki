import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:sasayaki_mobile/models.dart';
import 'package:sasayaki_mobile/pages/player_page.dart';

const cues = [
  Cue(idx: 0, startMs: 0, endMs: 2000, src: 'こんにちは、先輩', en: 'Hello, senpai'),
  Cue(idx: 1, startMs: 2000, endMs: 4000, src: '', en: 'Only English here'),
];

Widget host(String mode, {int? at = 0, List<Cue> list = cues}) => MaterialApp(
      home: Scaffold(
        body: SizedBox(
          height: 400,
          child: SubtitleView(cues: list, active: ValueNotifier<int?>(at), mode: mode, fontSize: 22, hasSource: list.any((c) => c.src.isNotEmpty)),
        ),
      ),
    );

void main() {
  liveTests();
  testWidgets('both mode shows the English line and the original line', (t) async {
    await t.pumpWidget(host('both'));
    await t.pumpAndSettle();
    expect(find.text('Hello, senpai'), findsOneWidget);
    expect(find.text('こんにちは、先輩'), findsOneWidget);
  });

  testWidgets('original-only mode hides English', (t) async {
    await t.pumpWidget(host('src'));
    await t.pumpAndSettle();
    expect(find.text('こんにちは、先輩'), findsOneWidget);
    expect(find.text('Hello, senpai'), findsNothing);
  });

  testWidgets('English mode hides the original', (t) async {
    await t.pumpWidget(host('en'));
    await t.pumpAndSettle();
    expect(find.text('Hello, senpai'), findsOneWidget);
    expect(find.text('こんにちは、先輩'), findsNothing);
  });

  testWidgets('says so when a track has no original text at all', (t) async {
    await t.pumpWidget(host('both', at: 0, list: const [Cue(idx: 0, startMs: 0, endMs: 2000, src: '', en: 'Only English here')]));
    await t.pumpAndSettle();
    expect(find.textContaining('No original-language text'), findsOneWidget);
  });
}

void liveTests() {
  testWidgets('a line appears when it becomes active while playing, and changes with the next', (t) async {
    final active = ValueNotifier<int?>(null);
    await t.pumpWidget(MaterialApp(
      home: Scaffold(
        body: SizedBox(height: 400, child: SubtitleView(cues: cues, active: active, mode: 'both', fontSize: 22, hasSource: true)),
      ),
    ));
    expect(find.text('Hello, senpai'), findsNothing);
    active.value = 0;
    await t.pump(const Duration(milliseconds: 50));
    await t.pumpAndSettle();
    expect(find.text('Hello, senpai'), findsOneWidget);
    active.value = 1;
    await t.pumpAndSettle();
    expect(find.text('Only English here'), findsOneWidget);
    expect(find.text('Hello, senpai'), findsNothing);
    active.value = null;
    await t.pumpAndSettle();
    expect(find.text('Only English here'), findsNothing);
  });
}
