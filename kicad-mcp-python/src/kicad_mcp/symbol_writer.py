"""KiCad 自定义符号生成器：根据规格书（引脚/属性）生成 .kicad_sym 符号库文件。

生成的符号是 KiCad 10 S-expression 格式（与官方库符号一致），供 KiCad 原理图
使用。引脚自动布局：
- 输入/输出/被动引脚：左右两侧（2.54mm 栅格）
- 电源引脚：顶部/底部
- 符号 body 尺寸根据引脚数量自动计算

用法（供 MCP 工具调用）：
    from kicad_mcp.symbol_writer import build_lib_file, layout_pins

单位：全部 mm（符号文件坐标）。
"""

from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Optional

# pin 电气类型 -> .kicad_sym 文件里的 token（与 KiCad sch_io_kicad_sexpr 一致）
PIN_TYPE_TOKEN = {
    "input": "input",
    "output": "output",
    "bidirectional": "bidirectional",
    "tri_state": "tri_state",
    "passive": "passive",
    "power_in": "power_in",
    "power_out": "power_out",
    "open_collector": "open_collector",
    "open_emitter": "open_emitter",
    "no_connect": "no_connect",
    "unspecified": "unspecified",
}

# 电气类型 -> 引脚应放的位置（side）
TYPE_SIDE = {
    "input": "left",
    "output": "right",
    "bidirectional": "left",
    "tri_state": "left",
    "passive": "left",
    "power_in": "top",
    "power_out": "bottom",
    "open_collector": "right",
    "open_emitter": "right",
    "no_connect": "left",
    "unspecified": "left",
}

SPACING = 2.54       # 引脚栅格
PIN_LENGTH = 2.54    # 引脚引线长度
BODY_WIDTH = 3.81    # 符号 body 半宽（x 从 -BODY_WIDTH..BODY_WIDTH）


def _fmt(v: float) -> str:
    """格式化数字（去掉多余的 0）。"""
    return f"{v:g}"


def parse_spec(spec: str) -> dict:
    """解析规格书为统一结构。

    支持两种输入：
    1. JSON：{"name": "...", "reference": "U", "pins": [{"number","name","type"}]}
    2. 文本表格：
           元件: NAME
           描述: ...
           引脚:
           1: RST input
           2: VCC power_in
       （每行 "编号: 名称 类型"）

    Returns:
        {"name","reference","description","footprint","pins":[{number,name,type}]}
    """
    spec = spec.strip()
    # 尝试 JSON
    if spec.startswith("{"):
        try:
            data = json.loads(spec)
            pins = data.get("pins", [])
            norm = []
            for p in pins:
                t = str(p.get("type", "passive")).lower().replace(" ", "_")
                item = {"number": str(p["number"]), "name": str(p.get("name", "")),
                        "type": t if t in PIN_TYPE_TOKEN else "passive"}
                side = str(p.get("side", "")).lower()
                if side in ("left", "right", "top", "bottom"):
                    item["side"] = side
                norm.append(item)
            return {
                "name": str(data.get("name", "CUSTOM")),
                "reference": str(data.get("reference", "U")),
                "description": str(data.get("description", "")),
                "footprint": str(data.get("footprint", "")),
                "datasheet": str(data.get("datasheet", "")),
                "layout": data.get("layout") if isinstance(data.get("layout"), dict) else None,
                "pins": norm,
            }
        except Exception:
            pass

    # 文本解析
    part = {"name": "CUSTOM", "reference": "U", "description": "",
            "footprint": "", "datasheet": "", "pins": []}
    pin_re = re.compile(r"^\s*([A-Za-z0-9_.\-]+)\s*[:=]\s*(.+)$")
    pin_list_started = False
    for line in spec.splitlines():
        line = line.strip()
        if not line:
            continue
        low = line.lower()
        if low.startswith(("元件", "name", "符号")):
            v = line.split(":", 1)[-1].strip()
            if v:
                part["name"] = v.split()[0] if v else part["name"]
            continue
        if low.startswith("描述") or low.startswith("description"):
            part["description"] = line.split(":", 1)[-1].strip()
            continue
        if low.startswith("封装") or low.startswith("footprint"):
            part["footprint"] = line.split(":", 1)[-1].strip()
            continue
        if low.startswith("引脚") or low.startswith("pins") or low.startswith("pin"):
            pin_list_started = True
            continue
        if pin_list_started:
            m = re.match(r"^\s*([A-Za-z0-9_.\-]+)\s*[:=]\s*(.+)$", line)
            if m:
                num = m.group(1)
                rest = m.group(2).split()
                name = rest[0] if rest else ""
                t = rest[1].lower().replace("_", " ") if len(rest) > 1 else "passive"
                t = re.sub(r"\s+", "_", t)
                item = {"number": num, "name": name,
                        "type": t if t in PIN_TYPE_TOKEN else "passive"}
                if len(rest) > 2 and rest[2].lower() in ("left", "right", "top", "bottom"):
                    item["side"] = rest[2].lower()
                part["pins"].append(item)
    if not part["pins"]:
        # 宽松：任何 "数字 名称 类型" 行
        for line in spec.splitlines():
            m = re.match(r"^\s*([A-Za-z0-9_.\-]+)\s+([A-Za-z0-9_.\-]+)\s+([A-Za-z_]+)", line)
            if m:
                t = m.group(3).lower().replace("_", " ")
                t = re.sub(r"\s+", "_", t)
                part["pins"].append({"number": m.group(1), "name": m.group(2),
                                     "type": t if t in PIN_TYPE_TOKEN else "passive"})
    return part


