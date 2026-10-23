import 'package:flutter_test/flutter_test.dart';
import 'package:sasayaki_mobile/models.dart';

void main() {
  const cues = [
    Cue(idx: 0, startMs: 1000, endMs: 2000, src: 'a', en: 'A'),
    Cue(idx: 1, startMs: 2500, endMs: 4000, src: 'b', en: 'B'),
    Cue(idx: 2, startMs: 4000, endMs: 4500, src: 'c', en: 'C'),
  ];

  test('finds the line showing at a position', () {
    expect(activeCueIndex(cues, 1000), 0);
    expect(activeCueIndex(cues, 1999), 0);
    expect(activeCueIndex(cues, 3000), 1);
    expect(activeCueIndex(cues, 4000), 2); // back-to-back lines switch exactly at the boundary
  });

  test('is null before the first line and in gaps', () {
    expect(activeCueIndex(cues, 0), isNull);
    expect(activeCueIndex(cues, 2200), isNull);
    expect(activeCueIndex(cues, 4500), isNull);
    expect(activeCueIndex(const [], 100), isNull);
  });

  test('parses a synced row', () {
    final c = Cue.fromJson({'idx': 3, 'start_ms': 10, 'end_ms': 20, 'src_text': null, 'en_text': 'Hi'});
    expect((c.idx, c.startMs, c.endMs, c.src, c.en), (3, 10, 20, '', 'Hi'));
  });

  test('formats clock', () {
    expect(formatClock(const Duration(seconds: 65)), '1:05');
    expect(formatClock(const Duration(seconds: 3725)), '1:02:05');
  });
}
