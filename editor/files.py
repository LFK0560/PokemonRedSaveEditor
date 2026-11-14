from contextlib import contextmanager
from dataclasses import dataclass
from datetime import date
from hashlib import sha256
import os
from pathlib import Path
from tempfile import NamedTemporaryFile

from .rom import Catalog
from .save import InvalidSave, SAVE_SIZE, Save


class ChangedOnDisk(OSError):
    pass


@dataclass(frozen=True)
class Snapshot:
    data: bytes
    identity: tuple[int, ...]


def identity(stat: os.stat_result) -> tuple[int, ...]:
    return stat.st_dev, stat.st_ino, stat.st_mtime_ns, stat.st_size


def snapshot(path: Path, open_file=open) -> Snapshot:
    with open_file(path, "rb") as file:
        before = identity(os.fstat(file.fileno()))
        raw = file.read(SAVE_SIZE + 1)
        if identity(os.fstat(file.fileno())) != before or identity(path.stat()) != before:
            raise ChangedOnDisk("读取时存档发生变化。等模拟器写入完成后再试。")
        if before[-1] != len(raw):
            raise InvalidSave(f"存档为 {before[-1]:,} 字节，此 ROM 的 SRAM 存档须为 32,768 字节。")
    return Snapshot(raw, before)


@contextmanager
def staged_file(folder: Path, data: bytes):
    with NamedTemporaryFile(mode="wb", prefix=".pkred-", suffix=".tmp", dir=folder, delete=False) as file:
        path = Path(file.name)
        try:
            file.write(data)
            file.flush()
            os.fsync(file.fileno())
            file.close()
            if path.read_bytes() != data:
                raise OSError("临时文件重新读取后的内容与预期不一致。")
            yield path
        finally:
            file.close()
            path.unlink(missing_ok=True)


def move_new(staged: Path, destination: Path) -> None:
    if os.name == "nt":
        os.rename(staged, destination)
    else:
        os.link(staged, destination)


def backup(path: Path, data: bytes, *, overwrite: bool = False, day: date | None = None) -> Path:
    folder = path.parent / "备份" / (day or date.today()).isoformat()
    folder.mkdir(parents=True, exist_ok=True)
    ext = ".srm.bak" if path.name.lower().endswith(".srm.bak") else path.suffix
    stem = path.name[:-len(ext)] if ext else path.name
    if overwrite:
        stem += "_覆盖前"
    number = 1
    with staged_file(folder, data) as staged:
        while True:
            suffix = f"_{number}" if number > 1 else ""
            destination = folder / f"{stem}{suffix}{ext}"
            try:
                move_new(staged, destination)
            except FileExistsError:
                number += 1
            else:
                return destination


@contextmanager
def write_lock(path: Path):
    if os.name != "nt":
        yield
        return
    from ctypes import WinDLL, WinError, get_last_error
    from ctypes.wintypes import BOOL, DWORD, HANDLE, LPCWSTR, LPVOID

    kernel = WinDLL("kernel32", use_last_error=True)
    kernel.CreateMutexW.argtypes = (LPVOID, BOOL, LPCWSTR)
    kernel.CreateMutexW.restype = HANDLE
    kernel.WaitForSingleObject.argtypes = (HANDLE, DWORD)
    kernel.WaitForSingleObject.restype = DWORD
    kernel.ReleaseMutex.argtypes = (HANDLE,)
    kernel.CloseHandle.argtypes = (HANDLE,)
    normalized = os.path.normcase(str(path))
    digest = sha256(normalized.encode("utf-8")).hexdigest()
    mutex = kernel.CreateMutexW(None, False, "Local\\PokemonRedSaveEditor-" + digest)
    if not mutex:
        raise WinError(get_last_error())
    try:
        result = kernel.WaitForSingleObject(mutex, 0)
        if result == 258:
            raise ChangedOnDisk("另一个编辑器窗口正在写同一存档，请稍后重试。")
        if result not in (0, 128):
            raise WinError(get_last_error())
        try:
            yield
        finally:
            kernel.ReleaseMutex(mutex)
    finally:
        kernel.CloseHandle(mutex)


