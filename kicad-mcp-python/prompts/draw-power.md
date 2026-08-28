# 模板：画电源电路（USBC / LDO / 去耦）

> 典型：USB-C 输入 → LDO 稳压 → 去耦电容 → 3V3/GND。
> 一次 `kicad_sch_draw_circuit` 完成，**按真实引脚语义接线**（不要再犯"USBC 的 GND 接 VBUS"这种错）。

## 电路描述

```json
{
  "symbols": [
    {"ref": "J1", "lib": "keyboard-89_local", "symbol": "USBC", "value": "USB-C"},
    {"ref": "U2", "lib": "keyboard-89_local", "symbol": "LDO",  "value": "ME6211C33"},
    {"ref": "C1", "lib": "keyboard-89_local", "symbol": "C-100nF", "value": "100nF"},
    {"ref": "PWR0", "lib": "power", "symbol": "PWR_FLAG", "value": "PWR_FLAG"},
    {"ref": "PWRV", "lib": "power", "symbol": "PWR_FLAG", "value": "PWR_FLAG"}
  ],
  "nets": [
    {"name": "3V3",  "pins": [["U2","2"], ["C1","1"]], "label": "3V3"},
    {"name": "0",    "pins": [["U2","1"], ["C1","2"], ["J1","1"], ["J1","12"],
                               ["J1","13"], ["J1","14"], ["PWR0","1"]], "label": "0"},
    {"name": "VBUS", "pins": [["U2","3"], ["J1","2"], ["J1","11"], ["PWRV","1"]], "label": "VBUS"},
    {"name": "USB_DM", "pins": [["J1","7"]], "label": "USB_DM"},
    {"name": "USB_DP", "pins": [["J1","6"]], "label": "USB_DP"}
  ],
  "layout": {"mode": "grid", "columns": 1, "gap_mm": 20},
  "default_label_type": "global",
  "keep_power_symbols": true,
  "no_connect_marks": true,
  "clear": true, "run_erc": true, "render": true
}
```

## 关键约定（踩过的坑）
- **USBC 引脚语义**：VBUS=2,11（电源）；GND=1,12（地）；SHELL=13,14（接 GND/0）；
  DM=7、DP=6、CC1=4、CC2=10（信号）。**GND 接 GND、VBUS 接 VBUS**，别接反。
- **3V3 由 LDO 输出驱动** → 3V3 网络**不要放 PWR_FLAG**（两个 power_out 同网会报错）。
  只有 0/VBUS 这种"纯电源输入"网络才需要 PWR_FLAG。
- 布局用 **grid 单列 + gap 20**：信号流 J1→U2→C1 左→右（IEC 61082），trunk 有干净通道。
- `keep_power_symbols: true`：电源轨道用 rail_refs 让 3V3 顶轨 / 0 底轨。
- 未用引脚（SBU/CC/DP 等）`no_connect_marks: true` 自动打 X。

## 检查清单
- [ ] ERC 门禁 PASS（0 blocking；只剩 USB_DM/DP 跨页 label 豁免 + 封装库警告）
- [ ] J1 的 GND/VBUS 没接反
- [ ] 3V3 无 PWR_FLAG、0/VBUS 有 PWR_FLAG
