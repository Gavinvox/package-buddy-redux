import 'package:flutter_test/flutter_test.dart';
import 'package:packagebuddy/updater.dart';

void main() {
  test('isNewerVersion compares dotted versions', () {
    expect(isNewerVersion('0.4.0', '0.3.0'), isTrue);
    expect(isNewerVersion('v0.4.0', '0.4.0'), isFalse);
    expect(isNewerVersion('0.3.9', '0.4.0'), isFalse);
    expect(isNewerVersion('1.0.0', '0.9.9'), isTrue);
    expect(isNewerVersion('0.4.1', '0.4.0'), isTrue);
  });
}