def open_without_write_sharing(path: Path, mode: str):
    if os.name != "nt":
        return open(path, mode)
    from ctypes import WinDLL, WinError, get_last_error
    from ctypes.wintypes import DWORD, HANDLE, LPCWSTR, LPVOID
    from msvcrt import open_osfhandle

    kernel = WinDLL("kernel32", use_last_error=True)
    kernel.CreateFileW.argtypes = (LPCWSTR, DWORD, DWORD, LPVOID, DWORD, DWORD, HANDLE)
    kernel.CreateFileW.restype = HANDLE
    kernel.CloseHandle.argtypes = (HANDLE,)
    # Share READ and DELETE so atomic replacement can proceed. An emulator
    # holding or requesting a write handle cannot change the guarded inode.
    handle = kernel.CreateFileW(str(path), 0x80000000, 5, None, 3, 0x80, None)
    if handle == HANDLE(-1).value:
        raise WinError(get_last_error())
    try:
        fd = open_osfhandle(handle, os.O_BINARY | os.O_RDONLY)
    except Exception:
        kernel.CloseHandle(handle)
        raise
    return os.fdopen(fd, mode)


def replace_guarded(staged: Path, destination: Path) -> None:
    if os.name != "nt":
        os.replace(staged, destination)
        return
    from ctypes import Structure, WinDLL, WinError, addressof, c_int, create_string_buffer, get_last_error, memmove
    from ctypes.wintypes import BOOL, DWORD, HANDLE, LPCWSTR, LPVOID, WCHAR

    class RenameInfo(Structure):
        _fields_ = [("flags", DWORD), ("root", HANDLE), ("length", DWORD), ("name", WCHAR)]

    kernel = WinDLL("kernel32", use_last_error=True)
    kernel.CreateFileW.argtypes = (LPCWSTR, DWORD, DWORD, LPVOID, DWORD, DWORD, HANDLE)
    kernel.CreateFileW.restype = HANDLE
    kernel.SetFileInformationByHandle.argtypes = (HANDLE, c_int, LPVOID, DWORD)
    kernel.SetFileInformationByHandle.restype = BOOL
    kernel.CloseHandle.argtypes = (HANDLE,)
    name = str(destination).encode("utf-16-le")
    size = max(RenameInfo.name.offset + len(name) + 2, 32)
    buffer = create_string_buffer(size)
    info = RenameInfo.from_buffer(buffer)
    # FILE_RENAME_REPLACE_IF_EXISTS | FILE_RENAME_POSIX_SEMANTICS.
    # POSIX semantics let the verified original stay open until the rename.
    info.flags = 3
    info.length = len(name)
    memmove(addressof(buffer) + RenameInfo.name.offset, name, len(name))
    handle = kernel.CreateFileW(str(staged), 0x10000, 7, None, 3, 0x80, None)
    if handle == HANDLE(-1).value:
        raise WinError(get_last_error())
    try:
        if not kernel.SetFileInformationByHandle(handle, 22, buffer, size):
            raise WinError(get_last_error())
    finally:
        kernel.CloseHandle(handle)


class Document:
    def __init__(self, path: Path, source: Snapshot, model: Save, backup_path: Path):
        self.path = path
        self.source = source
        self.model = model
        self.import_backup = backup_path

    @classmethod
    def load(cls, path: Path, catalog: Catalog, map_ids=None) -> "Document":
        path = path.resolve(strict=True)
        source = snapshot(path)
        model = Save(catalog, source.data, map_ids)
        return cls(path, source, model, backup(path, source.data))

    def save(self, destination: Path | None = None, expected: Snapshot | None = None) -> Path | None:
        target = destination.resolve() if destination else self.path
        same_path = target == self.path
        expected = self.source if same_path else expected
        model = self.model
        model.validate()
        data = bytes(model.data)
        with write_lock(target):
            if expected is None:
                with staged_file(target.parent, data) as staged:
                    Save(model.catalog, staged.read_bytes(), model.map_ids)
                    try:
                        move_new(staged, target)
                    except FileExistsError:
                        raise ChangedOnDisk("目标文件在保存前出现，请重新选择另存路径。") from None
                previous = None
            else:
                with open_without_write_sharing(target, "rb") as current:
                    def verify_current():
                        current.seek(0)
                        if (identity(os.fstat(current.fileno())) != expected.identity
                                or current.read(SAVE_SIZE + 1) != expected.data
                                or identity(target.stat()) != expected.identity):
                            raise ChangedOnDisk("原存档在打开后已更新。编辑仍在内存中，可使用「另存为」。")

                    verify_current()
                    if data == expected.data:
                        previous = None
                    else:
                        with staged_file(target.parent, data) as staged:
                            Save(model.catalog, staged.read_bytes(), model.map_ids)
                            previous = backup(target, expected.data, overwrite=True)
                            verify_current()
                            replace_guarded(staged, target)
            written = snapshot(target)
            if written.data != data:
                raise ChangedOnDisk("写入后复读发现磁盘文件又发生了变化。编辑仍在内存中。")
            self.source = written
        self.path = target
        model.original = data
        return previous
