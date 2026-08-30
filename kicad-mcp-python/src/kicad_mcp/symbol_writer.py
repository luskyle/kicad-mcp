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
import math
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
GRID = 1.27


def _fmt(v: float) -> str:
    """格式化数字（去掉多余的 0）。"""
    return f"{v:g}"


def _snap_grid(value: float) -> float:
    return round(value / GRID) * GRID


def _ceil_grid(value: float) -> float:
    return math.ceil(value / GRID - 1e-9) * GRID


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
                p_spacing: Optional[float] = None,
                value_name: str = "") -> dict:
    """给引脚分配位置（智能排布，符合 KiCad 官方符号惯例）。

    排布策略：
      - 电源引脚：VCC 类放顶部、GND 类放底部（IEC 61082：电源上/地在下）；
        名字过长的电源引脚（>3 字符）改放左右（名字水平、清晰不重叠）。
      - 信号引脚：input 放左侧、output 放右侧（信号流左→右）；
        无方向类型（bidirectional/passive/…）在左右两侧**交替均衡**分配，
        避免全部堆在一侧造成符号失衡。
      - 左右引脚名字向 body 内延伸（KiCad 左侧 anchor=start、右侧 anchor=end），
        body 半宽按两侧最长名字自适应（实际字宽 ≈ 字符数×字高×1.05），
        保证名字在 body 内互不重叠。
      - 上下（垂直）引脚名字从连接点向 body 延伸，连接点按名字长度外移，
        避免与编号重叠。

    Args:
        pins: 引脚列表（含 side/type/name/number）。
        l_spacing: 左右引脚栅格（mm），默认 SPACING=2.54。
        p_spacing: 顶部/底部引脚栅格（mm），默认 3.5。

    Returns:
        {"pins": [ {number,name,type,side,x,y,angle,hide_name?} ... ],
         "body": {"x0","y0","x1","y1"} }  (x0,y0 左上，x1,y1 右下；Y 向下)
    """
    l_spacing = l_spacing or SPACING
    p_spacing = p_spacing or SPACING

    left, right, top, bottom = [], [], [], []
    lr_pool: list = []
    seen_names = {}
    for p in pins:
        explicit = p.get("side") is not None
        side = p.get("side") or TYPE_SIDE.get(p["type"], "left")
        # 长名电源引脚改放左右（垂直名字会压编号）
        if side in ("top", "bottom") and len(p["name"]) > 3:
            side = {"power_in": "left", "power_out": "right"}.get(p["type"], side)
        # GND 类 power_in 放底部（KiCad 惯例：VCC 顶、GND 底）
        if (side == "top" and p["type"] == "power_in"
                and re.search(r"\bGND\b|VSS|VEE|VSUB|GNDA", p["name"].upper())):
            side = "bottom"
        p = {**p, "side": side, "_explicit": explicit}
        # 同名引脚只显示第一个名字，其余隐藏（只留编号）
        if p["name"]:
            if seen_names.get(p["name"]):
                p["hide_name"] = True
            seen_names[p["name"]] = True
        if side in ("left", "right"):
            lr_pool.append(p)
        else:
            {"top": top, "bottom": bottom}[side].append(p)

    # 左右均衡分配：input→左、output→右（信号流），无方向类型左右交替，
    # 避免一侧堆积（如 9 个引脚全堆左侧、右侧只有 1 个）。
    forced_left = [p for p in lr_pool
                   if (p["_explicit"] and p["side"] == "left") or p["type"] == "input"]
    forced_right = [p for p in lr_pool
                    if (p["_explicit"] and p["side"] == "right") or p["type"] == "output"]
    forced_ids = {id(p) for p in forced_left + forced_right}
    flexible = [p for p in lr_pool if id(p) not in forced_ids]
    left = list(forced_left)
    right = list(forced_right)
    for i, p in enumerate(flexible):
        if i % 2 == 0:
            left.append(p)
            p["side"] = "left"
        else:
            right.append(p)
            p["side"] = "right"

    max_side = max(len(left), len(right), 1)
    # 左右引脚：从 body 顶部向下排，y 正值在上
    body_h = (max_side - 1) * l_spacing + 2 * SPACING

    # 关键：确保 body_h 是偶数个 1.27 网格（半高落在整数网格上）。
    # 否则顶部/底部引脚 y 会落在半格（如 33.5 格），连到这些引脚的导线
    # ERC 报 endpoint_off_grid 且 KiCad 网格连接判定会失败（线端点吸附到
    # 最近网格点而碰不到 off_grid 引脚）。
    body_grids = round(body_h / (2 * GRID)) * 2
    if body_grids * GRID < body_h:
        body_grids += 2
    body_h = body_grids * GRID

    # body 半宽：至少覆盖顶部/底部电源引脚的分布范围，还要容纳左右引脚
    # 名字向 body 内延伸的长度（左侧 anchor=start 向右、右侧 anchor=end 向左，
    # 长名会在 body 内与对侧名字重叠），并且要预留 body 中央的
    # Value/Reference 属性文字（value_w/2）不被左右长名覆盖。
    # 实测 KiCad 1.27mm 字高文字每字符宽约 1.34mm，但长名+斜杠更宽 → 用 1.1 保守。
    def _name_w_mm(name: str) -> float:
        return len(name) * 1.27 * 1.1

    lmaxw = max((_name_w_mm(p["name"]) for p in left), default=0.0)
    rmaxw = max((_name_w_mm(p["name"]) for p in right), default=0.0)
    value_w = len(value_name) * 1.27 * 1.05
    n_top = max(len(top), 1)
    n_bot = max(len(bottom), 1)
    top_span = (n_top - 1) * p_spacing
    bot_span = (n_bot - 1) * p_spacing
    body_half_w = max(BODY_WIDTH,
                      (lmaxw + rmaxw) / 2 + 1.0,
                      lmaxw + value_w / 2 + 0.8,
                      rmaxw + value_w / 2 + 0.8,
                      top_span / 2 + p_spacing / 2,
                      bot_span / 2 + p_spacing / 2)
    body_half_w = _ceil_grid(body_half_w)

    # 引脚引线长度：KiCad 编号(number)在引线上、紧挨连接点，名字从 body 内
    # 延伸。若引线太短，编号右端会伸进 body 与名字重叠 → 按最长编号宽度
    # 加长引线，让编号完全落在 body 外侧。
    max_num_w = max((len(p["number"]) for p in pins), default=1) * 1.27 * 0.75
    pin_len = _ceil_grid(max(PIN_LENGTH, 1.2 + max_num_w))

    y_top = body_h / 2 - SPACING          # 最上面引脚 y
    pin_x = body_half_w + pin_len         # 左右引脚距中心的 x

    for i, p in enumerate(left):
        p["x"], p["y"], p["angle"] = -pin_x, _snap_grid(y_top - i * l_spacing), 0
        p["length"] = pin_len
    for i, p in enumerate(right):
        p["x"], p["y"], p["angle"] = pin_x, _snap_grid(y_top - i * l_spacing), 180
        p["length"] = pin_len

    # 顶部/底部电源引脚：居中对称排列，引线朝外。
    # KiCad 符号库坐标 Y 向上为正（与原理图相反）：
    #   上方引脚 at (0, +y) angle 270（引线朝上）
    #   下方引脚 at (0, -y) angle 90 （引线朝下）
    # 连接点按名字长度+pin_names offset 外移：垂直引脚名字从连接点向 body
    # 延伸 offset(1.016)+len*1.27*1.1（实测每字符宽≈1.356mm），需保证名字
    # 末端不越过 body 边缘（否则与 body 内的 Value 属性文字重叠）。
    def _name_ext(name: str) -> float:
        return len(name) * 1.27 * 1.1

    top_ext = max((_name_ext(p["name"]) for p in top), default=0.0)
    bot_ext = max((_name_ext(p["name"]) for p in bottom), default=0.0)
    top_margin = _ceil_grid(max(pin_len, top_ext + 1.016 + 1.2))
    bot_margin = _ceil_grid(max(pin_len, bot_ext + 1.016 + 1.2))
    top_y = body_h / 2 + top_margin
    top_x0 = (n_top - 1) * p_spacing / 2
    for i, p in enumerate(top):
        p["x"], p["y"], p["angle"] = _snap_grid(top_x0 - i * p_spacing), top_y, 270
        p["length"] = top_margin
    bot_y = -(body_h / 2 + bot_margin)
    bot_x0 = (n_bot - 1) * p_spacing / 2
    for i, p in enumerate(bottom):
        p["x"], p["y"], p["angle"] = _snap_grid(bot_x0 - i * p_spacing), bot_y, 90
        p["length"] = bot_margin

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
            f"(length {p.get('length', PIN_LENGTH):g}) "
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
                         p_spacing=layout_cfg.get("pin_spacing"),
                         value_name=name)
    body = layout["body"]
    pins = layout["pins"]

    # 库坐标 Y 向上为正：Reference 放在 body 上方，Value 在下方。
    # KiCad 把垂直（顶部/底部）引脚的名字固定渲染在 body 边缘内侧并向内延伸，
    # 若 Reference/Value 放 body 外上方/下方会被顶部/底部引脚名+编号占据，
    # 放 body 内对应侧也会被引脚名覆盖（实测底部 GND 名占 body 内下方）。
    # 因此：底部有引脚 → Value 放 body 中央；顶部有引脚 → Reference 放 body 中央；
    # 该侧无引脚 → 仍放 body 外侧（KiCad 惯例）。
    has_top = any(p.get("side") == "top" for p in layout["pins"])
    has_bot = any(p.get("side") == "bottom" for p in layout["pins"])
    if has_top:
        ref_y = body["y0"] - 2.54      # body 内上方（避开顶部引脚名）
    else:
        ref_y = body["y0"] + 2.54      # body 上方外部
    if has_bot:
        val_y = (body["y0"] + body["y1"]) / 2  # body 中央（避开底部引脚名）
    else:
        val_y = body["y1"] - 2.54      # body 下方外部
    # 顶部+底部都有引脚：中央只有一个位置，Reference/Value 上下错开，
    # 但仍避开两侧引脚名字覆盖区（引脚名约占 body 内侧 1.5~5mm）。
    if has_top and has_bot:
        half = (body["y0"] - body["y1"]) / 2
        ref_y = body["y0"] - min(half * 0.7, 3.81)
        val_y = body["y1"] + min(half * 0.7, 3.81)

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
