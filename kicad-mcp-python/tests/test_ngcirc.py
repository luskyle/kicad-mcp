"""测试 ngSpice_Circ 加载未预处理（含 power 占位行）的 netlist 并 bg_run。"""
import ctypes
import sys
import time

lib = ctypes.CDLL("libngspice.so.0")

SC = ctypes.CFUNCTYPE(ctypes.c_int, ctypes.c_char_p, ctypes.c_int, ctypes.c_void_p)
ST = ctypes.CFUNCTYPE(ctypes.c_int, ctypes.c_char_p, ctypes.c_int, ctypes.c_void_p)


@SC
def sc(s, i, u):
    if s:
        sys.stderr.write("[out] " + s.decode("utf-8", "replace"))
    return 0


@ST
def st(s, i, u):
    if s:
        sys.stderr.write("[stat] " + s.decode("utf-8", "replace"))
    return 0


fn = lib.ngSpice_Init
fn.argtypes = [ctypes.c_void_p] * 7
fn.restype = ctypes.c_int
print("init =", fn(sc, st, None, None, None, None, None), flush=True)

lib.ngSpice_Command.argtypes = [ctypes.c_char_p]
lib.ngSpice_Command.restype = ctypes.c_int

# ngSpice_Circ: char** 数组，最后 NULL
lib.ngSpice_Circ.argtypes = [ctypes.POINTER(ctypes.c_char_p)]
lib.ngSpice_Circ.restype = ctypes.c_int

text = open("/tmp/rc.spice").read()
lines = [l for l in text.splitlines() if l.strip()]
carr = (ctypes.c_char_p * (len(lines) + 1))()
for i, l in enumerate(lines):
    carr[i] = l.encode()
carr[len(lines)] = None

print("ngSpice_Circ ->", lib.ngSpice_Circ(carr), flush=True)
print("run bg_run ->", lib.ngSpice_Command(b"bg_run"), flush=True)

# 等待仿真完成
for i in range(20):
    time.sleep(0.5)
    ret = lib.ngSpice_Command(b"display")
print("done", flush=True)
