import 'dart:io';
import 'dart:typed_data';

import 'package:file_picker/file_picker.dart';

/// Asks where to save (Android, Linux) and writes the file.
Future<String?> saveBytes(String filename, Uint8List bytes, String mime) async {
  final uri = await FilePicker.saveFile(fileName: filename, bytes: bytes, mimeType: mime);
  if (uri == null) return null;
  if (uri.scheme == 'file') {
    final f = File(uri.toFilePath());
    if (!f.existsSync() || f.lengthSync() == 0) await f.writeAsBytes(bytes);
    return f.path;
  }
  return uri.toString();
}
