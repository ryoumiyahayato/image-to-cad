# Font metrics audit

All 436 selected TEXT entities use STYLE `wqy-unicode` -> `wqy-unicode.lff`, style width 1.0 and oblique 0. The bundled font is `wqy-unicode.lff` (43717474 bytes), WenQuanYi Micro Hei Mono Light, LetterSpacing 3, WordSpacing 6.75.

Canonical metrics parse the exact LFF visible bounds; all selected entities report `librecad-lff-visible-bounds` and no fallback. Live user LibreCAD font resolution/substitution cannot be inspected here. Substitution is secondary because intended-font metrics already show overflow.
