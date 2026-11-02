# Harbourview Dashboard V2

Part B 的 AI Analyst 已接入 Overview：支持已有图表引导、指定数值、自定义比较图及专题报告。默认使用真实 Gemini LLM，需配置 `GEMINI_API_KEY`；缺少密钥时明确提示，不会自动回退规则模式。配置与示例见 `PART_B_README.md`。本轮按要求未运行测试，`PART_B_VERIFICATION.md` 保留旧版验证记录并标记其适用范围。

本地、单人使用的 Streamlit dashboard。居民业务指标只由本目录 `metrics.py` 维护。
外部 `planB/Dashboard/pipline/metrics.py` 是提供新版计算文件的来源；运行时不再动态导入外部副本，也不在页面实现另一套居民计算。后续计算变更应集中维护本目录这一份。

## 文件职责

| 文件 | 职责 |
|---|---|
| `metrics.py` | 唯一居民级计算实现；`calculate_file()` 保留来源哈希和计算版本，`export_result()` 导出汇总 |
| `duckdb_store.py` | 汇总 CSV/JSON 导入全新数据库；只读校验六张表、关键约束及导入一致性；拒绝覆盖 |
| `db.py` | 保持 `read_only=True` 的汇总读取和文件身份缓存；不读取居民 CSV，不写数据库 |
| `summary_validation.py` | 两处随访共用校验、报告期入住率及月份完整性校验；不计算居民级指标 |
| `report_versions.py` | 配置、输入校验、预览、候选 CSV、计算导入、发布锁、提交幂等和原子清单 |
| `app.py` | 读取启用版本、保留历史数据库浏览、导航与缓存刷新 |
| `pages/add_resident.py` | 表单、预览、确认、状态反馈；没有文件保存或版本发布逻辑 |
| `pages/overview.py`, `outcomes.py`, `occupancy.py`, `quality.py` | 保留原有页面布局，接入共同校验和准确的标签、异常提示 |
| `tests/test_refactor.py` | 临时合成数据的计算、数据库、发布失败及 Streamlit AppTest 验证 |

## 安装与启动

在 `C:\Users\yuren\Documents\AxonAssessment\TaskA\Dashboard_V2` 打开 PowerShell：

```powershell
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
.\.venv\Scripts\python.exe -m streamlit run app.py
```

已有兼容环境可直接使用，无需重新创建。未配置录入时，现有 `database/harbourview.duckdb` 仍能供分析页面使用；“新增居民记录”显示配置提示并禁用提交。启动、页面重绘、筛选与原有聊天占位交互不会触发全量计算。

## 显式配置与初始化

本次交付不创建正式配置，不启用正式原始数据版本，不向正式 CSV 添加记录。

1. 将 `report_config.example.json` 复制为 `report_config.json`。
2. 明确指定原始 CSV、版本目录和所有报告参数。相对路径以配置文件所在目录解析，不根据文件名自动选择数据源。
3. 核对后显式执行初始化，再启动或刷新 dashboard。

以下配置**仅为示例，日期、财年、容量及数据来源均需根据实际数据确认**。`2026-01-15` 在既有分析中为推定快照日期，不代表已确认的提取日期：

```json
{
  "source_csv": "data/harbourview_residents.csv",
  "version_root": "report_store",
  "report": {
    "as_of": "2026-01-15",
    "fiscal_year": 2025,
    "capacity": 24,
    "followup_anchor": "discharge",
    "occupancy_start": "2025-01-01"
  }
}
```

`as_of` 为源快照截止。财年为自然年，生效报告截止取快照日期与财年末的较早值；上述示例生效截止为 `2025-12-31`。`fiscal_year: null` 表示截至显式快照日期的全历史报告。入住率起始日期必须显式指定，容量为已确认的常数，表单不可更改。

```powershell
# 先确认配置与实际数据，再明确执行；不会覆盖原 CSV 或已有数据库。
python report_versions.py initialize --config report_config.json
python report_versions.py status --config report_config.json
python -m streamlit run app.py
```

也可在启动前设置 `$env:HARBOURVIEW_CONFIG = 'C:\absolute\report_config.json'`。
已有启用版本时拒绝再次初始化。若需要其他报告参数，请配置独立的 `version_root` 并显式初始化；不要直接修改启用版本的参数。

初始化从明确配置的 `source_csv` 建立第一个版本。此后“可追加的原始数据源”是该存储内当前启用的 `raw.csv`；初始 CSV 作为种子保持原样。不要继续直接编辑种子 CSV 并期待 dashboard 自动同步，也不要手动修改历史版本文件。

## 新增居民记录

导航选择“新增居民记录”，查看录入目标、启用版本及报告参数。填入居民 ID，其他日期允许留空；未填写日期不会自动填为今天。状态与随访值沿用计算程序枚举。退出原因为原始文本，`completed` 才会进入完成项目子集。费用为空与费用为零分别保留。

