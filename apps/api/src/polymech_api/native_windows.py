"""Windows Credential Manager and process handles, using the OS APIs directly.

https://learn.microsoft.com/windows/win32/api/wincred/nf-wincred-credreadw
https://learn.microsoft.com/windows/win32/api/synchapi/nf-synchapi-waitforsingleobject
"""

from __future__ import annotations

import ctypes
from ctypes import wintypes
from typing import cast


def _library(name: str) -> ctypes.CDLL:
    # Windows-only ctypes names are resolved lazily so macOS can collect this module.
    return cast(ctypes.CDLL, getattr(ctypes, "WinDLL")(name, use_last_error=True))  # noqa: B009


def _error_code() -> int:
    return cast(int, getattr(ctypes, "get_last_error")())  # noqa: B009


def _error() -> OSError:
    return cast(OSError, getattr(ctypes, "WinError")())  # noqa: B009


class _Credential(ctypes.Structure):
    _fields_ = [
        ("Flags", wintypes.DWORD),
        ("Type", wintypes.DWORD),
        ("TargetName", wintypes.LPWSTR),
        ("Comment", wintypes.LPWSTR),
        ("LastWritten", wintypes.FILETIME),
        ("CredentialBlobSize", wintypes.DWORD),
        ("CredentialBlob", ctypes.POINTER(wintypes.BYTE)),
        ("Persist", wintypes.DWORD),
        ("AttributeCount", wintypes.DWORD),
        ("Attributes", wintypes.LPVOID),
        ("TargetAlias", wintypes.LPWSTR),
        ("UserName", wintypes.LPWSTR),
    ]


def _credentials() -> ctypes.CDLL:
    api = _library("advapi32")
    api.CredReadW.argtypes = [
        wintypes.LPCWSTR,
        wintypes.DWORD,
        wintypes.DWORD,
        ctypes.POINTER(ctypes.POINTER(_Credential)),
    ]
    api.CredWriteW.argtypes = [ctypes.POINTER(_Credential), wintypes.DWORD]
    api.CredDeleteW.argtypes = [wintypes.LPCWSTR, wintypes.DWORD, wintypes.DWORD]
    for name in ("CredReadW", "CredWriteW", "CredDeleteW"):
        getattr(api, name).restype = wintypes.BOOL
    api.CredFree.argtypes = [wintypes.LPVOID]
    api.CredFree.restype = None
    return api


def get_credential(name: str) -> str | None:
    api = _credentials()
    credential = ctypes.POINTER(_Credential)()
    if not api.CredReadW(f"PolyMechStudio/{name}", 1, 0, ctypes.byref(credential)):
        if _error_code() == 1168:  # ERROR_NOT_FOUND
            return None
        raise _error()
    try:
        item = credential.contents
        return ctypes.string_at(item.CredentialBlob, item.CredentialBlobSize).decode("utf-16-le")
    finally:
        api.CredFree(credential)


def set_credential(name: str, value: str) -> None:
    blob = ctypes.create_string_buffer(value.encode("utf-16-le"))
    item = _Credential()
    item.Type = 1  # CRED_TYPE_GENERIC
    item.TargetName = f"PolyMechStudio/{name}"
    item.CredentialBlobSize = len(value.encode("utf-16-le"))
    item.CredentialBlob = ctypes.cast(blob, ctypes.POINTER(wintypes.BYTE))
    item.Persist = 2  # CRED_PERSIST_LOCAL_MACHINE: this user's later login sessions
    item.UserName = "PolyMech Studio"
    if not _credentials().CredWriteW(ctypes.byref(item), 0):
        raise _error()


def delete_credential(name: str) -> None:
    if not _credentials().CredDeleteW(f"PolyMechStudio/{name}", 1, 0) and _error_code() != 1168:
        raise _error()


def wait_for_process_exit(pid: int) -> None:
    api = _library("kernel32")
    api.OpenProcess.argtypes = [wintypes.DWORD, wintypes.BOOL, wintypes.DWORD]
    api.OpenProcess.restype = wintypes.HANDLE
    api.WaitForSingleObject.argtypes = [wintypes.HANDLE, wintypes.DWORD]
    api.WaitForSingleObject.restype = wintypes.DWORD
    api.CloseHandle.argtypes = [wintypes.HANDLE]
    api.CloseHandle.restype = wintypes.BOOL
    handle = api.OpenProcess(0x00100000, False, pid)  # SYNCHRONIZE
    if not handle:
        if _error_code() == 87:  # process already gone before OpenProcess
            return
        raise _error()
    try:
        if api.WaitForSingleObject(handle, 0xFFFFFFFF) != 0:  # INFINITE / WAIT_OBJECT_0
            raise _error()
    finally:
        api.CloseHandle(handle)
