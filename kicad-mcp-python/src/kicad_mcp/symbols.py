"""KiCad 符号库解析：从 .kicad_sym 读取符号引脚定义并做坐标变换。

用途：让绘制工具能精确地把连线连到元件引脚（而不是靠估算坐标）。

单位约定：本模块内部一律使用 **mm**（符号文件坐标即 mm）。
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path
from typing import List, Optional

# KiCad 10 符号库根目录（AppImage 解包位置，可由环境变量覆盖）
DEFAULT_LIB_ROOT = Path("/tmp/squashfs-root/share/kicad/symbols")


@dataclass
class SymbolPin:
    number: str          # 引脚编号（如 "1"、"A"）
    name: str            # 引脚名（如 "+"、"-"、"A"）
    x_mm: float          # 相对符号中心的 X（mm）
    y_mm: float          # 相对符号中心的 Y（mm，Y 向下为正）
    angle: int           # 引脚方向角（0/90/180/270）


# SCH_SYMBOL 的 orientation_degrees 变换（与 KiCad 内部 transform 一致）
# 已验证（10.0.6）：KiCad orientation 90° 对库坐标施加 (x,y)->(-y,x)。
# 0°:  (x, y)
# 90°: (-y, x)
# 180°:(-x, -y)
# 270°:(y, -x)
def rotate_xy(x: float, y: float, degrees: int) -> tuple[float, float]:
    degrees = int(degrees) % 360
    if degrees == 0:
        return x, y
    if degrees == 90:
        return -y, x
    if degrees == 180:
        return -x, -y
    if degrees == 270:
        return y, -x
    raise ValueError(f"不支持的旋转角度: {degrees}（可选 0/90/180/270）")


# ---------------- S-expression 解析 ----------------

def _tokenize(text: str) -> List[str]:
    return re.findall(r'\(|\)|"[^"]*"|[^\s()]+', text)


def parse_sexpr(text: str):
    """把 S-expression 文本解析成嵌套 list（原子为 str/int/float）。"""
    tokens = _tokenize(text)
    stack: list = [[]]
    for tok in tokens:
        if tok == '(':
            stack.append([])
        elif tok == ')':
            item = stack.pop()
            stack[-1].append(item)
        else:
            if tok.startswith('"') and tok.endswith('"'):
                stack[-1].append(tok[1:-1])
            elif re.fullmatch(r'-?\d+', tok):
                stack[-1].append(int(tok))
            elif re.fullmatch(r'-?\d*\.\d+', tok):
                stack[-1].append(float(tok))
            else:
                stack[-1].append(tok)
    return stack[0]


def _iter_sexpr(node, tag: str):
    """递归遍历 S-expression，产出所有以 tag 开头的子节点。"""
    if isinstance(node, list):
        if node and isinstance(node[0], str) and node[0] == tag:
            yield node
        for child in node:
            if isinstance(child, list):
                yield from _iter_sexpr(child, tag)


def parse_pins(sym_node) -> List[SymbolPin]:
    """从 (symbol "Name" ...) 节点提取引脚列表。"""
    pins: List[SymbolPin] = []
    for pin in _iter_sexpr(sym_node, 'pin'):
        # pin 结构: (pin <type> <style> (at x y angle) (name ".." ...) (number ".." ...))
        at = None
        name = ''
        number = ''
        for sub in pin:
            if isinstance(sub, list) and sub and sub[0] == 'at' and len(sub) >= 4:
                at = (float(sub[1]), float(sub[2]), int(sub[3]))
            elif isinstance(sub, list) and sub and sub[0] == 'name' and len(sub) >= 2:
                name = str(sub[1])
            elif isinstance(sub, list) and sub and sub[0] == 'number' and len(sub) >= 2:
                number = str(sub[1])
        if at is not None:
            pins.append(SymbolPin(number=number, name=name, x_mm=at[0], y_mm=at[1], angle=at[2]))
    return pins


def load_symbol(lib_name: str, sym_name: str,
                lib_root: Path = DEFAULT_LIB_ROOT) -> Optional[dict]:
    """加载符号定义，返回 { 'name': str, 'pins': [SymbolPin] }；找不到返回 None。"""
    path = lib_root / f"{lib_name}.kicad_symdir" / f"{sym_name}.kicad_sym"
    if not path.exists():
        return None
    root = parse_sexpr(path.read_text(encoding='utf-8'))
    for sym in _iter_sexpr(root, 'symbol'):
        # 顶层 (symbol "Name" ...)，跳过 body 子符号（"Name_0_1"）
        if len(sym) >= 2 and isinstance(sym[1], str) and sym[1] == sym_name:
            return {'name': sym_name, 'pins': parse_pins(sym)}
    return None


def get_pins(lib_name: str, sym_name: str,
             lib_root: Path = DEFAULT_LIB_ROOT) -> List[SymbolPin]:
    """获取符号的引脚（相对符号中心，mm）。"""
    sym = load_symbol(lib_name, sym_name, lib_root)
    return sym['pins'] if sym else []


def absolute_pin(sym_x_mm: float, sym_y_mm: float, orientation_degrees: int,
                 pin: SymbolPin) -> tuple[float, float]:
    """计算引脚在原理图上的绝对坐标（mm），考虑符号放置位置和旋转。

    注意: KiCad 符号库坐标 Y 与原理图坐标 Y 方向相反（.kicad_sym 里 at
    的正 Y 渲染在原理图上方，即原理图 Y 向上为正）。因此把旋转后的库坐标
    转换到原理图坐标时，Y 要取反（原理图 Y 向下为正）。已用 eeschema
    get_items 读回的引脚绝对位置验证: 文件 at (0,+5.08) 读回 y = 中心-5.08。
    """
    rx, ry = rotate_xy(pin.x_mm, pin.y_mm, orientation_degrees)
    return sym_x_mm + rx, sym_y_mm - ry
