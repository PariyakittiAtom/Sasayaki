import 'package:flutter_test/flutter_test.dart';
import 'package:sasayaki_mobile/pages/login_page.dart';

void main() {
  test('pasted links are reduced to the project address', () {
    for (final pasted in [
      'https://abcd1234.supabase.co',
      'https://abcd1234.supabase.co/',
      ' https://abcd1234.supabase.co/rest/v1/ ',
      'abcd1234.supabase.co',
    ]) {
      expect(cleanProjectUrl(pasted), 'https://abcd1234.supabase.co', reason: pasted);
    }
    expect(cleanProjectUrl(''), '');
  });
}
