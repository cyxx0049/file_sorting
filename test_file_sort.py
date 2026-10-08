# -*- coding: utf-8 -*-
"""file_sort.py 的测试。

覆盖：
- 单元测试：parse_size / format_size / parse_size_ranges / classify / folder_to_constraint
- 集成测试（subprocess）：README.md 中的全部命令，以及 SPEC.md 中的错误处理。

运行：python -m unittest test_file_sort -v
"""

import os
import subprocess
import sys
import tempfile
import unittest
from datetime import datetime
from pathlib import Path

import file_sort

SCRIPT = Path(__file__).resolve().parent / "file_sort.py"


def run_cli(args):
    """以子进程方式运行 file_sort.py，返回 CompletedProcess。"""
    env = dict(os.environ, PYTHONUTF8="1", PYTHONIOENCODING="utf-8")
    return subprocess.run(
        [sys.executable, str(SCRIPT)] + args,
        capture_output=True, text=True, encoding="utf-8", errors="replace", env=env,
    )


def make_opts(by="type", size_ranges=None, date_source=None, date_granularity=None,
              on_conflict="rename", output=None, dry_run=False, recursive=False):
    import argparse
    return argparse.Namespace(
        by=by, size_ranges=size_ranges, date_source=date_source,
        date_granularity=date_granularity, on_conflict=on_conflict,
        output=output, dry_run=dry_run, recursive=recursive,
    )


def set_mtime(path, dt):
    ts = dt.timestamp()
    os.utime(path, (ts, ts))


