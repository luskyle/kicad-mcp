"""用 libngspice（ctypes）跑 SPICE netlist 仿真的最小验证（正确签名版）。

正确的初始化是 ngSpice_Init（7 个回调参数），不是 ngSpice_Init_Sync（5 参、
用于外部电压源同步）。回调返回 int。
仿真后通过 wrdata 命令把波形写文件，再解析。
"""
import ctypes
import os
import sys

NETLIST = "/tmp/rc_pre.spice"
OUT = "/tmp/rc_out.txt"

lib = ctypes.CDLL("libngspice.so.0")

# 回调类型（返回 int）
SENDCHAR = ctypes.CFUNCTYPE(ctypes.c_int, ctypes.c_char_p, ctypes.c_int, ctypes.c_void_p)
SENDSTAT = ctypes.CFUNCTYPE(ctypes.c_int, ctypes.c_char_p, ctypes.c_int, ctypes.c_void_p)
CONTROLLED_EXIT = ctypes.CFUNCTYPE(ctypes.c_int, ctypes.c_int, ctypes.c_bool,
                                   ctypes.c_bool, ctypes.c_int, ctypes.c_void_p)
SENDDATA = ctypes.CFUNCTYPE(ctypes.c_int, ctypes.c_void_p, ctypes.c_int,
                            ctypes.c_int, ctypes.c_void_p)
SENDINITDATA = ctypes.CFUNCTYPE(ctypes.c_int, ctypes.c_void_p, ctypes.c_int, ctypes.c_void_p)
BGTHREAD = ctypes.CFUNCTYPE(ctypes.c_int, ctypes.c_bool, ctypes.c_int, ctypes.c_void_p)


@SENDCHAR
def send_char(s, ident, user):
    if s:
        sys.stderr.write(s.decode("utf-8", "replace"))
    return 0


@SENDSTAT
def send_stat(s, ident, user):
    if s:
        sys.stderr.write(s.decode("utf-8", "replace"))
    return 0


@CONTROLLED_EXIT
def controlled_exit(status, immediate, on_quit, ident, user):
    print(f"\n[ngspice 请求退出] status={status} immediate={immediate} on_quit={on_quit}")
    return 0


@SENDDATA
def send_data(data, num_plots, num_vects, user):
    return 0


@SENDINITDATA
def send_init_data(data, num_plots, user):
    return 0


@BGTHREAD
def bg_thread(running, ident, user):
    return 0


def init_ngspice():
    fn = lib.ngSpice_Init
    fn.argtypes = [ctypes.c_void_p] * 7
    fn.restype = ctypes.c_int
    r = fn(send_char, send_stat, controlled_exit, send_data, send_init_data,
           bg_thread, None)
    print(f"ngSpice_Init -> {r}")
    return r


def run_commands(cmds):
    lib.ngSpice_Command.argtypes = [ctypes.c_char_p]
    lib.ngSpice_Command.restype = ctypes.c_int
    for c in cmds:
        print(f">>> {c}", flush=True)
        r = lib.ngSpice_Command(c.encode("utf-8"))
        print(f"    ret={r}", flush=True)


if __name__ == "__main__":
    init_ngspice()
    print("\n--- 运行仿真 ---")
    run_commands([
        f"source {NETLIST}",
        "run",
        f"wrdata {OUT} v(/OUT) v(/VIN)",
    ])
    print("\n--- wrdata 结果 ---")
    if os.path.exists(OUT):
        with open(OUT) as f:
            print(f.read())
    else:
        print("无输出文件（仿真可能出错）")
