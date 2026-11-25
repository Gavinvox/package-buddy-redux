Local copy of tray_manager 0.5.3 with Linux StatusNotifier fixes:

- Indicator id is the stable name `packagebuddy-redux` (not a random shortid or the GTK application id).
- setTitle() calls app_indicator_set_title() (the StatusNotifier Title) instead of set_label() (text beside the icon).
- setToolTip() is implemented on Linux: it sets Title and, when libayatana 0.6+ is present, tooltip-title as well.
