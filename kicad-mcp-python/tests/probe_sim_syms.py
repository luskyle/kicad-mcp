"""探测仿真符号引脚结构：VDC(Simulation_SPICE)、R/C(Device)。"""
import sys, json
sys.path.insert(0, "src")
from kicad_mcp.tools import schematic as sch

def probe(lib, entry, pos_mm):
    r = sch.kicad_sch_add_symbol(lib_nickname=lib, entry_name=entry,
                                 x_mm=pos_mm[0], y_mm=pos_mm[1],
                                 reference="X1", value="1", orientation_degrees=0)
    print(f"== {lib}:{entry} @{pos_mm} ==")
    print(json.dumps(r, ensure_ascii=False, indent=1))

if __name__ == "__main__":
    probe("Simulation_SPICE", "VDC", [40, 40])
    probe("Device", "R", [40, 80])
    probe("Device", "C", [40, 120])
