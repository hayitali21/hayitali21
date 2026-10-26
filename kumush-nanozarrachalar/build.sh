#!/bin/sh
# lab.html -> index.html (GitHub uchun to'liq HTML hujjat)
cd "$(dirname "$0")"
{ printf '<!doctype html>\n<html lang="uz">\n<head>\n<meta charset="utf-8">\n<meta name="viewport" content="width=device-width, initial-scale=1, viewport-fit=cover">\n</head>\n<body>\n'; cat lab.html; printf '\n</body>\n</html>\n'; } > index.html
