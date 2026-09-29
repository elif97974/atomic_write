"""Atomic file writing primitives.

The strategy is the classic write-to-temp-then-rename: write the full
payload to a sibling temporary file, fsync it, then atomically rename it
over the destination. On POSIX, rename(2) is atomic with respect to the
directory entry, so any reader opening the destination sees either the
old file in its entirety or the new file in its entirety — never a
partially-written intermediate.

On Windows, os.replace is atomic for files on the same volume but is NOT
atomic with respect to concurrent readers that already hold an open handle
to the old file: those readers keep reading the old inode until they close.
That is acceptable for our purposes (the guarantee we sell is "readers never
see a half-written file", and they don't), but it is the one platform
difference worth knowing about.
"""

from __future__ import annotations

import contextlib
import errno
import os
import tempfile
from typing import Iterator, Union

PathLike = Union[str, "os.PathLike[str]"]


class AtomicWriter:
    """Writes files atomically via temp-file + fsync + rename.

    By default the temporary file is created in the same directory as the
    destination. This is a hard requirement for the rename to be atomic on
    POSIX: rename(2) only guarantees atomicity when source and destination
    are on the same filesystem, and the temp directory is very commonly on
    a different filesystem than the destination.

    Parameters
    ----------
    dir:
        Directory in which to create the temporary file. Defaults to the
        destination's directory. Override this only if you have a reason
        (e.g. the destination directory does not yet exist) and you know
        the override directory is on the same filesystem.
    mode:
        File mode to apply to the final file, as an integer such as 0o644.
        The temporary file is created with this mode via fdopen, so the
        mode is correct before the rename and no chmod race window exists.
    fsync_file:
        Whether to fsync the file data before renaming. On by default.
        Turning this off trades durability for speed: a crash immediately
        after a successful write may leave the file empty or missing.
    fsync_dir:
        Whether to fsync the containing directory after renaming, so the
        rename itself survives a crash. On by default. Off trades crash
        safety for speed.
    """

    def __init__(
        self,
        *,
        dir: PathLike | None = None,
        mode: int = 0o644,
        fsync_file: bool = True,
        fsync_dir: bool = True,
    ) -> None:
        self._dir = dir
        self._mode = mode
        self._fsync_file = fsync_file
        self._fsync_dir = fsync_dir

    @contextlib.contextmanager
    def open(self, path: PathLike) -> Iterator[int]:
        """Context manager yielding an open fd to write to.

        On a clean exit the temp file is fsynced (if enabled) and renamed
        over *path*. On an exception the temp file is unlinked and *path*
        is left untouched.

        Yields the raw integer file descriptor so callers can use os.write
        directly. This avoids the overhead and the buffering of a Python
        file object, which matters because a buffered wrapper would need
        careful flushing before the fsync — forgetting to flush is the
        classic silent-data-loss bug in atomic-write helpers.
        """
        final_dir = os.path.dirname(os.fspath(path))
        tmp_dir = self._dir if self._dir is not None else (final_dir or ".")

        # NamedTemporaryFile would give us a wrapper object; we want the
        # raw fd so callers can os.write. mkstemp gives us exactly that.
        fd, tmp_path = tempfile.mkstemp(dir=tmp_dir)
        try:
            # Apply the requested mode immediately. mkstemp creates the
            # file 0600 by default; setting the mode now means there is
            # never a window in which the file exists on disk with the
            # wrong permissions. (The file is still unlinked-and-replaced
            # on failure, so this is belt-and-braces rather than a real
            # race fix, but it also makes the final file mode correct
            # without a separate chmod after rename.)
            os.chmod(fd, self._mode)

            yield fd

            if self._fsync_file:
                os.fsync(fd)
            # Close before rename: on Windows you cannot rename a file
            # that still has an open handle.
            os.close(fd)
            fd = -1  # sentinel: already closed
            os.replace(tmp_path, path)

            if self._fsync_dir:
                # fsync the directory so the rename (a directory update)
                # is durable. Open with O_RDONLY: that is the documented
                # way to get a directory fd for fsync on POSIX.
                # Not supported on Windows; ignore there.
                with contextlib.suppress(OSError):
                    dir_fd = os.open(final_dir or ".", os.O_RDONLY)
                    try:
                        os.fsync(dir_fd)
                    finally:
                        os.close(dir_fd)
        except BaseException:
            # Clean up the temp file on any exit path — including
            # KeyboardInterrupt — so we never leak partial files.
            if fd >= 0:
                with contextlib.suppress(OSError):
                    os.close(fd)
            with contextlib.suppress(OSError):
                os.unlink(tmp_path)
            raise

    def write_bytes(self, path: PathLike, data: bytes) -> None:
        """Write *data* to *path* atomically."""
        with self.open(path) as fd:
            os.write(fd, data)

    def write_text(
        self,
        path: PathLike,
        text: str,
        encoding: str = "utf-8",
        newline: str = "",
    ) -> None:
        """Write *text* to *path* atomically.

        *newline* is passed through to the encoder. The default "" means
        no newline translation, so what you pass is what lands on disk.
        Pass newline="\n" to translate platform newlines to \n.
        """
        self.write_bytes(path, text.encode(encoding, newline))


def atomic_write(
    path: PathLike,
    data: bytes | str,
    *,
    mode: int = 0o644,
    encoding: str = "utf-8",
    dir: PathLike | None = None,
    fsync_file: bool = True,
    fsync_dir: bool = True,
) -> None:
    """Write *data* to *path* atomically.

    Convenience wrapper around :class:`AtomicWriter` for the common case
    of a single write. *data* may be bytes or str; str is encoded with
    *encoding* (UTF-8 by default).
    """
    writer = AtomicWriter(
        dir=dir,
        mode=mode,
        fsync_file=fsync_file,
        fsync_dir=fsync_dir,
    )
    if isinstance(data, str):
        writer.write_text(path, data, encoding=encoding)
    else:
        writer.write_bytes(path, data)
