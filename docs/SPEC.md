# file_sort.py 功能规格

## 目的与范围
这是一个终端文件整理cli，将指定目录下的文件按照type/size/date进行分类移入分类子目录
不处理文件内容，不做去重，不做压缩

## CLI命令行
```
python file_sort.py <目标目录> --by {type,size,date} [选项]
```

| 参数 | 说明 | 默认 |
|------|------|------|
| `--by` | 分类维度（type/size/date），必填 | 无 |
| `--size-ranges` | 大小档位边界，如 `1MB,10MB,100MB` | `1KB,1MB,10MB,100MB,1GB` |
| `--date-granularity` | `year` / `month` / `day` | `month` |
| `--date-source` | `mtime` / `ctime` / `atime` | `mtime` |
| `--dry-run` | 只打印计划，不移动 | 关 |
| `--recursive` | 递归扫描子目录 | 关（仅顶层） |
| `--on-conflict` | `rename` / `skip` / `overwrite` | `rename` |
| `--output` | 分类子目录根目录 | 目标目录本身 |
| `--verify` | 只校验不整理 | 关 |

## 分类规则（`classify(file) -> 子目录名`）
- **type**：按扩展名（小写）分目录（`jpg/`、`pdf/`、`py/`）；无扩展名 → `no_extension/`。
- **size**：按 `--size-ranges` 切成相邻区间，目录名用区间表达（`1MB-10MB/`、`>=100MB/`）。**区间为左闭右开。**
  需实现大小单位解析（B/KB/MB/GB/TB，大小写不敏感，1024 进制）。
- **date**：取 `--date-source` 时间戳，按粒度生成 `2026/`、`2026-10/`、`2026-10-02/`。

目录名是「文件属性 → 字符串」的确定性映射，且是人类可读的规则编码。

## 边界条件与错误处理
原则：**非法输入立即报错，给出「错误原因 + 正确用法示例」，非零退出码**，不静默吞错、不猜意图。
集中在 argparse 的 `type=` 回调（抛 `ArgumentTypeError`）与 `validate_args(args)` 中，`main()` 统一格式化。
### 边界条件
- 空文件放入第一个大小的文件夹，并给出存在空文件的提示
- 符号链接和隐藏文件不处理，给出提示信息，不放入分类文件夹
- `--recursive`命令默认关闭，不递归扫描任何子目录，开启时递归扫描所有子目录，将子目录的文件整理分类放入原子目录中，不提出原目录
### 错误处理
| 场景 | 行为 |
|------|------|
| 缺 `--by` / `--by`后无参数 | 打印 usage 与最小示例，退出码 2 |
| `--by` 非法值 | 列出合法值 `type/size/date` |
| 目录不存在 / 非目录 / 无权限 | 报错，提示检查路径 |
| `--size-ranges` 取值非法（无单位/非升序/边界≤0） | 报错，附示例 `1MB,10MB,100MB` |
| `--size-ranges` 配 `--by type/date`（参数不匹配） | 报错，提示仅 `--by size` 有效 |
| `--date-*` 配 `--by type/size`（参数不匹配） | 报错，提示仅 `--by date` 有效 |
| `--date-granularity`/`--date-source`/`--on-conflict` 取值非法 | 列出合法取值 |
| 空目录 / 无可整理文件 | 信息性提示，退出码 0 |

错误输出格式示例：

```
错误：--size-ranges 必须是升序的带单位数值，例如 "1MB,10MB,100MB"
正确用法：python file_sort.py <目录> --by size --size-ranges 1MB,10MB,100MB
```

## 函数结构（单文件）
**参考实现，允许调整**
```
parse_size(str) -> int            # "10MB" → 字节数（非法抛 ArgumentTypeError）
parse_size_ranges(str) -> [int]   # 升序边界列表（校验升序/正数）
format_size(int) -> str           # 字节数 → "10MB"（目录名用）
validate_args(args) -> None       # 跨参数组合校验
classify(path, by, opts) -> str   # 文件 → 目录名（移动侧）
folder_to_constraint(name, by, opts)  # 目录名 → 约束（校验侧，独立实现）
scan_files(dir, recursive, skip_dirs)
build_plan(files, by, opts) -> [(src, dst)]  # 含冲突处理
execute(plan, dry_run, on_conflict)
verify(dir, by, opts) -> 报告     # 调 folder_to_constraint，不调 classify
main()
```