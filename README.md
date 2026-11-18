# 东港试验站波形交接 V1

材料试验站把振动台定标读值交给外场复核组。原始记录可以有缺口。外场按指定窗口领取所需原样点，断开站内库后加工，接班员从独立账册领取历史结果。

缺样反求与凭据入账见 `RECOVERY.md`，接班核对步骤见 `RECOVERY_HANDOFF.md`。

## 一天的交接

1. 采集员接纳 `examples/acquisition.json`，发布长度为 3、单位为 `mm/s` 的修订。样点 0 为 2，样点 2 为 7，样点 1 缺测。
2. 定标员登记 `examples/neighbor_mean.json` 的相邻均值。偏移 0 和 1 的权重均为 1/2，输入输出单位均为 `mm/s`。
3. 交班员用明确的修订和配方版本签出 `[0,3)`，获得固定交接号及领料清单 `[0,1,2]`。
4. 领料员按交接号导出窗口文件并领取固定修订的现有样点，另存为稀疏样点文件。外场只需这两份文件即可开始加工。
5. 外场加工得到欠读 `[1]`、欠读 `[1]`、`7/2`。最后一个输出的右邻在记录外，按零计。接班员由此知道应补取原下标 1。
6. 接班员将行集按 `A1` 整份入账。关闭再打开账册，仍可按 `A1` 领取同样的正文和绑定。
7. 次班以原修订为基，补录 1→3 并更正 2→9，发布新修订。重新签出的交接生成 `5/2`、`6`、`9/2`，按 `A2` 入账。
8. 接班员重开账册，分别领取 `A1` 和 `A2`。原交接仍可按原修订重新领料和复算。

## 运行

在项目根目录使用 Python 3.11 和标准库运行。

```sh
python3 verify.py
python3 -m unittest discover -s tests -t . -v
python3 demo.py
```

`verify.py` 运行完整回归。`demo.py` 在临时目录建立站内库、两个独立交接文件和外场账册，打印重开账册后实际导出的有序结果。两条入口均在验证失败时以非零状态退出。

## Python 接口

| 环节 | 入口与结果 |
| --- | --- |
| 接纳 | `source.import_wave.import_revision(store, source, length, unit, samples, base_revision=None)` 返回新修订号。`import_wave_file(store, path)` 从采集 JSON 接纳。 |
| 当前指针 | `source.revisions.RevisionStore.current_revision(source)` 返回来源最后一次成功发布的修订。`get_revision(revision)` 读取固定记录尺度、来源、单位和基修订。 |
| 配方登记 | `recipe.catalog.register_recipe(store, name, input_unit, output_unit, taps)` 返回不可变版本号。同名可登记新版本。 |
| 签出与重领 | `exchange.prepare.prepare_window(revisions, recipes, issues, revision, recipe_version, lo, hi)` 返回 `WindowPackage`，包含 `issue_id`、`revision`、`length`、`recipe_version`、`units`、`window`、`taps` 和升序 `required_samples`。`exchange.issue_store.export_window(issues, issue_id)` 返回固定 V1 JSON 字节。 |
| 取样 | `source.read_samples.read_samples(revisions, revision, indices)` 返回固定修订的 `SparseSamples`。`source.sample_transfer` 的 `encode_sample_transfer` 和 `decode_sample_transfer` 编解码独立的稀疏样点文件。 |
| 断源加工 | `processing.replay.run_window(package, samples)` 接受 `WindowPackage` 或 V1 JSON 和 `SparseSamples`，返回带交接绑定的 `OfflineRows`。`ValueRow.value` 为 `Fraction`，`MissingRow.missing` 是升序原下标元组。单位由 `package.units.output_unit` 提供。 |
| 成果发布 | `ledger.admission.publish_result(ledger, result_id, package, rows)` 核对固定交接、窗口覆盖、正文形状及欠读来源后提交，返回 `ArchivedResult`。 |
| 重开领取 | `ledger.report_reader.read_result(ledger, result_id)` 返回独立成果副本，`ledger.export.export_result(ledger, result_id)` 返回确定性 JSON 字节。 |
| 缺样反求 | `processing.replay.recover_points(ledger, samples, row_refs, targets)` 从本地账册的已提交 V1 数值行按冻结单级配方建立精确有理方程，返回逐点分类候选。 |
| 反求入账 | `ledger.admission.publish_recovery(ledger, result_id, candidate, *, before_commit=None)` 从账册重建方程并独立核验分类、证据与整组一致性后提交，返回正式成果字典；`ledger.recovery_audit.audit_recovery(ledger, result_id)` 供接班独立核账。 |

`RevisionStore`、`RecipeStore` 和 `WindowIssueStore` 可以连接同一站内 SQLite 文件，`ResultStore` 使用独立账册文件。打开仓储后调用 `initialize()` 建表，用毕调用 `close()`。重复初始化保留已经写入的业务状态。成果发布的可选关键字 `before_commit` 可在行已写入且尚未提交时检查事务边界。回调抛出的异常向上传播，表头和行整次回滚。

采集 JSON 的 `samples` 是形如 `[[原下标,读值], …]` 的数组，保留重复项供接纳时拒收。Python 接纳和配方登记接受映射或键值对序列。读值和权重接受整数、`Fraction`、有限 `Decimal` 及可精确解析的十进制或分数字符串。采集 JSON 的十进制数字按原文解析。布尔值、二进制浮点和非法有理数抛 `ValueError`。稀疏样点文件的每项为 `[下标,分子,分母]`，V1 包中的每个非零权重为 `[偏移,分子,分母]`。文件正规编码使用升序下标、正分母和约分后的有理数。

半开窗口满足 `0 <= lo <= hi <= N`。输出 i 按单级配方读取 `i + offset`。记录外取零，记录内实际缺省的非零权重来源产生欠读。领取并集包含有效但尚未记录的下标。零权重在登记时剔除，空有效来源产生精确零，空窗交出空清单和空行集。修订更正采用显式同来源基修订，沿用其长度、单位、未提及的样点及缺口，覆盖仅写入新修订。

缺固定引用抛 `KeyError`。非法样点、窗口、单位、包、修订绑定或成果正文抛 `ValueError`。失败接纳和签出均不发布状态。成果采用同号同绑定同规范正文的幂等发布，异绑定或异正文抛 `ValueError`。成果表头和全部行在一个事务内提交。

## 正常回归

| 场景 | 业务检查 |
| --- | --- |
| V1、V3 | `tests/test_exchange.py` 核对清单、固定配方版本、空窗、非法签出与单位冲突。 |
| V2 | `tests/test_source.py` 核对重复和非法补录拒收、原修订及当前指针。 |
| V4–V6 | `tests/test_replay.py` 核对独立文件断源加工、边界、精确分数、全部欠读、实测零、非法包和串修订。 |
| V7、V8 | `tests/test_ledger.py` 核对绑定和行覆盖、幂等重放、冲突、空成果、重复初始化、提交前失败及重试。 |
| V9 | `tests/test_shift.py` 核对从旧交接重领原样点、显式分支更正、分别加工及重开领取。 |
| V10 | `tests/test_recovery.py` 与 `check_recovery_chain.py` 核对缺样反求的分类、唯一反求、证据线性组合、发布重放、冲突与改造候选拒绝、提交前失败重试、独立核账及旧库兼容。 |