class TempDirTestCase(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.tmp = Path(self._tmp.name)

    def tearDown(self):
        self._tmp.cleanup()


# --------------------------------------------------------------------------
# parse_size / format_size / parse_size_ranges
# --------------------------------------------------------------------------
class TestParseSize(unittest.TestCase):
    def test_mb(self):
        self.assertEqual(file_sort.parse_size("1MB"), 1024 ** 2)

    def test_kb(self):
        self.assertEqual(file_sort.parse_size("10KB"), 10 * 1024)

    def test_gb(self):
        self.assertEqual(file_sort.parse_size("1GB"), 1024 ** 3)

    def test_case_insensitive(self):
        self.assertEqual(file_sort.parse_size("1mb"), 1024 ** 2)

    def test_plain_b(self):
        self.assertEqual(file_sort.parse_size("500B"), 500)

    def test_no_unit_invalid(self):
        with self.assertRaises(Exception):
            file_sort.parse_size("10")

    def test_garbage_invalid(self):
        with self.assertRaises(Exception):
            file_sort.parse_size("abc")


class TestFormatSize(unittest.TestCase):
    def test_zero(self):
        self.assertEqual(file_sort.format_size(0), "0B")

    def test_kb(self):
        self.assertEqual(file_sort.format_size(1024), "1KB")

    def test_mb(self):
        self.assertEqual(file_sort.format_size(1024 ** 2), "1MB")

    def test_gb(self):
        self.assertEqual(file_sort.format_size(1024 ** 3), "1GB")

    def test_non_round(self):
        self.assertEqual(file_sort.format_size(1536), "1536B")

    def test_roundtrip(self):
        for n in (0, 1, 1024, 1024 ** 2, 10 * 1024 ** 2, 1024 ** 3):
            self.assertEqual(file_sort.parse_size(file_sort.format_size(n)), n)


class TestParseSizeRanges(unittest.TestCase):
    def test_valid(self):
        self.assertEqual(file_sort.parse_size_ranges("1MB,10MB"),
                         [1024 ** 2, 10 * 1024 ** 2])

    def test_non_ascending(self):
        with self.assertRaises(Exception):
            file_sort.parse_size_ranges("10MB,1MB")

    def test_zero(self):
        with self.assertRaises(Exception):
            file_sort.parse_size_ranges("0MB,10MB")

    def test_empty_part(self):
        with self.assertRaises(Exception):
            file_sort.parse_size_ranges("1MB,,10MB")

    def test_garbage(self):
        with self.assertRaises(Exception):
            file_sort.parse_size_ranges("abc")


# --------------------------------------------------------------------------
# classify（移动侧）
# --------------------------------------------------------------------------
class TestClassifyType(unittest.TestCase):
    def test_lower_ext(self):
        opts = make_opts()
        self.assertEqual(file_sort.classify(Path("a.jpg"), "type", opts), "jpg")

    def test_upper_ext_lowercased(self):
        opts = make_opts()
        self.assertEqual(file_sort.classify(Path("A.PDF"), "type", opts), "pdf")

    def test_no_extension(self):
        opts = make_opts()
        self.assertEqual(file_sort.classify(Path("noext"), "type", opts), "no_extension")

    def test_multi_dot(self):
        opts = make_opts()
        self.assertEqual(file_sort.classify(Path("archive.tar.gz"), "type", opts), "gz")


class TestClassifySize(TempDirTestCase):
    def test_buckets(self):
        opts = make_opts(by="size", size_ranges=file_sort.parse_size_ranges("1MB,10MB"))
        small = self.tmp / "small.bin"; small.write_bytes(b"x" * 1024)              # 1KB -> lt1MB
        mid = self.tmp / "mid.bin"; mid.write_bytes(b"x" * (5 * 1024 ** 2))          # 5MB -> 1MB-10MB
        big = self.tmp / "big.bin"; big.write_bytes(b"x" * (20 * 1024 ** 2))         # 20MB -> ge10MB
        self.assertEqual(file_sort.classify(small, "size", opts), "lt1MB")
        self.assertEqual(file_sort.classify(mid, "size", opts), "1MB-10MB")
        self.assertEqual(file_sort.classify(big, "size", opts), "ge10MB")

    def test_boundary_left_closed_right_open(self):
        opts = make_opts(by="size", size_ranges=file_sort.parse_size_ranges("1MB,10MB"))
        at1mb = self.tmp / "a.bin"; at1mb.write_bytes(b"x" * (1024 ** 2))
        at10mb = self.tmp / "b.bin"; at10mb.write_bytes(b"x" * (10 * 1024 ** 2))
        self.assertEqual(file_sort.classify(at1mb, "size", opts), "1MB-10MB")
        self.assertEqual(file_sort.classify(at10mb, "size", opts), "ge10MB")


class TestClassifyDate(TempDirTestCase):
    def test_year(self):
        f = self.tmp / "a.txt"; f.write_text("x")
        set_mtime(f, datetime(2026, 3, 5, 10, 0, 0))
        opts = make_opts(by="date", date_source="mtime", date_granularity="year")
        self.assertEqual(file_sort.classify(f, "date", opts), "2026")

    def test_month(self):
        f = self.tmp / "a.txt"; f.write_text("x")
        set_mtime(f, datetime(2026, 3, 5, 10, 0, 0))
        opts = make_opts(by="date", date_source="mtime", date_granularity="month")
        self.assertEqual(file_sort.classify(f, "date", opts), "2026-03")

    def test_day(self):
        f = self.tmp / "a.txt"; f.write_text("x")
        set_mtime(f, datetime(2026, 3, 5, 10, 0, 0))
        opts = make_opts(by="date", date_source="mtime", date_granularity="day")
        self.assertEqual(file_sort.classify(f, "date", opts), "2026-03-05")


# --------------------------------------------------------------------------
# folder_to_constraint（校验侧，独立实现）
# --------------------------------------------------------------------------
class TestConstraintType(unittest.TestCase):
    def test_match(self):
        c = file_sort.folder_to_constraint("jpg", "type", make_opts())
        self.assertTrue(c(Path("a.jpg"))[0])
        self.assertTrue(c(Path("b.JPG"))[0])

    def test_mismatch(self):
        c = file_sort.folder_to_constraint("jpg", "type", make_opts())
        self.assertFalse(c(Path("a.png"))[0])

    def test_no_extension(self):
        c = file_sort.folder_to_constraint("no_extension", "type", make_opts())
        self.assertTrue(c(Path("noext"))[0])
        self.assertFalse(c(Path("a.jpg"))[0])

    def test_unparseable(self):
        self.assertIsNone(file_sort.folder_to_constraint("has space", "type", make_opts()))


class TestConstraintSize(TempDirTestCase):
    def test_in_range(self):
        c = file_sort.folder_to_constraint("1MB-10MB", "size", make_opts())
        f = self.tmp / "a.bin"; f.write_bytes(b"x" * (5 * 1024 ** 2))
        self.assertTrue(c(f)[0])

    def test_below(self):
        c = file_sort.folder_to_constraint("1MB-10MB", "size", make_opts())
        f = self.tmp / "a.bin"; f.write_bytes(b"x" * 1024)
        self.assertFalse(c(f)[0])

    def test_above(self):
        c = file_sort.folder_to_constraint("1MB-10MB", "size", make_opts())
        f = self.tmp / "a.bin"; f.write_bytes(b"x" * (20 * 1024 ** 2))
        self.assertFalse(c(f)[0])

    def test_left_closed_right_open(self):
        c = file_sort.folder_to_constraint("1MB-10MB", "size", make_opts())
        at1mb = self.tmp / "a.bin"; at1mb.write_bytes(b"x" * (1024 ** 2))
        at10mb = self.tmp / "b.bin"; at10mb.write_bytes(b"x" * (10 * 1024 ** 2))
        self.assertTrue(c(at1mb)[0])
        self.assertFalse(c(at10mb)[0])

    def test_lt_bucket(self):
        c = file_sort.folder_to_constraint("lt1MB", "size", make_opts())
        below = self.tmp / "a.bin"; below.write_bytes(b"x" * 1024)          # 1KB < 1MB
        at1mb = self.tmp / "b.bin"; at1mb.write_bytes(b"x" * (1024 ** 2))   # 恰好 1MB，右开
        self.assertTrue(c(below)[0])
        self.assertFalse(c(at1mb)[0])

    def test_ge_bucket(self):
        c = file_sort.folder_to_constraint("ge10MB", "size", make_opts())
        f = self.tmp / "a.bin"; f.write_bytes(b"x" * (20 * 1024 ** 2))
        self.assertTrue(c(f)[0])

    def test_unparseable(self):
        self.assertIsNone(file_sort.folder_to_constraint("not-a-size", "size", make_opts()))


class TestConstraintDate(TempDirTestCase):
    def test_year_match(self):
        f = self.tmp / "a.txt"; f.write_text("x")
        set_mtime(f, datetime(2026, 3, 5, 10, 0, 0))
        c = file_sort.folder_to_constraint("2026", "date", make_opts(by="date", date_source="mtime"))
        self.assertTrue(c(f)[0])

    def test_month_match(self):
        f = self.tmp / "a.txt"; f.write_text("x")
        set_mtime(f, datetime(2026, 3, 5, 10, 0, 0))
        c = file_sort.folder_to_constraint("2026-03", "date", make_opts(by="date", date_source="mtime"))
        self.assertTrue(c(f)[0])

    def test_month_mismatch(self):
        f = self.tmp / "a.txt"; f.write_text("x")
        set_mtime(f, datetime(2026, 3, 5, 10, 0, 0))
        c = file_sort.folder_to_constraint("2026-04", "date", make_opts(by="date", date_source="mtime"))
        self.assertFalse(c(f)[0])

    def test_unparseable(self):
        self.assertIsNone(file_sort.folder_to_constraint("jpg", "date", make_opts(by="date", date_source="mtime")))


# --------------------------------------------------------------------------
# 集成测试：README.md 中的命令
# --------------------------------------------------------------------------
class TestIntegration(TempDirTestCase):
    def test_move_by_type(self):
        (self.tmp / "a.jpg").write_text("x")
        (self.tmp / "b.JPG").write_text("x")
        (self.tmp / "c.pdf").write_text("x")
        (self.tmp / "noext").write_text("x")
        r = run_cli([str(self.tmp), "--by", "type"])
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertTrue((self.tmp / "jpg" / "a.jpg").exists())
        self.assertTrue((self.tmp / "jpg" / "b.JPG").exists())
        self.assertTrue((self.tmp / "pdf" / "c.pdf").exists())
        self.assertTrue((self.tmp / "no_extension" / "noext").exists())

    def test_dry_run(self):
        f = self.tmp / "a.jpg"; f.write_text("x")
        r = run_cli([str(self.tmp), "--by", "type", "--dry-run"])
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertTrue(f.exists())                 # 未移动
        self.assertFalse((self.tmp / "jpg").exists())
        self.assertIn("计划", r.stdout)

    def test_move_by_size(self):
        (self.tmp / "small.bin").write_bytes(b"x" * 1024)                 # 1KB
        (self.tmp / "mid.bin").write_bytes(b"x" * (5 * 1024 ** 2))        # 5MB
        (self.tmp / "big.bin").write_bytes(b"x" * (20 * 1024 ** 2))       # 20MB
        r = run_cli([str(self.tmp), "--by", "size", "--size-ranges", "1MB,10MB"])
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertTrue((self.tmp / "lt1MB" / "small.bin").exists())
        self.assertTrue((self.tmp / "1MB-10MB" / "mid.bin").exists())
        self.assertTrue((self.tmp / "ge10MB" / "big.bin").exists())

    def test_move_by_date_month(self):
        a = self.tmp / "a.txt"; a.write_text("x")
        b = self.tmp / "b.txt"; b.write_text("x")
        set_mtime(a, datetime(2026, 1, 15, 12, 0, 0))
        set_mtime(b, datetime(2026, 2, 15, 12, 0, 0))
        r = run_cli([str(self.tmp), "--by", "date", "--date-source", "mtime", "--date-granularity", "month"])
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertTrue((self.tmp / "2026-01" / "a.txt").exists())
        self.assertTrue((self.tmp / "2026-02" / "b.txt").exists())

    def test_recursive_local_classification(self):
        sub = self.tmp / "sub"; sub.mkdir()
        f = sub / "a.jpg"; f.write_text("x")
        r = run_cli([str(self.tmp), "--by", "type", "--recursive"])
        self.assertEqual(r.returncode, 0, r.stderr)
        # 不提出原目录：文件留在其所属子目录内的分类目录中
        self.assertTrue((sub / "jpg" / "a.jpg").exists())

    def test_recursive_self_move_protection(self):
        sub = self.tmp / "sub"; sub.mkdir()
        (sub / "a.jpg").write_text("x")
        run_cli([str(self.tmp), "--by", "type", "--recursive"])
        # 再次运行：已正确分类的文件不应被再次嵌套移动
        r2 = run_cli([str(self.tmp), "--by", "type", "--recursive"])
        self.assertEqual(r2.returncode, 0, r2.stderr)
        self.assertTrue((sub / "jpg" / "a.jpg").exists())
        self.assertFalse((sub / "jpg" / "jpg").exists())

    def test_on_conflict_skip(self):
        d1 = self.tmp / "d1"; d1.mkdir()
        d2 = self.tmp / "d2"; d2.mkdir()
        (d1 / "a.jpg").write_text("1")
        (d2 / "a.jpg").write_text("2")
        out = self.tmp / "out"
        r = run_cli([str(self.tmp), "--by", "type", "--recursive",
                     "--output", str(out), "--on-conflict", "skip"])
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertTrue((out / "jpg" / "a.jpg").exists())
        self.assertIn("跳过 1", r.stdout)

    def test_on_conflict_rename(self):
        d1 = self.tmp / "d1"; d1.mkdir()
        d2 = self.tmp / "d2"; d2.mkdir()
        (d1 / "a.jpg").write_text("1")
        (d2 / "a.jpg").write_text("2")
        out = self.tmp / "out"
        r = run_cli([str(self.tmp), "--by", "type", "--recursive",
                     "--output", str(out), "--on-conflict", "rename"])
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertTrue((out / "jpg" / "a.jpg").exists())
        self.assertTrue((out / "jpg" / "a_1.jpg").exists())

    def test_verify_correct(self):
        (self.tmp / "a.jpg").write_text("x")
        (self.tmp / "b.pdf").write_text("x")
        run_cli([str(self.tmp), "--by", "type"])
        r = run_cli([str(self.tmp), "--by", "type", "--verify"])
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertIn("正确 2", r.stdout)
        self.assertIn("错误 0", r.stdout)
        self.assertIn("正确率：100.00%", r.stdout)

    def test_verify_detects_misplacement(self):
        (self.tmp / "a.jpg").write_text("x")
        (self.tmp / "b.pdf").write_text("x")
        run_cli([str(self.tmp), "--by", "type"])
        # 人为挪错：jpg 目录下的 a.jpg 移入 pdf 目录
        (self.tmp / "pdf" / "a.jpg").write_text((self.tmp / "jpg" / "a.jpg").read_text())
        (self.tmp / "jpg" / "a.jpg").unlink()
        r = run_cli([str(self.tmp), "--by", "type", "--verify"])
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertIn("错误 1", r.stdout)

    def test_verify_detects_unclassified(self):
        (self.tmp / "a.jpg").write_text("x")
        run_cli([str(self.tmp), "--by", "type"])
        # 人为把已分类文件放回根目录
        (self.tmp / "a.jpg").write_text((self.tmp / "jpg" / "a.jpg").read_text())
        (self.tmp / "jpg" / "a.jpg").unlink()
        r = run_cli([str(self.tmp), "--by", "type", "--verify"])
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertIn("未分类 1", r.stdout)

    def test_skip_hidden(self):
        (self.tmp / "a.jpg").write_text("x")
        (self.tmp / ".hidden.jpg").write_text("x")
        r = run_cli([str(self.tmp), "--by", "type"])
        self.assertEqual(r.returncode, 0, r.stderr)
        # 隐藏文件未被移动（仍在根目录）
        self.assertTrue((self.tmp / ".hidden.jpg").exists())
        self.assertIn("提示：跳过隐藏文件", r.stdout)

    def test_skip_symlink(self):
        (self.tmp / "a.jpg").write_text("x")
        try:
            (self.tmp / "link.jpg").symlink_to(self.tmp / "a.jpg")
        except (OSError, NotImplementedError):
            self.skipTest("当前环境不支持创建符号链接")
        r = run_cli([str(self.tmp), "--by", "type"])
        self.assertEqual(r.returncode, 0, r.stderr)
        # 符号链接未被移动（仍是符号链接）
        self.assertTrue((self.tmp / "link.jpg").is_symlink())
        self.assertIn("提示：跳过符号链接", r.stdout)

    def test_skip_windows_hidden(self):
        if os.name != "nt":
            self.skipTest("仅 Windows 检查 HIDDEN 属性")
        f = self.tmp / "hidden_nodot.jpg"; f.write_text("x")
        try:
            subprocess.run(["attrib", "+h", str(f)], check=True, capture_output=True)
        except (OSError, subprocess.CalledProcessError):
            self.skipTest("无法设置 HIDDEN 属性")
        r = run_cli([str(self.tmp), "--by", "type"])
        self.assertEqual(r.returncode, 0, r.stderr)
        # 无点号、但带 HIDDEN 属性的文件同样不应被移动
        self.assertTrue(f.exists())
        self.assertIn("提示：跳过隐藏文件", r.stdout)


# --------------------------------------------------------------------------
# 集成测试：错误处理（SPEC.md 错误表）
# --------------------------------------------------------------------------
class TestErrorHandling(TempDirTestCase):
    def test_missing_by(self):
        r = run_cli([str(self.tmp)])
        self.assertEqual(r.returncode, 2)
        self.assertIn("错误", r.stderr)
        self.assertIn("正确用法", r.stderr)

    def test_invalid_by(self):
        r = run_cli([str(self.tmp), "--by", "foo"])
        self.assertEqual(r.returncode, 2)
        self.assertIn("type / size / date", r.stderr)

    def test_invalid_size_ranges_non_ascending(self):
        r = run_cli([str(self.tmp), "--by", "size", "--size-ranges", "10MB,1MB"])
        self.assertEqual(r.returncode, 2)
        self.assertIn("升序", r.stderr)

    def test_size_ranges_with_type(self):
        r = run_cli([str(self.tmp), "--by", "type", "--size-ranges", "1MB,10MB"])
        self.assertEqual(r.returncode, 2)
        self.assertIn("仅在 --by size 时有效", r.stderr)

    def test_date_option_with_type(self):
        r = run_cli([str(self.tmp), "--by", "type", "--date-granularity", "month"])
        self.assertEqual(r.returncode, 2)
        self.assertIn("仅在 --by date 时有效", r.stderr)

    def test_invalid_date_source(self):
        r = run_cli([str(self.tmp), "--by", "date", "--date-source", "bogus"])
        self.assertEqual(r.returncode, 2)
        self.assertIn("mtime / ctime / atime", r.stderr)

    def test_invalid_on_conflict(self):
        r = run_cli([str(self.tmp), "--by", "type", "--on-conflict", "bogus"])
        self.assertEqual(r.returncode, 2)
        self.assertIn("rename / skip / overwrite", r.stderr)

    def test_nonexistent_dir(self):
        r = run_cli([str(self.tmp / "nope"), "--by", "type"])
        self.assertEqual(r.returncode, 2)
        self.assertIn("目录不存在", r.stderr)

    def test_empty_dir(self):
        r = run_cli([str(self.tmp), "--by", "type"])
        self.assertEqual(r.returncode, 0)
        self.assertIn("无可整理文件", r.stdout)


if __name__ == "__main__":
    unittest.main()
