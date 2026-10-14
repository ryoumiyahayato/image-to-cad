# TEXT_STYLE_CANDIDATE_MATRIX

Result: **P2_REPRESENTATION_BLOCKER — STOP condition 3**.

There is no existing font tested on this machine that simultaneously supplies
the required simplified Chinese coverage, improves the hollow appearance, and
renders correctly as native editable TEXT in the installed LibreCAD.
This is a bounded result for these installed resources and renderer, not a claim
that DXF cannot carry editable Chinese text in other CAD applications.

Each comparison DXF contains 电施, 图纸目录, 项目编号, Project Name,
Design Institute, 1, 7, 01, 2024.8.15, and ®. TEXT height = 5 mm,
width factor = 1; no OCR fitting or source-image overlay is involved.
Every DXF uses native TEXT. Visible plotting attributes are identical:
black true color, 0.13 mm lineweight. Resources were neither installed nor removed.

| Candidate | CAD readability in actual LibreCAD | Chinese coverage | Latin | Digits | Appearance | Native editability | Portability risk | Missing-font / fallback behavior |
| --- | --- | --- | --- | --- | --- | --- | --- | --- |
| Existing project wqy-unicode.lff | Readable, retains the reported hollow defect | All tested Chinese | All tested | All tested | Closed outlines stroked; hollow | YES | Requires the LFF in the CAD font directory; other CAD renderers unverified | Missing-resource control falls back to standard; Chinese becomes diamonds |
| Installed unicode.lff | Latin/digits readable; Chinese corrupt | Missing 电图纸录项编 | All tested | All tested | Stroke | YES | Requires corresponding installed LFF; insufficient Chinese repertoire | Actual missing Chinese glyphs are diamonds |
| Installed kst32b.lff | Latin/digits readable; Chinese corrupt | Missing 电图纸录项编 | All tested | All tested | Stroke | YES | Japanese repertoire; insufficient simplified Chinese; not project-bundled | Actual missing Chinese glyphs are diamonds |
| Installed iso3098.lff | Latin/digits readable; Chinese corrupt | Missing 电施图纸目录项编号 | All tested | All tested | Stroke | YES | Requires LFF; no useful coverage of the test phrases | Missing Chinese glyphs are diamonds |
| System simhei.ttf, style simhei | Actual Chinese unreadable despite available TTF glyphs | File covers all test Chinese; LibreCAD falls back and displays diamonds | Fallback Latin readable | Fallback digits readable | Actual standard stroke fallback, not filled SimHei | YES, but intended font not rendered | System font license does not authorize redistribution; renderer ignores this native TTF reference | Actual body pixels identical to standard and missing-font control |
| System simhei.ttf, style simhei.ttf | Same as simhei style-name variant | Same | Same | Same | Same fallback | YES | Same | Identical fallback body hash |
| System arial.ttf | Chinese unreadable | File lacks test Chinese; actual fallback also lacks Chinese | Fallback Latin readable | Fallback digits readable | Standard stroke fallback | YES | System font redistribution not introduced | Identical fallback body hash |
| System NotoSansSC-VF.ttf | Actual Chinese unreadable despite full glyph repertoire | File covers every requested glyph; actual fallback displays diamonds | Fallback Latin readable | Fallback digits readable | Standard stroke fallback, not the installed Noto face | YES | No font bundled or converted; intended native TTF not rendered here | Identical fallback body hash |
| Installed standard.lff | Latin/digits readable; Chinese unreadable | Missing 电施图纸目录项编号 | All tested | All tested | Stroke | YES | Default fallback repertoire lacks Chinese | Baseline for fallback comparison |
| Deliberately missing p2_missing_font.ttf | Latin/digits readable; Chinese unreadable | No resource | Fallback readable | Fallback readable | Standard stroke fallback | YES | Deliberately unavailable control | Exact same body hash as all four TTF experiments |

® exists in the tested LFF fonts, Arial, and system Noto. SimHei's own cmap
lacks ®; the visible ® in that experiment comes from the fallback.
No face was silently substituted in the measurement code.

All 47 installed LFF files were indexed for the requested characters. Only
wqy-unicode.lff covers all requested Chinese (and all requested characters).
See `installed-lff-inventory.json` for the complete resource inventory and hashes.

The project manifest declares four OFL Noto CJK OTF resources, but **none of the
four actual OTF files is present** in this checkout. A declaration or download URL
is not a usable bundled font. The actual bundled Unicode LFF and its license
files are present. No font was downloaded, copied into the project, or converted.
See `project-font-manifest-availability.json`.

## Actual native CAD render evidence

The existing LibreCAD executable rendered all ten unmodified comparison DXFs to
PDF with its native `dxf2pdf` engine. Poppler rendered those PDFs to PNG at 180 DPI.
All final render commands succeeded; final Poppler logs are empty. Each DXF has
10 sample TEXT entities plus a standard-font experiment label. None contains
IMAGE or glyph POLYLINE replacements. PDF/PNG are diagnostic renders only.

After removing only the label region, each body crop is 843 x 795 pixels.
The native render body SHA-256 for simhei, simhei.ttf, arial, NotoSansSC-VF,
standard, and p2_missing_font is identical:

`2d69ceabccf70b9cf81423a742cf5515ed75ebd763364f39d18d515c335d332c`

The wqy body has a different hash and visibly hollow complete Chinese/Latin/digits:

`251f0fd97c80069770f45768292ed1d05b963fd62e8eff49e6d334cc60416aef`

These are actual native LibreCAD renders; the experiment never draws substitute
text through Qt, PIL, a browser, ezdxf's drawing frontend, or a system-font preview.
PIL only crops/composes the already-rendered PNG evidence without enhancement.
Measurements and exact native commands are in `matrix-measurements.json`.

The Computer Use helper returned an occluded LibreCAD capture, then failed both
the initial activation and the one allowed recovery activation with
`failed to activate captured window`. GUI input stopped. Consequently the
experiment makes **no claim of GUI text editing or display-bbox acceptance**.
The native CAD render is the installed application's PDF rendering engine.

ODA File Converter 27.1.0 exists. No ODA renderer/viewer executable was found in
the installed ODA directory. The converter cannot establish appearance. ODA
render was not run, and converter success is not counted as font acceptance.

Local runtime artifacts:
`local-artifacts/product-fix-p2/font-experiment/` contains comparison DXFs,
native PDFs, PNGs, a contact sheet, render logs, and editable-text save/reopen
copies. These heavy artifacts are ignored by Git.

Official LibreCAD references (used to verify the console entry point and font
resources):

- https://docs.librecad.org/en/latest/guides/console-tool.html
- https://docs.librecad.org/en/latest/appx/fonts.html
- https://dokuwiki.librecad.org/doku.php/community:fonts

The blocker conclusion follows from the local comparison and inventory, not from
the availability of an online TTF conversion service.
