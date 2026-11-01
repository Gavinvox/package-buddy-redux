import 'dart:js_interop';
import 'dart:typed_data';

import 'package:web/web.dart' as web;

/// Starts a browser download. Returns a short description of where it went.
Future<String?> saveBytes(String filename, Uint8List bytes, String mime) async {
  final blob = web.Blob([bytes.toJS].toJS, web.BlobPropertyBag(type: mime));
  final url = web.URL.createObjectURL(blob);
  final a = web.HTMLAnchorElement()
    ..href = url
    ..download = filename;
  web.document.body?.append(a);
  a.click();
  a.remove();
  web.URL.revokeObjectURL(url);
  return 'your browser\'s Downloads folder';
}
