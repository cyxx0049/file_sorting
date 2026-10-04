## 此工具为cli命令式文件整理工具
脚本文件file_sort.py
具体用法包含：
- 将指定目录中的文件按照文件类型分类,实现移动：`python file_sort.py <指定目录> --by type`
- 将指定目录中的文件按照文件大小分类：按照1MB，10MB，100MB档位大小：`python file_sort.py <指定目录> --by size --size-ranges 1MB,10MB,100MB`
- 将指定目录中的文件按照时间分类：按照修改时间的月份分类：`python file_sort.py <指定目录> --by date --date-source mtime --date-granularity month`
- 只打印计划不实现移动：`python file_sort.py <指定目录> --by type --dry-run`
- 递归扫描子目录：`python file_sort.py <指定目录> --by type --recursive`
- 对于冲突文件执行略过处理：`python file_sort.py <指定目录> --by type --on-conflict skip`
- 对于已分类完成目录进行验证：`python file_sort.py <已完成分类的目录> --by type --verify`