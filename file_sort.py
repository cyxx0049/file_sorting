#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""file_sort.py —— 终端文件整理脚本。

按 type（扩展名）/ size（大小）/ date（时间）对指定目录下的文件进行分类并移动。
评判标准是「文件是否被正确分类」，由 --verify 模式独立校验。

用法示例：
    python file_sort.py <目录> --by type
    python file_sort.py <目录> --by size --size-ranges 1MB,10MB,100MB
    python file_sort.py <目录> --by date --date-source mtime --date-granularity month
    python file_sort.py <目录> --by type --dry-run
    python file_sort.py <目录> --by type --recursive
    python file_sort.py <目录> --by type --on-conflict skip
    python file_sort.py <已完成分类的目录> --by type --verify

设计详见 docs/SPEC.md 与 docs/VERIFY.md。
"""

import argparse
import os
import re
import shutil
import stat
import sys
from datetime import datetime
from pathlib import Path

# --------------------------------------------------------------------------
# 常量
# --------------------------------------------------------------------------
# 大小单位（1024 进制），按从大到小排列，供 format_size 优先取整。
UNITS = (("TB", 2 ** 40), ("GB", 2 ** 30), ("MB", 2 ** 20), ("KB", 2 ** 10), ("B", 1))
UNIT_FACTORS = {name: factor for name, factor in UNITS}

DEFAULT_SIZE_RANGES = "1KB,1MB,10MB,100MB,1GB"
USAGE_HINT = "python file_sort.py <目录> --by {type,size,date} [选项]"


# --------------------------------------------------------------------------
# 错误输出
# --------------------------------------------------------------------------
def fail(message, usage=None):
    """打印「错误原因 + 正确用法」，非零退出码。"""
    sys.stderr.write(f"错误：{message}\n")
    sys.stderr.write(f"正确用法：{usage or USAGE_HINT}\n")
    sys.exit(2)


class Parser(argparse.ArgumentParser):
    """自定义 ArgumentParser：任何解析错误都附带中文用法提示，退出码 2。"""

    def error(self, message):
        self.print_usage(sys.stderr)
        sys.stderr.write(f"错误：{message}\n")
        sys.stderr.write(f"正确用法：{USAGE_HINT}\n")
        sys.exit(2)


# --------------------------------------------------------------------------
# 大小解析与格式化
# --------------------------------------------------------------------------
def parse_size(text):
    """'10MB' → 字节数（整数）。非法输入抛 ArgumentTypeError。"""
    text = text.strip()
    m = re.fullmatch(r"(\d+)\s*([KMGT]?B)", text, re.IGNORECASE)
    if not m:
        raise argparse.ArgumentTypeError(
            f"无效的大小：'{text}'，应为带单位的数值，如 1KB / 10MB / 1GB")
    num = int(m.group(1))
    unit = m.group(2).upper()
    return num * UNIT_FACTORS[unit]


def format_size(n):
    """字节数 → 人类可读字符串（尽量取整，如 '1MB'、'1536B'）。"""
    for name, factor in UNITS:
        if n >= factor and n % factor == 0:
            return f"{n // factor}{name}"
    return f"{n}B"


def parse_size_ranges(text):
    """'1MB,10MB' → 升序边界列表 [1048576, 10485760]（严格升序且均 > 0）。"""
    parts = [p.strip() for p in text.split(",")]
    if any(not p for p in parts):
        raise argparse.ArgumentTypeError("大小档位不能包含空值，例如 '1MB,10MB'")
    bounds = []
    for p in parts:
        v = parse_size(p)
        if v <= 0:
            raise argparse.ArgumentTypeError(f"档位边界必须大于 0：'{p}'")
        bounds.append(v)
    for i in range(1, len(bounds)):
        if bounds[i] <= bounds[i - 1]:
            raise argparse.ArgumentTypeError(
                f"大小档位必须严格升序，例如 '1MB,10MB,100MB'，第 {i + 1} 项 '{parts[i]}' 不大于前一项")
    return bounds


# --------------------------------------------------------------------------
# argparse type 回调（非法取值 → 中文错误）
# --------------------------------------------------------------------------
def by_value(s):
    v = s.lower()
    if v not in ("type", "size", "date"):
        raise argparse.ArgumentTypeError(f"无效的 --by 取值：'{s}'，合法值为 type / size / date")
    return v


def granularity_value(s):
    v = s.lower()
    if v not in ("year", "month", "day"):
        raise argparse.ArgumentTypeError(
            f"无效的 --date-granularity 取值：'{s}'，合法值为 year / month / day")
    return v


def date_source_value(s):
    v = s.lower()
    if v not in ("mtime", "ctime", "atime"):
        raise argparse.ArgumentTypeError(
            f"无效的 --date-source 取值：'{s}'，合法值为 mtime / ctime / atime")
    return v


def conflict_value(s):
    v = s.lower()
    if v not in ("rename", "skip", "overwrite"):
        raise argparse.ArgumentTypeError(
            f"无效的 --on-conflict 取值：'{s}'，合法值为 rename / skip / overwrite")
    return v


# --------------------------------------------------------------------------
# 分类（移动侧）：文件 → 目标子目录名
# --------------------------------------------------------------------------
def classify_date(dt, granularity):
    if granularity == "year":
        return f"{dt.year:04d}"
    if granularity == "month":
        return f"{dt.year:04d}-{dt.month:02d}"
    if granularity == "day":
        return f"{dt.year:04d}-{dt.month:02d}-{dt.day:02d}"
    raise ValueError(f"未知日期粒度：{granularity}")


def classify_size(size, bounds):
    """字节数 → 大小档位目录名。bounds 为升序正整数列表。区间左闭右开。
    目录名需兼容 Windows 文件系统，用 lt/ge 前缀代替 < / >=。"""
    for i, b in enumerate(bounds):
        if size < b:
            if i == 0:
                return f"lt{format_size(b)}"
            return f"{format_size(bounds[i - 1])}-{format_size(b)}"
    return f"ge{format_size(bounds[-1])}"


def classify(path, by, opts):
    """文件 → 分类子目录名（移动侧核心函数）。"""
    if by == "type":
        suffix = path.suffix
        if suffix == "":
            return "no_extension"
        return suffix.lstrip(".").lower()
    if by == "size":
        return classify_size(path.stat().st_size, opts.size_ranges)
    if by == "date":
        ts = getattr(path.stat(), "st_" + opts.date_source)
        return classify_date(datetime.fromtimestamp(ts), opts.date_granularity)
    raise ValueError(f"未知分类维度：{by}")


# --------------------------------------------------------------------------
# 校验（校验侧）：目录名 → 属性约束。与 classify 完全独立，不共享分类计算逻辑。
# --------------------------------------------------------------------------
def constraint_type(name):
    if name == "no_extension":
        def check(path):
            if path.suffix == "":
                return (True, "", "")
            return (False, f"扩展名 '{path.suffix}'", "应无扩展名")
        return check
    if re.fullmatch(r"[A-Za-z0-9_+-]+", name):
        ext = "." + name.lower()
        def check(path):
            if path.suffix.lower() == ext:
                return (True, "", "")
            return (False, f"扩展名 '{path.suffix}'", f"应为 '{ext}'")
        return check
    return None


def constraint_size(name):
    try:
        if name.startswith("lt"):
            lower, upper = 0, parse_size(name[2:])
        elif name.startswith("ge"):
            lower, upper = parse_size(name[2:]), None
        elif "-" in name:
            lo, hi = name.split("-", 1)
            lower, upper = parse_size(lo), parse_size(hi)
        else:
            return None
    except (argparse.ArgumentTypeError, ValueError):
        return None

    def check(path):
        sz = path.stat().st_size
        if lower is not None and sz < lower:
            return (False, f"大小 {sz} B", f"应 >= {lower} B")
        if upper is not None and sz >= upper:
            return (False, f"大小 {sz} B", f"应 < {upper} B")
        return (True, "", "")
    return check


def constraint_date(name, source):
    m = re.fullmatch(r"(\d{4})(?:-(\d{1,2})(?:-(\d{1,2}))?)?", name)
    if not m:
        return None
    year = int(m.group(1))
    month = int(m.group(2)) if m.group(2) else None
    day = int(m.group(3)) if m.group(3) else None

    def check(path):
        ts = getattr(path.stat(), "st_" + source)
        dt = datetime.fromtimestamp(ts)
        if dt.year != year:
            return (False, f"年份 {dt.year}", f"应为 {year}")
        if month is not None and dt.month != month:
            return (False, f"月份 {dt.month}", f"应为 {month}")
        if day is not None and dt.day != day:
            return (False, f"日 {dt.day}", f"应为 {day}")
        return (True, "", "")
    return check


def folder_to_constraint(name, by, opts):
    """目录名 → 属性约束。返回 None 表示目录名无法解析（应被警告并忽略）。"""
    if by == "type":
        return constraint_type(name)
    if by == "size":
        return constraint_size(name)
    if by == "date":
        return constraint_date(name, opts.date_source)
    return None


# --------------------------------------------------------------------------
# 扫描
# --------------------------------------------------------------------------
def is_hidden(fp):
    """是否为隐藏文件/目录：Unix 以 '.' 开头，Windows 设置 HIDDEN 属性。"""
    if fp.name.startswith("."):
        return True
    hidden_attr = getattr(stat, "FILE_ATTRIBUTE_HIDDEN", 0)
    if not hidden_attr:
        return False
    try:
        return bool(fp.stat().st_file_attributes & hidden_attr)
    except (AttributeError, OSError):
        return False


def scan_files(target_dir, recursive, by, opts):
    """收集待分类文件。跳过隐藏文件与符号链接；返回 (files, skipped)。"""
    target = Path(target_dir)
    files = []
    skipped = []  # (path, reason)

    def add_file(fp):
        if fp.is_symlink():
            skipped.append((fp, "符号链接"))
            return
        if is_hidden(fp):
            skipped.append((fp, "隐藏文件"))
            return
        files.append(fp)

    if not recursive:
        try:
            entries = sorted(target.iterdir(), key=lambda p: p.name)
        except OSError as e:
            fail(f"无法读取目录 {target}：{e}")
        for entry in entries:
            if entry.is_symlink():
                skipped.append((entry, "符号链接"))
                continue
            if entry.is_dir():
                continue
            add_file(entry)
    else:
        for dirpath, dirnames, filenames in os.walk(target):
            dirpath = Path(dirpath)
            kept = []
            for d in dirnames:
                dp = dirpath / d
                if dp.is_symlink() or is_hidden(dp):
                    skipped.append((dp, "隐藏目录/符号链接目录"))
                    continue
                kept.append(d)
            dirnames[:] = kept
            for fn in filenames:
                add_file(dirpath / fn)
    return files, skipped


# --------------------------------------------------------------------------
# 计划与执行
# --------------------------------------------------------------------------
def dest_root(file, opts):
    """文件所属的「分类子目录根」：--output 指定则用该目录，否则用文件所在目录。"""
    if opts.output:
        return Path(opts.output).resolve()
    return file.parent


def resolve_destination(dst, mode, assigned):
    """按冲突策略解析最终目标路径。返回 Path 或 None（skip）。"""
    if dst not in assigned and not dst.exists():
        assigned.add(dst)
        return dst
    if mode == "overwrite":
        assigned.add(dst)
        return dst
    if mode == "skip":
        return None
    # rename：追加 _1/_2 直到不冲突
    stem, suffix = dst.stem, dst.suffix
    i = 1
    while True:
        cand = dst.with_name(f"{stem}_{i}{suffix}")
        if cand not in assigned and not cand.exists():
            assigned.add(cand)
            return cand
        i += 1


def build_plan(files, by, opts):
    """计算移动计划。返回 (plan, already, empty_files)。
    already：已在正确分类目录中的文件（自移动防护，跳过）；
    empty_files：空文件（给出提示，但仍正常分类）。"""
    plan = []
    already = []
    empty_files = []
    assigned = set()

    for src in files:
        folder = classify(src, by, opts)
        if src.parent.name == folder:
            already.append(src)  # 已在正确分类目录，避免重复嵌套移动
            continue
        try:
            if src.stat().st_size == 0:
                empty_files.append(src)
        except OSError:
            pass
        dst = dest_root(src, opts) / folder / src.name
        plan.append((src, resolve_destination(dst, opts.on_conflict, assigned)))
    return plan, already, empty_files


def execute(plan, dry_run, on_conflict):
    """执行移动。dry_run 只打印。返回 (stats, failures)。"""
    moved = skipped = failed = 0
    failures = []
    for src, dst in plan:
        if dst is None:
            skipped += 1
            continue
        if dry_run:
            print(f"[计划] {src} -> {dst}")
            moved += 1
            continue
        try:
            dst.parent.mkdir(parents=True, exist_ok=True)
            if dst.exists() or dst.is_symlink():
                if dst.is_dir() and not dst.is_symlink():
                    shutil.rmtree(dst)
                else:
                    dst.unlink()
            shutil.move(str(src), str(dst))
            moved += 1
        except OSError as e:
            failed += 1
            failures.append((src, dst, e))
    stats = {"moved": moved, "skipped": skipped, "failed": failed}
    return stats, failures


# --------------------------------------------------------------------------
# 校验（评判标准）
# --------------------------------------------------------------------------
def verify(target_dir, by, opts):
    """独立校验：检查每个文件是否落在正确分类目录。返回报告 dict。"""
    roots = [Path(target_dir).resolve()]
    if opts.output:
        out = Path(opts.output).resolve()
        if out != roots[0]:
            roots.append(out)

    total = correct = wrong = unclassified = 0
    errors = []
    unclassified_files = []
    warnings = []

    for root in roots:
        if not root.is_dir():
            continue
        for dirpath, dirnames, filenames in os.walk(root):
            dirpath = Path(dirpath)
            # 与扫描侧一致：跳过隐藏目录与符号链接目录
            dirnames[:] = [d for d in dirnames
                           if not (dirpath / d).is_symlink() and not is_hidden(dirpath / d)]
            constraint = None if dirpath == root else folder_to_constraint(dirpath.name, by, opts)

            if constraint is not None:
                # 分类目录：检查其中每个文件的原始属性是否满足约束
                for fn in filenames:
                    fp = dirpath / fn
                    if fp.is_symlink() or is_hidden(fp):
                        continue
                    total += 1
                    ok, actual, expected = constraint(fp)
                    if ok:
                        correct += 1
                    else:
                        wrong += 1
                        errors.append((fp, actual, expected))
                dirnames.clear()  # 分类目录是叶子，不再下钻
                continue

            if dirpath != root:
                # 无法解析的目录名：警告并忽略该校验
                warnings.append(f"无法解析目录名，跳过校验：{dirpath}")
                dirnames.clear()
                continue

            # 根目录本身：直接散落的文件视为「未分类/遗漏」
            for fn in filenames:
                fp = dirpath / fn
                if fp.is_symlink() or is_hidden(fp):
                    continue
                total += 1
                unclassified += 1
                unclassified_files.append(fp)

    rate = (correct / total) if total else 0.0
    return {
        "total": total, "correct": correct, "wrong": wrong,
        "unclassified": unclassified, "rate": rate,
        "errors": errors, "unclassified_files": unclassified_files,
        "warnings": warnings,
    }


def print_verify_report(rep):
    print(f"校验结果：总数 {rep['total']}，正确 {rep['correct']}，错误 {rep['wrong']}，未分类 {rep['unclassified']}")
    print(f"正确率：{rep['rate'] * 100:.2f}%")
    for w in rep["warnings"]:
        print(f"警告：{w}")
    for fp, actual, expected in rep["errors"]:
        print(f"[错误] {fp} —— 实际：{actual}，约束：{expected}")
    for fp in rep["unclassified_files"]:
        print(f"[未分类] {fp}")


# --------------------------------------------------------------------------
# 参数解析与校验
# --------------------------------------------------------------------------
def build_parser():
    p = Parser(prog="file_sort.py", description="按类型/大小/日期整理文件")
    p.add_argument("directory", help="要整理的目标目录")
    p.add_argument("--by", type=by_value, default=None, help="分类维度：type / size / date（必填）")
    p.add_argument("--size-ranges", type=parse_size_ranges, default=None,
                   help="大小档位边界，如 1MB,10MB,100MB")
    p.add_argument("--date-granularity", type=granularity_value, default=None,
                   help="日期粒度：year / month / day（默认 month）")
    p.add_argument("--date-source", type=date_source_value, default=None,
                   help="日期来源：mtime / ctime / atime（默认 mtime）")
    p.add_argument("--dry-run", action="store_true", help="只打印计划，不实际移动")
    p.add_argument("--recursive", action="store_true", help="递归扫描子目录")
    p.add_argument("--on-conflict", type=conflict_value, default="rename",
                   help="冲突处理：rename / skip / overwrite（默认 rename）")
    p.add_argument("--output", type=str, default=None, help="分类子目录根目录（默认目标目录）")
    p.add_argument("--verify", action="store_true", help="只校验不整理")
    return p


def validate_args(args):
    if args.by is None:
        fail("缺少必填参数 --by，请指定分类维度 type / size / date")

    if args.by == "size":
        if args.size_ranges is None:
            args.size_ranges = parse_size_ranges(DEFAULT_SIZE_RANGES)
    elif args.size_ranges is not None:
        fail("--size-ranges 仅在 --by size 时有效")

    if args.by == "date":
        args.date_granularity = args.date_granularity or "month"
        args.date_source = args.date_source or "mtime"
    else:
        if args.date_granularity is not None:
            fail("--date-granularity 仅在 --by date 时有效")
        if args.date_source is not None:
            fail("--date-source 仅在 --by date 时有效")


# --------------------------------------------------------------------------
# 主流程
# --------------------------------------------------------------------------
def main(argv=None):
    args = build_parser().parse_args(argv)
    validate_args(args)

    target = Path(args.directory)
    if not target.exists():
        fail(f"目录不存在：{args.directory}，请检查路径")
    if not target.is_dir():
        fail(f"不是目录：{args.directory}")
    if not os.access(target, os.R_OK):
        fail(f"目录无读权限：{args.directory}")

    if args.verify:
        print_verify_report(verify(target, args.by, args))
        return 0

    files, skipped = scan_files(target, args.recursive, args.by, args)
    for p, reason in skipped:
        print(f"提示：跳过{reason}：{p}")

    if not files:
        print("无可整理文件（目录为空，或仅含子目录/隐藏文件/符号链接）。")
        return 0

    plan, already, empty_files = build_plan(files, args.by, args)
    for p in already:
        print(f"提示：跳过已在正确分类目录中的文件：{p}")
    for p in empty_files:
        print(f"提示：存在空文件：{p}")

    stats, failures = execute(plan, args.dry_run, args.on_conflict)

    if args.dry_run:
        print(f"共计划移动 {stats['moved']} 个文件（dry-run，未实际移动），跳过 {stats['skipped']} 个。")
    else:
        print(f"整理完成：移动 {stats['moved']} 个，跳过 {stats['skipped']} 个，失败 {stats['failed']} 个。")
    for src, dst, err in failures:
        print(f"[失败] {src} -> {dst}：{err}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
