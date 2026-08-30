from pathlib import Path


OUTPUT = Path(__file__).with_name("keyboard-89_local.pretty")


def footprint(name: str, description: str, body: str) -> str:
    return f'''(footprint "{name}"
\t(version 20240108)
\t(generator "keyboard-89")
\t(layer "F.Cu")
\t(descr "{description}")
\t(attr smd)
\t(fp_text reference "REF**" (at 0 -4) (layer "F.SilkS")
\t\t(effects (font (size 1 1) (thickness 0.15))))
\t(fp_text value "{name}" (at 0 4) (layer "F.Fab")
\t\t(effects (font (size 1 1) (thickness 0.15))))
{body}\n)\n'''


def smd_pad(number: str, x: float, y: float, width: float, height: float) -> str:
    return (f'\t(pad "{number}" smd roundrect (at {x:g} {y:g}) '
            f'(size {width:g} {height:g}) (layers "F.Cu" "F.Paste" "F.Mask") '
            '(roundrect_rratio 0.2))')


def outline(width: float, height: float) -> str:
    return (f'\t(fp_rect (start {-width / 2:g} {-height / 2:g}) '
            f'(end {width / 2:g} {height / 2:g}) '
            '(stroke (width 0.1) (type default)) (fill none) (layer "F.Fab"))')


def write(name: str, description: str, body: list[str]) -> None:
    (OUTPUT / f"{name}.kicad_mod").write_text(
        footprint(name, description, "\n".join(body)), encoding="utf-8")


OUTPUT.mkdir(exist_ok=True)

write("C_0402_1005Metric", "0402 capacitor, IPC nominal", [
    outline(1.0, 0.5), smd_pad("1", -0.48, 0, 0.56, 0.62),
    smd_pad("2", 0.48, 0, 0.56, 0.62),
])
write("C_0805_2012Metric", "0805 capacitor, IPC nominal", [
    outline(2.0, 1.25), smd_pad("1", -0.95, 0, 1.0, 1.45),
    smd_pad("2", 0.95, 0, 1.0, 1.45),
])
write("R_0402_1005Metric", "0402 resistor, IPC nominal", [
    outline(1.05, 0.54), smd_pad("1", -0.51, 0, 0.54, 0.64),
    smd_pad("2", 0.51, 0, 0.54, 0.64),
])
write("SOIC-8_3.9x4.9mm_P1.27mm", "JEDEC MS-012AA SOIC-8", [
    outline(3.9, 4.9),
    *[smd_pad(str(index + 1), -2.475, -1.905 + index * 1.27, 1.95, 0.6)
      for index in range(4)],
    *[smd_pad(str(8 - index), 2.475, -1.905 + index * 1.27, 1.95, 0.6)
      for index in range(4)],
])
write("SOT-89-3", "SOT-89-3 for AMS1117-3.3", [
    outline(2.5, 4.5), smd_pad("1", -1.95, -1.5, 1.3, 0.9),
    smd_pad("2", -0.3, 0, 4.6, 1.73), smd_pad("3", -1.95, 1.5, 1.3, 0.9),
])
write("Crystal_YSX321SL", "YSX321SL 3.2x2.5 mm crystal", [
    outline(3.2, 2.5), smd_pad("1", -1.1, 0.85, 1.4, 1.2),
    smd_pad("2", 1.1, 0.85, 1.4, 1.2), smd_pad("3", 1.1, -0.85, 1.4, 1.2),
    smd_pad("4", -1.1, -0.85, 1.4, 1.2),
])

header_body = [outline(2.54, 12.7), "\t(attr through_hole)"]
for index in range(5):
    shape = "rect" if index == 0 else "circle"
    header_body.append(
        f'\t(pad "{index + 1}" thru_hole {shape} (at 0 {index * 2.54:g}) '
        '(size 1.7 1.7) (drill 1) (layers "*.Cu" "*.Mask"))')
write("PinHeader_1x05_P2.54mm_Vertical", "1x05 2.54 mm SWD header", header_body)

qfn = [outline(7, 7)]
for index in range(14):
    qfn.append(smd_pad(str(index + 1), -3.4375, -2.6 + index * 0.4, 0.875, 0.2))
    qfn.append(smd_pad(str(index + 15), -2.6 + index * 0.4, 3.4375, 0.2, 0.875))
    qfn.append(smd_pad(str(index + 29), 3.4375, 2.6 - index * 0.4, 0.875, 0.2))
    qfn.append(smd_pad(str(index + 43), 2.6 - index * 0.4, -3.4375, 0.2, 0.875))
qfn.append(smd_pad("57", 0, 0, 3.2, 3.2))
write("QFN-56-1EP_7x7mm_P0.4mm_EP3.2x3.2mm", "RP2040 QFN-56 exposed pad", qfn)

usb = [outline(8.94, 7.35)]
usb_pin_numbers = ["1", "2", "4", "6", "7", "9", "2", "12",
                   "12", "11", "3", "5", "8", "10", "11", "1"]
for index, number in enumerate(usb_pin_numbers):
    usb.append(smd_pad(number, -3.75 + index * 0.5, 0, 0.3, 1.2))
for number, x in (("13", -4.32), ("14", 4.32)):
    for y in (1.9, 4.5):
        usb.append(
            f'\t(pad "{number}" thru_hole oval (at {x:g} {y:g}) (size 1.6 1.1) '
            '(drill oval 1.2 0.6) (layers "*.Cu" "*.Mask"))')
for x in (-2.89, 2.89):
    usb.append(
        f'\t(pad "" np_thru_hole circle (at {x:g} 1.5) (size 0.65 0.65) '
        '(drill 0.65) (layers "*.Cu" "*.Mask"))')
write("USB_C_16P_2MD_073", "Shouhan TYPE-C 16PIN 2MD(073)", usb)