import os
import tempfile
import unittest

from atomic_write import atomic_write, AtomicWriter


class TestAtomicWrite(unittest.TestCase):

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.dir = self.tmp.name

    def _path(self, name="target.txt"):
        return os.path.join(self.dir, name)

    # --- happy path ---------------------------------------------------

    def test_write_bytes_creates_file_with_content(self):
        p = self._path()
        atomic_write(p, b"hello world")
        with open(p, "rb") as f:
            self.assertEqual(f.read(), b"hello world")

    def test_write_text_encodes_utf8(self):
        p = self._path()
        atomic_write(p, "café — résumé")
        with open(p, "rb") as f:
            self.assertEqual(f.read(), "café — résumé".encode("utf-8"))

    def test_write_text_custom_encoding(self):
        p = self._path()
        atomic_write(p, "olé", encoding="latin-1")
        with open(p, "rb") as f:
            self.assertEqual(f.read(), "olé".encode("latin-1"))

    def test_overwrite_replaces_existing_content(self):
        p = self._path()
        atomic_write(p, b"old content that is longer")
        atomic_write(p, b"new")
        with open(p, "rb") as f:
            self.assertEqual(f.read(), b"new")

    def test_empty_payload(self):
        p = self._path()
        atomic_write(p, b"")
        with open(p, "rb") as f:
            self.assertEqual(f.read(), b"")
        self.assertEqual(os.path.getsize(p), 0)

    # --- permissions --------------------------------------------------

    def test_mode_applied(self):
        p = self._path()
        atomic_write(p, b"x", mode=0o600)
        mode = os.stat(p).st_mode & 0o777
        self.assertEqual(mode, 0o600)

    def test_default_mode_is_644(self):
        p = self._path()
        atomic_write(p, b"x")
        mode = os.stat(p).st_mode & 0o777
        # umask may clear some bits, so check the bits that survive.
        # We expect at least 0o644 & ~umask; on most systems that is 0o644.
        self.assertEqual(mode, 0o644 & ~self._umask())

    @staticmethod
    def _umask():
        # umask is process-global and inherited; query it without changing it.
        m = os.umask(0)
        os.umask(m)
        return m

    # --- failure paths ------------------------------------------------

    def test_exception_leaves_existing_file_untouched(self):
        p = self._path()
        atomic_write(p, b"original")

        class Boom(Exception):
            pass

        writer = AtomicWriter()
        with self.assertRaises(Boom):
            with writer.open(p) as fd:
                os.write(fd, b"partial garbage")
                raise Boom()

        with open(p, "rb") as f:
            self.assertEqual(f.read(), b"original")

    def test_exception_cleans_up_temp_file(self):
        p = self._path()
        before = set(os.listdir(self.dir))

        class Boom(Exception):
            pass

        with self.assertRaises(Boom):
            with AtomicWriter().open(p) as fd:
                os.write(fd, b"x")
                raise Boom()

        after = set(os.listdir(self.dir))
        self.assertEqual(before, after)

    # --- AtomicWriter API ---------------------------------------------

    def test_writer_write_bytes(self):
        p = self._path()
        AtomicWriter().write_bytes(p, b"abc")
        with open(p, "rb") as f:
            self.assertEqual(f.read(), b"abc")

    def test_writer_write_text_default_encoding(self):
        p = self._path()
        AtomicWriter().write_text(p, "naïve")
        with open(p, "rb") as f:
            self.assertEqual(f.read(), "naïve".encode("utf-8"))

    def test_writer_open_yields_writable_fd(self):
        p = self._path()
        with AtomicWriter().open(p) as fd:
            os.write(fd, b"via fd")
        with open(p, "rb") as f:
            self.assertEqual(f.read(), b"via fd")

    # --- fsync flags --------------------------------------------------

    def test_fsync_disabled_still_writes(self):
        p = self._path()
        atomic_write(p, b"no fsync", fsync_file=False, fsync_dir=False)
        with open(p, "rb") as f:
            self.assertEqual(f.read(), b"no fsync")

    # --- nested directory ---------------------------------------------

    def test_nested_destination_directory(self):
        nested = os.path.join(self.dir, "sub", "deep")
        os.makedirs(nested)
        p = os.path.join(nested, "file.txt")
        atomic_write(p, b"nested")
        with open(p, "rb") as f:
            self.assertEqual(f.read(), b"nested")


if __name__ == "__main__":
    unittest.main()
