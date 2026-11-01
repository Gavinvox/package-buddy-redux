// One package in a list: a carrier-colored band on top, details below, day count or check on the right.
import 'package:flutter/material.dart';

import '../models.dart';
import '../theme.dart';

class CarrierBand extends StatelessWidget {
  const CarrierBand({super.key, required this.pkg, this.height = 28, this.big = false});
  final Pkg pkg;
  final double height;
  final bool big;
  @override
  Widget build(BuildContext context) {
    final band = carrierBand(pkg.carrierCode, pkg.carrierName);
    return Container(
      height: height,
      color: band.bg,
      padding: const EdgeInsets.symmetric(horizontal: 10),
      child: Row(children: [
        Tooltip(
          message: pkg.sending ? 'Sending' : 'Receiving',
          child: Icon(pkg.sending ? Icons.arrow_forward : Icons.arrow_back, color: band.fg, size: height * 0.8),
        ),
        const Spacer(),
        Flexible(
          flex: 8,
          child: Text(pkg.carrierName,
              overflow: TextOverflow.ellipsis,
              style: TextStyle(
                  color: band.fg, fontSize: big ? 20 : height * 0.68, fontFamily: 'RobotoCondensed', fontWeight: FontWeight.w400)),
        ),
      ]),
    );
  }
}

class PackageRow extends StatelessWidget {
  const PackageRow({super.key, required this.pkg, required this.onTap, this.selected = false});
  final Pkg pkg;
  final VoidCallback onTap;
  final bool selected;

  @override
  Widget build(BuildContext context) {
    final theme = Theme.of(context);
    final b = theme.brightness;
    final dark = b == Brightness.dark;
    final muted = dark ? const Color(0xFFA9B1BD) : const Color(0xFF5F5F5F);
    final bg = selected
        ? (dark ? const Color(0xFF1C2D47) : const Color(0xFFD5E4F7))
        : theme.colorScheme.surfaceContainer;

    final title = pkg.description.isNotEmpty ? pkg.description : pkg.number;
    final String line2;
    if (pkg.delivered) {
      line2 = 'Delivered: ${fmtWhen(pkg.deliveredAt ?? pkg.lastEventTime)}';
    } else if (pkg.eta != null && pkg.eta!.isNotEmpty) {
      line2 = 'ETA: ${fmtWhen(pkg.eta, time: false)}';
    } else {
      line2 = pkg.stateLabel;
    }
    final loc = [
      if ((pkg.lastLocation ?? '').isNotEmpty) pkg.lastLocation!,
      if ((pkg.lastEventTime ?? '').isNotEmpty) fmtWhen(pkg.lastEventTime),
    ].join(' - ');
    var status = _statusLine();
    if (status.trim().toLowerCase() == line2.trim().toLowerCase()) status = '';

    return Material(
      color: bg,
      child: InkWell(
        onTap: onTap,
        child: Column(crossAxisAlignment: CrossAxisAlignment.stretch, children: [
          CarrierBand(pkg: pkg),
          Padding(
            padding: const EdgeInsets.fromLTRB(10, 6, 8, 8),
            child: Row(crossAxisAlignment: CrossAxisAlignment.center, children: [
              Expanded(
                child: Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
                  Text(title,
                      maxLines: 1,
                      overflow: TextOverflow.ellipsis,
                      style: theme.textTheme.titleMedium!.copyWith(fontWeight: FontWeight.w700, fontSize: 18)),
                  if (pkg.description.isNotEmpty)
                    Text(pkg.number,
                        maxLines: 1,
                        overflow: TextOverflow.ellipsis,
                        style: TextStyle(color: muted, fontSize: 13.5, letterSpacing: 0.4, fontWeight: FontWeight.w500)),
                  const SizedBox(height: 2),
                  Text(line2, style: TextStyle(fontWeight: FontWeight.w300, fontSize: 15, color: theme.colorScheme.onSurface)),
                  if (loc.isNotEmpty)
                    Text(loc.toUpperCase(),
                        maxLines: 1,
                        overflow: TextOverflow.ellipsis,
                        style: TextStyle(fontFamily: 'RobotoCondensed', fontSize: 12.5, color: muted)),
                  if (status.isNotEmpty)
                    Text(status,
                        maxLines: 2,
                        overflow: TextOverflow.ellipsis,
                        style: TextStyle(fontWeight: FontWeight.w400, fontSize: 15, color: stateColor(pkg.state, b))),
                ]),
              ),
              const SizedBox(width: 8),
              SizedBox(width: 64, child: _right(context)),
            ]),
          ),
        ]),
      ),
    );
  }

  String _statusLine() {
    if (pkg.mode == 'not_tracked') return 'Saved only (not tracked)';
    if (pkg.mode == 'awaiting_approval') return 'Waiting for admin approval';
    if (pkg.mode == 'rejected') return 'Not approved for tracking';
    if (pkg.unsupported) return 'Carrier not available via 17TRACK';
    final t = pkg.statusText ?? '';
    if (t.isNotEmpty && !pkg.delivered) return t;
    return pkg.delivered ? 'Delivered' : pkg.stateLabel;
  }

  Widget _right(BuildContext context) {
    final b = Theme.of(context).brightness;
    if (pkg.delivered) {
      return Icon(Icons.check_rounded, size: 48, color: b == Brightness.dark ? deliveredDark : deliveredLight);
    }
    if (pkg.unsupported) {
      return Tooltip(
          message: 'Open on carrier site from the details',
          child: Icon(Icons.open_in_new, size: 30, color: stateColor(pkg.state, b)));
    }
    if (pkg.state == 'exception') {
      return Icon(Icons.warning_amber_rounded, size: 40, color: stateColor(pkg.state, b));
    }
    final d = pkg.days;
    if (d == null) {
      return Icon(pkg.mode == 'tracked' ? Icons.hourglass_empty : Icons.pause_circle_outline,
          size: 30, color: stateColor('pending', b));
    }
    return Column(mainAxisSize: MainAxisSize.min, children: [
      Text('$d', style: const TextStyle(fontSize: 44, height: 1.0, fontWeight: FontWeight.w300)),
      Text(d == 1 ? 'day' : 'days', style: const TextStyle(fontSize: 14, fontWeight: FontWeight.w300)),
    ]);
  }
}
