"""Tests for typed-validator's symlink resolution.

Every test builds its own temporary directory under tempfile.mkdtemp so the
suite is hermetic and does not touch the caller's filesystem. All paths are
constructed inside that temp dir; no external addresses are referenced.
"""

from __future__ import annotations

import os
import tempfile
import unittest

from typed_validator import SymlinkValidator, SymlinkResult


class SymlinkValidatorTests(unittest.TestCase):

    def setUp(self) -> None:
        # mkdtemp gives us a real directory we can shape freely; we remove it
        # in tearDown so the suite leaves no trace.
        self._dir = tempfile.mkdtemp(prefix="typed_validator_")
        # Use addCleanup so cleanup still runs even if setUp fails partway.
        self.addCleanup(self._cleanup, self._dir)

    @staticmethod
    def _cleanup(path: str) -> None:
        # Walk bottom-up so directories are emptied before removal.
        for root, dirs, files in os.walk(path, topdown=False):
            for name in files:
                try:
                    os.remove(os.path.join(root, name))
                except OSError:
                    pass
            for name in dirs:
                try:
                    os.rmdir(os.path.join(root, name))
                except OSError:
                    pass
        try:
            os.rmdir(path)
        except OSError:
            pass

    # ---- helpers ----------------------------------------------------------

    def _path(self, name: str) -> str:
        return os.path.join(self._dir, name)

    def _make_regular(self, name: str) -> str:
        p = self._path(name)
        with open(p, "w", encoding="utf-8") as fh:
            fh.write("hello")
        return p

    def _make_dir(self, name: str) -> str:
        p = self._path(name)
        os.mkdir(p)
        return p

    def _make_symlink(self, name: str, target: str) -> str:
        p = self._path(name)
        os.symlink(target, p)
        return p

    # ---- happy path: not a symlink at all --------------------------------

    def test_regular_file_exists(self) -> None:
        f = self._make_regular("file.txt")
        r = SymlinkValidator().validate(f)
        self.assertEqual(r.status, "valid")
        self.assertEqual(r.target, os.path.abspath(f))
        self.assertEqual(r.depth, 0)

    def test_regular_dir_exists(self) -> None:
        d = self._make_dir("subdir")
        r = SymlinkValidator().validate(d)
        self.assertEqual(r.status, "valid")
        self.assertEqual(r.depth, 0)

    # ---- happy path: simple symlink to a real file ------------------------

    def test_simple_symlink_to_file(self) -> None:
        target = self._make_regular("target.txt")
        link = self._make_symlink("link.txt", target)
        r = SymlinkValidator().validate(link)
        self.assertEqual(r.status, "valid")
        self.assertEqual(r.target, os.path.abspath(target))
        self.assertEqual(r.depth, 1)

    # ---- happy path: symlink to symlink to file ---------------------------

    def test_chain_of_two_links(self) -> None:
        target = self._make_regular("target.txt")
        link1 = self._make_symlink("link1", target)
        link2 = self._make_symlink("link2", link1)
        r = SymlinkValidator().validate(link2)
        self.assertEqual(r.status, "valid")
        self.assertEqual(r.target, os.path.abspath(target))
        self.assertEqual(r.depth, 2)

    # ---- missing start ----------------------------------------------------

    def test_start_path_missing(self) -> None:
        r = SymlinkValidator().validate(self._path("nope.txt"))
        self.assertEqual(r.status, "missing")
        self.assertEqual(r.depth, 0)

    # ---- broken symlink ---------------------------------------------------

    def test_broken_symlink(self) -> None:
        # Point at a path that does not exist anywhere on the filesystem.
        link = self._make_symlink("broken.txt", self._path("missing_target"))
        r = SymlinkValidator().validate(link)
        self.assertEqual(r.status, "broken")
        self.assertEqual(r.depth, 1)
        # The reported target is the resolved (absolute) missing path.
        self.assertEqual(r.target, os.path.abspath(self._path("missing_target")))

    def test_broken_symlink_relative_target(self) -> None:
        # A relative target exercises the os.path.join(dir, target) logic.
        link = self._make_symlink("rel.txt", "does_not_exist")
        r = SymlinkValidator().validate(link)
        self.assertEqual(r.status, "broken")
        self.assertEqual(r.depth, 1)
        self.assertEqual(r.target, os.path.abspath(self._path("does_not_exist")))

    # ---- circular ---------------------------------------------------------

    def test_self_referential_symlink(self) -> None:
        p = self._path("self")
        os.symlink(p, p)
        r = SymlinkValidator().validate(p)
        self.assertEqual(r.status, "circular")
        # The start path points at itself; we detect the cycle after
        # consuming one hop so that this is distinguishable from a non-symlink
        # input that never existed (which reports depth 0).
        self.assertEqual(r.target, os.path.abspath(p))
        self.assertEqual(r.depth, 1)

    def test_two_link_cycle(self) -> None:
        a = self._path("a")
        b = self._path("b")
        os.symlink(b, a)  # a -> b
        os.symlink(a, b)  # b -> a
        r = SymlinkValidator().validate(a)
        self.assertEqual(r.status, "circular")
        # We must have visited at least one link before detecting the cycle.
        self.assertGreaterEqual(r.depth, 1)

    # ---- too deep ---------------------------------------------------------

    def test_max_depth_exceeded(self) -> None:
        # Build a chain longer than max_depth and ensure we classify as too_deep.
        target = self._make_regular("end.txt")
        prev = target
        # max_depth=3 means we permit 3 hops; build 5 links so we blow past it.
        for i in range(5):
            link = self._path(f"step{i}")
            os.symlink(prev, link)
            prev = link
        r = SymlinkValidator(max_depth=3).validate(prev)
        self.assertEqual(r.status, "too_deep")
        self.assertEqual(r.depth, 3)

    def test_max_depth_boundary_not_exceeded(self) -> None:
        # max_depth=3 should resolve a 3-link chain successfully.
        target = self._make_regular("end.txt")
        prev = target
        for i in range(3):
            link = self._path(f"ok{i}")
            os.symlink(prev, link)
            prev = link
        r = SymlinkValidator(max_depth=3).validate(prev)
        self.assertEqual(r.status, "valid")
        self.assertEqual(r.depth, 3)
        self.assertEqual(r.target, os.path.abspath(target))

    # ---- construction validation ------------------------------------------

    def test_max_depth_must_be_positive(self) -> None:
        with self.assertRaises(ValueError):
            SymlinkValidator(max_depth=0)
        with self.assertRaises(ValueError):
            SymlinkValidator(max_depth=-1)

    # ---- result shape ------------------------------------------------------

    def test_result_has_expected_fields(self) -> None:
        f = self._make_regular("file.txt")
        r = SymlinkValidator().validate(f)
        self.assertIsInstance(r, SymlinkResult)
        for field in ("start", "target", "status", "depth"):
            self.assertTrue(hasattr(r, field), f"missing field {field}")
        self.assertIsInstance(r.start, str)
        self.assertIsInstance(r.target, str)
        self.assertIsInstance(r.status, str)
        self.assertIsInstance(r.depth, int)


if __name__ == "__main__":
    unittest.main()
