# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## 项目描述
 `file_sorting` 为CLI终端整理文件项目，完成一个终端文件整理脚本文件 `file_sort.py`，实现按照type/size/date方式正确分类文件

## 语言
- Python 3.8+，仅用标准库，零第三方依赖。

## 使用命令
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

## 约定
- 默认移动（move），提供 `--dry-run` 预览模式，先看计划再执行。
- 每次运行只按一种维度分类（`--by type|size|date`）。
- 评判：独立校验函数。
- 单分支 `master`，提交信息用中文。

## 核心设计约束
- 移动侧使用函数：classify(file) -> 目录名。
- 校验侧使用函数：verify(目录名) -> 属性约束；不得复用 classify。
- **dry-run 一致性**：`build_plan()` 与 `execute()` 分离，预览与执行走同一份 plan。
- **自移动防护**：分类子目录建在扫描目录内，须排除这些目录，避免重复扫描已移动的文件。
- **冲突处理**：默认`rename`追加 `_1`/`_2`；可选择`skip` 跳过/`overwrite` 覆盖。
- **异常安全**：单文件失败只记录不中断，最后汇总失败清单。

## 相关文件参考
- 在完成python文件编写前需参考具体设计`docs/SPEC.md`，包括CLI、分类规则、错误表、函数结构
- 在完成校验函数`folder_to_constraint(name, by, opts)`时，参考具体校验设计`docs/VERIFY.md`
- 在完成测试代码编写时参考用法示例：README.md，测试需要包括但不限于此文件中的命令