def layout_pins(pins: list[dict], l_spacing: Optional[float] = None,
                p_spacing: Optional[float] = None) -> dict:
    """给引脚分配位置。

    Args:
        pins: 引脚列表（含 side）。
        l_spacing: 左右引脚栅格（mm），默认 SPACING=2.54。GPIO 名字较长时
            可加大（如 3.0）避免引脚名文字重叠。
        p_spacing: 顶部/底部引脚栅格（mm），默认 3.5。电源引脚名字较长
            （IOVDD/VREG_VIN/ADC_AVDD 等），需要比左右更大的间距，否则
            顶部/底部引脚名与编号会文字重叠。

    Returns:
        {"pins": [ {number,name,type,side,x,y,angle,hide_name?} ... ],
         "body": {"x0","y0","x1","y1"} }  (x0,y0 左上，x1,y1 右下；Y 向下)
    """
    l_spacing = l_spacing or SPACING
    p_spacing = p_spacing or 3.5

    left, right, top, bottom = [], [], [], []
    seen_names = {}
    for p in pins:
        # 显式 side 优先；否则按电气类型默认
        side = p.get("side") or TYPE_SIDE.get(p["type"], "left")
        # GND 类 power_in 放底部（KiCad 惯例：VCC 顶、GND 底）
        if (side == "top" and p["type"] == "power_in"
                and re.search(r"\bGND\b|VSS|VEE|VSUB|GNDA", p["name"].upper())):
            side = "bottom"
        p = {**p, "side": side}
        # 同名引脚（如 6 个 IOVDD / 2 个 DVDD）只显示第一个的名字，其余隐藏
        # 名字只留编号，避免顶部/底部电源引脚名字文字重叠
        if p["name"]:
            if seen_names.get(p["name"]):
                p["hide_name"] = True
            seen_names[p["name"]] = True
        {"left": left, "right": right, "top": top, "bottom": bottom}[side].append(p)

    max_side = max(len(left), len(right), 1)
    # 左右引脚：从 body 顶部向下排，y 正值在上
    body_h = (max_side - 1) * l_spacing + 2 * SPACING

    # body 半宽至少覆盖顶部/底部电源引脚的分布范围，否则电源引脚会远远
    # 飞出窄 body，造成符号宽度比例失调（像"一坨散开的线"）。
    n_top = max(len(top), 1)
    n_bot = max(len(bottom), 1)
    top_span = (n_top - 1) * p_spacing
    bot_span = (n_bot - 1) * p_spacing
    body_half_w = max(BODY_WIDTH, top_span / 2 + p_spacing / 2,
                      bot_span / 2 + p_spacing / 2)

    y_top = body_h / 2 - SPACING          # 最上面引脚 y
    pin_x = body_half_w + PIN_LENGTH      # 左右引脚距中心的 x

    for i, p in enumerate(left):
        p["x"], p["y"], p["angle"] = -pin_x, y_top - i * l_spacing, 0
    for i, p in enumerate(right):
        p["x"], p["y"], p["angle"] = pin_x, y_top - i * l_spacing, 180

    # 顶部/底部电源引脚：居中对称排列，引线朝外。
    # KiCad 符号库坐标 Y 向上为正（与原理图相反）：
    #   上方引脚 at (0, +y) angle 270（引线朝上）
    #   下方引脚 at (0, -y) angle 90 （引线朝下）
    # 已用 eeschema 渲染/读回验证（VDC: at (0,+5.08) 270 渲染在原理图上方）。
    top_y = body_h / 2 + PIN_LENGTH
    top_x0 = (n_top - 1) * p_spacing / 2
    for i, p in enumerate(top):
        p["x"], p["y"], p["angle"] = top_x0 - i * p_spacing, top_y, 270
    bot_y = -(body_h / 2 + PIN_LENGTH)
    bot_x0 = (n_bot - 1) * p_spacing / 2
    for i, p in enumerate(bottom):
        p["x"], p["y"], p["angle"] = bot_x0 - i * p_spacing, bot_y, 90

    return {
        "pins": left + right + top + bottom,
        "body": {"x0": -body_half_w, "y0": body_h / 2,
                 "x1": body_half_w, "y1": -body_h / 2},
    }


def _pin_sexpr(p: dict, indent: str = "\t\t\t") -> str:
    token = PIN_TYPE_TOKEN.get(p["type"], "passive")
    hide = " hide" if p.get("hide_name") else ""
    return (f"{indent}(pin {token} line "
            f"(at {_fmt(p['x'])} {_fmt(p['y'])} {p['angle']}) "
            f"(length {PIN_LENGTH:g}) "
            f"(name \"{p['name']}\" (effects (font (size 1.27 1.27)){hide})) "
            f"(number \"{p['number']}\" (effects (font (size 1.27 1.27)))))")


