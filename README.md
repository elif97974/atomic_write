# atomic_write

Write files atomically so readers never see a half-written file.

```python
from atomic_write import atomic_write, AtomicWriter

# one-shot convenience function
atomic_write("/etc/app.conf", b"key=value\n")

# or use the class for repeated writes with the same options
writer = AtomicWriter(mode=0o600)
writer.write_text("/etc/app.conf", "key=value\n")
```

## Why

A process that opens a file for writing and then writes into it exposes a
window in which readers see a truncated or partially-written file. The
fix is to write the full payload to a temporary file in the same
directory, fsync it, and rename it over the destination. `rename(2)` on
POSIX is atomic with respect to the directory entry, so readers see
either the old file or the new file — never an intermediate state.

This library does exactly that, and nothing else. It does not retry on
failure, it does not lock files, it does not manage backups. If the
write fails the destination is untouched; if it succeeds the destination
is fully replaced.

## Edge cases worth knowing

- The temporary file is created in the same directory as the destination
  by default, because `rename` is only atomic within a single filesystem.
  If the destination directory does not exist, pass `dir=` to point at an
  existing directory on the same filesystem.
- On Windows, `os.replace` is atomic for the directory entry, but readers
  that already hold an open handle to the old file continue reading the
  old inode until they close it. They never see partial data, but they
  also don't see the new data until they reopen.
- `fsync_file` and `fsync_dir` are on by default for crash safety. Turn
  them off only if you are writing transient data you can afford to lose
  on power failure.

## Exports

- `atomic_write(path, data, *, mode=0o644, encoding="utf-8", dir=None, fsync_file=True, fsync_dir=True)`
- `AtomicWriter(dir=None, mode=0o644, fsync_file=True, fsync_dir=True)` with methods `open(path)` (context manager yielding an fd), `write_bytes(path, data)`, and `write_text(path, text, encoding="utf-8", newline="")`.
