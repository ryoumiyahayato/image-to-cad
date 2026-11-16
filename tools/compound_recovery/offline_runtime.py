"""Make a local research process offline before it loads inference libraries."""
from __future__ import annotations

import ctypes
import ctypes.util
import errno
import os
import socket
import sys


def enforce_offline_runtime() -> dict:
    os.environ['ORT_DISABLE_TELEMETRY'] = '1'
    if 'onnxruntime' in sys.modules:
        raise RuntimeError('Offline policy must precede ONNX Runtime import')
    if sys.platform != 'linux':
        raise RuntimeError('This reproduction guard requires Linux libseccomp')
    name = ctypes.util.find_library('seccomp')
    if not name:
        raise RuntimeError('libseccomp is required; no unguarded fallback')
    lib = ctypes.CDLL(name, use_errno=True)
    lib.seccomp_init.argtypes = [ctypes.c_uint32]
    lib.seccomp_init.restype = ctypes.c_void_p
    lib.seccomp_syscall_resolve_name.argtypes = [ctypes.c_char_p]
    lib.seccomp_syscall_resolve_name.restype = ctypes.c_int
    lib.seccomp_rule_add.argtypes = [ctypes.c_void_p, ctypes.c_uint32, ctypes.c_int, ctypes.c_uint]
    lib.seccomp_rule_add.restype = ctypes.c_int
    lib.seccomp_load.argtypes = [ctypes.c_void_p]
    lib.seccomp_load.restype = ctypes.c_int
    lib.seccomp_release.argtypes = [ctypes.c_void_p]
    ctx = lib.seccomp_init(0x7fff0000)
    if not ctx:
        raise RuntimeError('Cannot initialize offline filter')
    blocked = ('socket', 'connect', 'sendto', 'sendmsg', 'sendmmsg')
    try:
        for call in blocked:
            number = lib.seccomp_syscall_resolve_name(call.encode('ascii'))
            if number < 0 or lib.seccomp_rule_add(ctx, 0x00050000 | errno.EPERM, number, 0) != 0:
                raise RuntimeError('Cannot install offline syscall rule: ' + call)
        if lib.seccomp_load(ctx) != 0:
            raise RuntimeError('Cannot enforce offline filter')
    finally:
        lib.seccomp_release(ctx)
    for family in (socket.AF_INET, socket.AF_INET6):
        try:
            probe = socket.socket(family, socket.SOCK_STREAM)
        except OSError as exc:
            if exc.errno != errno.EPERM:
                raise RuntimeError('Unexpected offline self-check result') from exc
        else:
            probe.close()
            raise RuntimeError('Offline network self-check failed')
    import onnxruntime
    onnxruntime.disable_telemetry_events()
    return {'telemetry_disabled_before_import': True,
            'network_syscalls_denied': list(blocked),
            'ipv4_ipv6_socket_selfcheck': 'EPERM',
            'onnxruntime': onnxruntime.__version__}
