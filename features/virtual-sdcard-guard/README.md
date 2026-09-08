# Virtual SD-card upload guard

Creality's upload path can intermittently append the closing HTTP multipart
delimiter to the G-code stored on the printer. Klipper then attempts to execute
that final line and reports an `Unknown command` after the real print has ended.

This component patches the installed `virtual_sdcard.py` reader. It ignores a
line only when all of these conditions are true:

- it is the physical final line in the selected file;
- it begins with at least 20 hyphens;
- its token is 16 to 64 hexadecimal characters; and
- it ends with the multipart closing `--` marker.

The stored file is not rewritten. When a contaminated ending is suppressed,
Klipper emits `[VIRTUAL_SDCARD]: Ignored trailing multipart upload boundary`.
All other unknown commands retain their normal behavior.