点击“预览记录”：检查 ID、日期、金额、枚举、容量，显示规范化后的完整新增行及 pipeline 质量警告。ID 按加载逻辑去除首尾空白后比较，大小写保持原规则。格式错误阻止保存；日期倒序、状态冲突等质量标记会显示，但不会一律升级为禁止录入。

点击“确认提交”：重新检查 ID、源版本、文件哈希、配置和计算代码版本。已有列和已有单元格原样保留；新记录的额外列留空。修改表单后需重新预览。发布时相关控件禁用；锁与提交标识共同防止重复写入。

成功后显示居民 ID、版本、完成状态及报告截止日期，并切换到新数据库、清理缓存。新增居民的日期可能超出报告截止，因此不保证出现在当前报告的所有指标中；程序不会为此更改截止日期。

侧栏可以继续浏览其他 DuckDB 文件，界面会明确显示“正在浏览的报告”和“录入更新的启用版本”。浏览历史报告不会改变录入目标。汇总下载只包含原有汇总，不增加居民原始记录下载入口。

## 发布结构、失败与恢复

```text
report_store/
  current.json                  # 唯一启用指针，原子替换
  versions/<version>/
    raw.csv                     # 对应版本的完整原始数据
    aggregates/                 # 汇总 CSV、metrics.json、报告及计算明细
    report.duckdb               # 仅六张 dashboard 汇总表
    manifest.json               # 参数、来源与数据库哈希、计算版本、前驱及提交标识
```

每个版本使用独立数据库，不新增数据库内的多批次 `run_id` 管理。完整个人记录和计算明细仅存在本地版本目录，未加入页面汇总下载。请按个人资料的访问要求保管和备份整个存储。

候选 CSV → `metrics.calculate_file()` → 导出 → 新 DuckDB → 校验 → 原子切换 `current.json`。启用前任何阶段失败，原来的原始数据版本和数据库继续对应；候选文件可能保留在独立目录，不能把这些文件当作已保存记录。

页面显示失败阶段，保留当前会话的输入和预览。临时计算/导入故障排除后可再次确认；若源数据、参数或计算程序变化，则必须重新预览。相同提交在已经启用后再次执行会返回原收据，不重复添加，也不会倒退当前版本。

若进程被强制结束，可能遗留 `.publish.lock`：先停止其他 dashboard 和发布进程，运行 `status` 检查 `current.json`。确认没有发布进程后，将该锁文件重命名为一个未使用的备份名称，然后重试。不要在发布过程中移除锁。若崩溃发生在原子切换之后，`status` 会显示已启用的新版本；先核实居民 ID 再决定是否重新录入。

正常失败不需要恢复旧 CSV。若版本文件被外部修改、丢失或损坏，应从备份恢复完整版本目录和对应清单；程序会拒绝在哈希不一致的数据上继续新增。没有自动删除历史版本或候选目录的操作。`export_result()` 本身不是原子发布，请通过这里的版本流程启用报告。

单独生成汇总及新数据库（不启用为录入版本）：

```powershell
# 日期仅为示例，需确认；两个输出路径应为新路径。
python metrics.py data/harbourview_residents.csv --as-of 2026-01-15 --fiscal-year 2025 --capacity 24 --followup-anchor discharge --occupancy-start 2025-01-01 --out scratch/new-aggregates
python duckdb_store.py --source scratch/new-aggregates --db scratch/new-report.duckdb
```

## 验证与限制

```powershell
python -B -m unittest discover -s tests -v
```

测试只在 `tests/` 下的临时目录生成合成 CSV 和数据库，正常结束时清理，不对正式居民 CSV 添加测试记录。覆盖六表读取、空质量表、随访非法值与零分母、床日加权及部分月份、预览一致性、额外列及空日期保留、重复提交、并发锁、各失败阶段、原子切换故障、缓存刷新、未配置禁用录入、历史数据库保护及页面导航。

本轮 24 项集成/UI 测试及既有 7 项计算回归测试全部通过。详细验证记录和测试环境见 `VERIFICATION.md`。AppTest 测试夹具固定为 `st.navigation` 模式，避免测试运行器每次重建页面管理器时误用旧式 `pages/` 自动导航；生产应用不修改 Streamlit 内部实现。

录入范围为本地单人操作，不包含编辑、删除、批量导入或多人权限。Overview 的聊天占位已由 Part B 分析入口替换，详见 `PART_B_README.md`。进程异常退出后可能需要人工恢复锁；表单草稿不跨浏览器会话持久保存。

原始计算的数据限制继续适用：没有随访评估日期，不能证明历史结果当时已知；没有年初居民登记，不能证明历史入住台账完整；未知退出保留上下界；入住率超过 100% 不截断。报告期所需月份、床日或比例无效时，停止展示受影响指标，不把剩余月份冒充完整报告期。
