#!/usr/bin/env python3
"""创建 keyboard-89 KiCad 项目: keyboard-89.kicad_pro + 根原理图(分层 5 sheet)。"""
import json
import pathlib
import uuid

PROJ = pathlib.Path("/home/luskyle/桌面/keyboard-89")

# ============ 1. .kicad_pro (KiCad 10 JSON) ============
kicad_pro = {
    "board": {},
    "boards": [],
    "cvpcb": {"equivalence_files": []},
    "libraries": {"pinned_footprint_libs": [], "pinned_symbol_libs": []},
    "meta": {"filename": "keyboard-89.kicad_pro", "version": 1},
    "net_settings": {
        "classes": [{
            "bus_width": 12, "clearance": 0.2,
            "diff_pair_gap": 0.25, "diff_pair_via_gap": 0.25, "diff_pair_width": 0.2,
            "line_style": 0, "microvia_diameter": 0.3, "microvia_drill": 0.1,
            "name": "Default", "pcb_color": "rgba(0, 0, 0, 0.000)",
            "schematic_color": "rgba(0, 0, 0, 0.000)",
            "track_width": 0.25, "via_diameter": 0.8, "via_drill": 0.4, "wire_width": 6,
        }],
        "meta": {"version": 3},
        "net_colors": None, "netclass_assignments": None, "netclass_patterns": [],
    },
    "pcbnew": {
        "last_paths": {
            "gencad": "", "netlist": "", "plot": "", "pos": "",
            "schematic": "", "specctra_dsn": "", "step": "", "svg": "", "vrml": "",
        },
        "page_layout_descr_file": "",
    },
    "schematic": {
        "annotate_start_num": 0,
        "drawing": {
            "dashed_lines_dash_length_ratio": 12.0,
            "dashed_lines_gap_length_ratio": 3.0,
            "default_line_thickness": 6.0, "default_text_size": 50.0,
            "junction_size_choice": 3, "label_size_ratio": 0.375,
            "operating_point_overlay_i_precision": 4,
            "operating_point_overlay_v_precision": 3,
            "overlay_color": "rgba(0, 0, 0, 0.000)",
            "pin_symbol_size": 25.0, "text_offset_ratio": 0.15,
        },
        "legacy_lib_dir": "", "legacy_lib_list": [],
    },
    "sheets": [[1, "keyboard-89.kicad_sch", "keyboard-89"]],
    "text_variables": {},
}
(PROJ / "keyboard-89.kicad_pro").write_text(json.dumps(kicad_pro, indent=2))
print("✓ keyboard-89.kicad_pro")

# ============ 2. 根原理图 keyboard-89.kicad_sch (分层 sheet) ============
SHEETS = [
    ("主控 MCU", "keyboard_main.kicad_sch", 50, 70, 1),
    ("电源", "keyboard_power.kicad_sch", 140, 70, 2),
    ("Flash", "keyboard_flash.kicad_sch", 230, 70, 3),
    ("键盘矩阵", "keyboard_matrix.kicad_sch", 50, 140, 4),
    ("系统总览", "keyboard_layout.kicad_sch", 140, 140, 5),
]
W, H = 70, 45
ROOT_UUID = str(uuid.uuid4())
lines = [
    "(kicad_sch",
    "\t(version 20260306)",
    '\t(generator "eeschema")',
    '\t(generator_version "10.0")',
    f'\t(uuid "{ROOT_UUID}")',
    '\t(paper "A3")',
    "\t(lib_symbols)",
]
for name, fname, x, y, page in SHEETS:
    suid = str(uuid.uuid4())
    lines += [
        "\t(sheet",
        f"\t\t(at {x} {y})",
        f"\t\t(size {W} {H})",
        "\t\t(exclude_from_sim no)",
        "\t\t(in_bom yes)",
        "\t\t(on_board yes)",
        "\t\t(dnp no)",
        "\t\t(fields_autoplaced yes)",
        "\t\t(stroke (width 0.1524) (type solid))",
        "\t\t(fill (color 0 0 0 0))",
        f'\t\t(uuid "{suid}")',
        f'\t\t(property "Sheetname" "{name}"',
        f'\t\t\t(at {x + W / 2} {y - 0.7} 0)',
        "\t\t\t(show_name no)",
        "\t\t\t(do_not_autoplace no)",
        "\t\t\t(effects (font (size 1.27 1.27)) (justify left bottom))",
        "\t\t)",
        f'\t\t(property "Sheetfile" "{fname}"',
        f'\t\t\t(at {x + W / 2} {y + H + 0.7} 0)',
        "\t\t\t(show_name no)",
        "\t\t\t(do_not_autoplace no)",
        "\t\t\t(effects (font (size 1.27 1.27)) (justify left top))",
        "\t\t)",
        "\t\t(instances",
        '\t\t\t(project "keyboard-89"',
        f'\t\t\t\t(path "/{ROOT_UUID}"',
        f'\t\t\t\t\t(page "{page}")',
        "\t\t\t\t)",
        "\t\t\t)",
        "\t\t)",
        "\t)",
    ]
lines += [
    "\t(sheet_instances",
    '\t\t(path "/" (page "1"))',
    "\t)",
    "\t(symbol_instances)",
    ")",
]
(PROJ / "keyboard-89.kicad_sch").write_text("\n".join(lines))
print("✓ keyboard-89.kicad_sch (根原理图, 5 sheets)")
print("项目文件: %s" % PROJ)
