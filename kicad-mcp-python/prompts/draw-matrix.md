# 模板：画键盘矩阵（15 键 3×5）

> 用 `draw_circuit` 的 **label_only** 网络：同侧两脚短接、每侧一个全局标签，不拉矩阵线。

## 电路描述（一次性 draw_circuit）

```json
{
  "symbols": [
    {"ref": "K1",  "lib": "keyboard-89_local", "symbol": "TC-6601-5-160G", "value": "K1"},
    {"ref": "K2",  "lib": "keyboard-89_local", "symbol": "TC-6601-5-160G", "value": "K2"}
    // ... K3..K15，坐标见 layout.positions
  ],
  "nets": [
    {"name": "C1", "label_only": true, "pins": [["K1","1"],["K1","2"],["K6","1"],["K6","2"],["K11","1"],["K11","2"]]},
    // ... C2..C5（列）；R1..R3（行，引脚 3/4）
  ],
  "layout": {"mode": "positions", "positions": {
    "K1": [60, 100, 0], "K2": [80.32, 100, 0], ...   // 间距 dx=dy=20.32mm
  }},
  "default_label_type": "global",
  "clear": true, "run_erc": true, "render": true
}
```

## 关键约定（踩过的坑）
- **引脚语义**（TC-6601 4 脚开关）：引脚 1/2 = 同一接触点（列 Cx），引脚 3/4 = 另一接触点（行 Rx）。
  `label_only` 会自动把同侧两脚用导线短接、只放一个标签（不会叠在符号上、不重复）。
- **间距 20.32mm**（16 格）：键半宽 6.35 + 标签 stub（约 2.54~5mm），15.24 会撞。
- **标签尺寸 1.27mm**（默认），放引脚外侧 stub 上（不压符号）。
- `label_only` 网络即使不写 label 字段也用网络名做标签（工具自动处理）。
- 跨页：列/行网络用 global 标签连到 MCU 页的 GPIO。

## 检查清单
- [ ] ERC 门禁 PASS（矩阵无违规）
- [ ] 每个键左侧 1 个 Cx 标签、右侧 1 个 Rx 标签（共 30，不是 60）
- [ ] 标签不压符号、相邻键标签不碰撞