def _property_sexpr(name: str, value: str, x: float, y: float,
                    hide: bool = False, indent: str = "\t\t") -> str:
    hide_str = " hide" if hide else ""
    return (f"{indent}(property \"{name}\" \"{value}\" "
            f"(at {_fmt(x)} {_fmt(y)} 0) "
            f"(effects (font (size 1.27 1.27)){hide_str}))")


def build_symbol(part: dict) -> str:
    """生成单个符号的 s-expr 文本（KiCad 10 标准缩进格式）。"""
    name = part["name"]
    reference = part.get("reference", "U")
    layout_cfg = part.get("layout") or {}
    layout = layout_pins(part["pins"],
                         l_spacing=layout_cfg.get("left_spacing"),
                         p_spacing=layout_cfg.get("pin_spacing"))
    body = layout["body"]
    pins = layout["pins"]

    # 库坐标 Y 向上为正：Reference 放在 body 上方，Value 在下方。
    # 但有大符号顶部/底部有引脚时，body 外上方/下方会被引脚名+编号占据，
    # Reference/Value 需放 body 内部避免与引脚文字重叠；小符号仍放 body 外。
    has_tb = any(p.get("side") in ("top", "bottom") for p in layout["pins"])
    if has_tb and body["y0"] > 5.08:
        ref_y = body["y0"] - 2.54   # body 内上方
        val_y = body["y1"] + 2.54   # body 内下方
    else:
        ref_y = body["y0"] + 2.54   # body 上方
        val_y = body["y1"] - 2.54   # body 下方

    lines = [f"\t(symbol \"{name}\"",
             "\t\t(pin_names (offset 1.016))",
             "\t\t(exclude_from_sim no)",
             "\t\t(in_bom yes)",
             "\t\t(on_board yes)",
             "\t\t(in_pos_files yes)",
             _property_sexpr("Reference", reference, 0, ref_y),
             _property_sexpr("Value", name, 0, val_y),
             _property_sexpr("Footprint", part.get("footprint", ""), 0, 0, hide=True),
             _property_sexpr("Datasheet", part.get("datasheet", ""), 0, 0, hide=True),
             _property_sexpr("Description", part.get("description", ""), 0, 0, hide=True),
             f"\t\t(symbol \"{name}_0_1\"",
             f"\t\t\t(rectangle (start {_fmt(body['x0'])} {_fmt(body['y0'])}) "
             f"(end {_fmt(body['x1'])} {_fmt(body['y1'])}) "
             f"(stroke (width 0.254) (type default)) (fill (type background)))",
             "\t\t)",
             # 引脚放在单独单元 _1_1（与官方库一致）：官方把 body 放 _0_1、
             # 引脚放 _1_1，若把引脚塞进 _0_1，eeschema 解析会异常（引脚
             # y 坐标翻转，导致 GND 等顶部引脚落到 body 下方）。
             f"\t\t(symbol \"{name}_1_1\""]
    for p in pins:
        lines.append(_pin_sexpr(p))
    lines.append("\t\t)")
    lines.append("\t)")
    return "\n".join(lines)


def build_lib_file(parts: list[dict], lib_name: str = "custom_local") -> str:
    """生成完整 .kicad_sym 库文件文本（可含多个符号）。"""
    header = ("(kicad_symbol_lib\n\t(version 20251024)\n"
              "\t(generator \"kicad_mcp\")\n\t(generator_version \"10.0\")")
    body = "\n".join(build_symbol(p) for p in parts)
    return f"{header}\n{body}\n)\n"


def build_symbol_file(part: dict) -> str:
    """生成 .kicad_symdir 目录库里的单个符号文件内容。

    每个符号一个文件（kicad_symbol_lib 包裹单个 symbol），这是 KiCad 10
    标准库格式。**注意**: 需使用与官方库一致的紧凑格式（property 单行），
    否则 eeschema 加载会失败。
    """
    header = ("(kicad_symbol_lib\n\t(version 20251024)\n"
              "\t(generator \"kicad_mcp\")\n\t(generator_version \"10.0\")")
    return f"{header}\n{build_symbol(part)}\n)\n"


def write_lib_file(parts: list[dict], path: str, lib_name: str) -> Path:
    """把符号写入单文件 .kicad_sym。返回路径。"""
    p = Path(path)
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(build_lib_file(parts, lib_name), encoding="utf-8")
    return p


def write_symdir(symbols: list[dict], dir_path: str) -> Path:
    """把符号写入 .kicad_symdir 目录库（每符号一个文件）。返回目录路径。"""
    d = Path(dir_path)
    d.mkdir(parents=True, exist_ok=True)
    for part in symbols:
        f = d / f"{part['name']}.kicad_sym"
        f.write_text(build_symbol_file(part), encoding="utf-8")
    return d
