# Legacy Axis Twist runtime compatibility

These three runtime files remain at their historical paths so existing printer
symlinks keep working after an installer update and restart. Do not delete or
relocate them as part of retiring the install option. No installer script or new
install option is provided here.

Keeping ATC installed is the user's choice. Updates and **Apply all recommended
updates** do not remove it, clear its calibration, or require its removal.

To remove an existing installation explicitly, use **Optional extras → Remove
legacy Axis Twist**. That entry appears only while legacy ATC is detected and
disappears after successful removal. See the [removal guide](../../installer/extras/axis-twist-removal/README.md)
for backups, firmware matching, Cartographer handling, and restart requirements.
