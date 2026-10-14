# P2C static Regular derivation review — before generating B

The exact source is the unmodified Google Fonts file declared in
`font-candidate.json`, SHA256
`a3041811a78c361b1de50f953c805e0244951c21c5bd412f7232ef0d899af0da`.
Its accompanying OFL.txt SHA256 is
`1c05c68c34f9708415aada51f17e1b0092d2cea709bf4a94cd38114f9e73d7d9`.
Both were checked before this review. The font and license's copyright notice
declare **Source** as the Reserved Font Name.

OFL 1.1 permits modifying the font under its conditions. A static instantiation
and changed names are a Modified Version. Condition 2 requires the copyright
notice and license to accompany redistribution; condition 3 prohibits the
reserved name in a modified font's primary user-facing name without permission;
condition 4 prohibits using author names to endorse the derivative; condition 5
keeps the font under OFL. The original copyright and license metadata must stay.
Reference: [official OFL modification guidance](https://openfontlicense.org/how-to-modify-ofl-fonts/)
and [OFL FAQ](https://openfontlicense.org/ofl-faq/), alongside the exact source
OFL.txt in this directory. These summaries do not replace the full license.

The approved preparation is a static **wght=400** instance made with the existing
FontTools instancer. Its independent primary family is **ITC CAD SC**, style
**Regular**, filename **ITCCADSC-Regular.ttf**, PostScript name
**ITCCADSC-Regular**. Primary family/full/PostScript/grouping names are rewritten
consistently, removing ambiguity with existing Noto families and avoiding the
reserved word. It is identified as a derivative, not an official Noto release.
The original source, checksum, instantiation coordinate, FontTools version,
output checksum, rename details, and coverage must be recorded in a FONTLOG.
OFL.txt must accompany the file. Copyright and license fields remain intact.

This review authorizes preparation and local testing of B within the user's
explicit task. It does **not** approve production bundling or choosing B as the
default before actual CAD loading, substitution, rendering, and sizing checks.
No glyph is to be written into CAD geometry or replaced with raster text.
No production font resource or installer is changed by the experiment.
