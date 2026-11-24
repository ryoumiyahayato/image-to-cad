"""One immutable, optional technical font for source-constrained single rows."""

SOURCE_ROW_FONT = {
    "profile": "osifont-lgpl3fe-2e9aa86a",
    "upstream_commit": "2e9aa86a8a09b044e08c00f5a4a2505dc3ca9f6e",
    "source_url": "https://raw.githubusercontent.com/hikikomori82/osifont/"
    "2e9aa86a8a09b044e08c00f5a4a2505dc3ca9f6e/osifont-lgpl3fe.ttf",
    "font": {
        "file": "osifont-lgpl3fe.ttf",
        "bytes": 126556,
        "sha256": "81880ba0a1ba2e15752f5ec536f227a69bec98b73ae8200780804b66750320b6",
    },
    "license": {
        "file": "osifont-lgpl3fe.LICENSE.txt",
        "bytes": 44531,
        "sha256": "54c7920e41a69b52f3ee4369721432319962d4e72f35708ec2988c62f8850292",
    },
    "style": "I2CAD_SOURCE_ROW",
    "export_license": "FONT_LICENSE_osifont.txt",
}

SOURCE_ROW_DERIVATIVE = {
    "profile": "osifont-cad-metrics-v1-2e9aa86a",
    "derivation": "uniform-whole-font-CAD-metrics-v1",
    "source_profile": SOURCE_ROW_FONT["profile"],
    "font": {
        "file": "osifont-cad-metrics.ttf",
        "bytes": 166372,
        "sha256": "447f7edab80cf96ee4848f141bde491ebb973bbee4b03017c120c38fb9032e4d",
    },
    "lff": {
        "file": "I2CAD_SOURCE_ROW.lff",
        "bytes": 6928277,
        "sha256": "63615cd5eb628459ff4c4a17157af4fd69ff681e04c333e352e4171e474ceea1",
    },
    "license": {
        "file": "osifont-cad-metrics.LICENSE.txt",
        "bytes": 46456,
        "sha256": "2851b614f1375a9c0969a1dbd39561f84bcdce0bb1ceeeb15a12a92553d77e92",
    },
    "style": "I2CAD_SOURCE_ROW",
    "export_license": "FONT_LICENSE_I2CAD_SOURCE_ROW.txt",
}

FONT_SPEC = {
    "profile": SOURCE_ROW_DERIVATIVE["profile"],
    "derivation": SOURCE_ROW_DERIVATIVE["derivation"],
    "source_profile": SOURCE_ROW_DERIVATIVE["source_profile"],
    "font": SOURCE_ROW_DERIVATIVE["font"]["file"],
    "sha256": SOURCE_ROW_DERIVATIVE["font"]["sha256"],
    "bytes": SOURCE_ROW_DERIVATIVE["font"]["bytes"],
    "style": SOURCE_ROW_DERIVATIVE["style"],
    "source_license": SOURCE_ROW_DERIVATIVE["license"]["file"],
    "bundled_license": SOURCE_ROW_DERIVATIVE["export_license"],
    "license_sha256": SOURCE_ROW_DERIVATIVE["license"]["sha256"],
    "license_bytes": SOURCE_ROW_DERIVATIVE["license"]["bytes"],
    "librecad_font": SOURCE_ROW_DERIVATIVE["lff"]["file"],
    "librecad_sha256": SOURCE_ROW_DERIVATIVE["lff"]["sha256"],
    "librecad_bytes": SOURCE_ROW_DERIVATIVE["lff"]["bytes"],
}
