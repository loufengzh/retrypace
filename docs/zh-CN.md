# retrypace 入门

[English](../README.md) · [Русский](ru.md) · [Deutsch](de.md)

retrypace 是用于设计评审和持续集成的离线重试计划分析工具。它回答三个问题：截止时间内能完成多少次尝试？同时进行的请求最多有多少？任意时间窗口中的请求突发量有多大？

需要 Python 3.10 或更新版本。运行时没有第三方依赖，不发送网络请求，不实际等待，也不收集遥测信息。

## 运行

```sh
git clone https://github.com/loufengzh/retrypace.git
cd retrypace
python -m retrypace --config examples/burst.json --compare
python -m retrypace --config examples/staggered.json --format csv > attempts.csv
python -m unittest discover -s tests -v
```

从源码目录即可运行，无需安装。可选的本地安装命令为 `python -m pip install .`；构建工具可能需要下载。安装后可使用 `retrypace` 命令。目前本项目尚未发布到 PyPI，请勿假定注册表中的同名包就是本项目。

## 配置

新建一个 JSON 文件，使用以下字段；未提供的字段采用下列默认值。所有时间单位均为整数毫秒。

```json
{
  "clients": 100,
  "max_attempts": 5,
  "base_ms": 100,
  "cap_ms": 2000,
  "attempt_ms": 50,
  "deadline_ms": 3000,
  "stagger_ms": 0,
  "window_ms": 100,
  "concurrency_limit": 20,
  "seed": 1,
  "strategy": "full-jitter"
}
```

- `clients`：客户端数量。
- `max_attempts`：每个客户端的总尝试次数上限，包含首次请求。
- `base_ms`、`cap_ms`：基础等待时间和退避上限；上限不得小于基础时间。
- `attempt_ms`：每次请求固定占用的时间，必须为正数。
- `deadline_ms`：相对于各客户端启动时刻的总预算。只有完整请求能在预算内结束时才会启动；恰好结束于截止时刻的请求允许执行。值为零时不执行任何请求。
- `stagger_ms`：相邻客户端启动时间的间隔；零表示同时启动。
- `window_ms`：统计请求启动数量的窗口宽度。
- `concurrency_limit`：用于统计超限压力的参考值，不会限制请求、建立队列或丢弃请求。
- `seed`：0 到 2³²−1 的确定性种子。
- `strategy`：`fixed`、`exponential`、`full-jitter`、`equal-jitter` 或 `decorrelated`。

除截止时间、启动间隔和种子外，数字必须为正整数；布尔值不能替代整数。其他数字上限为 1,000,000,000。未知字段会报错。`clients × max_attempts` 不得超过 1,000,000；大型场景仍可能占用大量内存。

`--config` 接受不带 BOM 的 UTF-8 JSON 对象，文件最多为 64 KiB（65,536 字节），空白也计入限制。重复的 JSON 键会被拒绝，即使值相同，或键通过不同的 JSON 转义写法表示；不会采用“最后一个键覆盖前一个键”的规则。NaN 和 Infinity 也会被拒绝。输入无效、过大或嵌套过深时，命令在应用策略覆盖或 CI 阈值之前以退出码 1 结束，不输出报告。字节限制仅适用于 CLI 文件读取；`Config.from_dict` 校验已解析的映射，无法发现其他 JSON 加载器已丢弃的重复键。

## 模型与策略

模型假设每次请求均失败，并在请求结束后开始等待。客户端串行重试，不同客户端互不影响。首次重试的指数上限为基础等待时间，之后翻倍，直到上限。

- 固定等待：始终等待基础时间。
- 指数退避：等待当前指数上限。
- 完全抖动：在零和当前指数上限之间取整数。
- 等量抖动：在指数上限的一半（向上取整）和指数上限之间取整数。
- 去相关抖动：在基础时间和上次等待时间的三倍之间取整数，然后应用上限；初始的上次等待时间等于基础时间。

所有随机区间均包含两端。相同配置和种子产生相同结果；随机数发生器不用于密码学，也不应直接视为生产重试实现。

## 阅读结果

JSON 包含 `schema_version`、`model`、`config`、`summary`、`buckets` 和可选的 `events`。

- `attempts` / `retries`：实际纳入计划的总请求数 / 重试数。
- `clients_stopped_by_deadline`：下一次完整尝试无法放入预算的客户端数量。
- `clients_stopped_by_attempt_limit`：达到总尝试次数上限的客户端数量。
- `peak_concurrency`：同时进行的请求峰值；请求区间为 `[开始, 结束)`，同一时刻结束和开始的请求不重叠。
- `peak_window_starts`：任意半开窗口中的启动次数峰值，能够发现跨越固定桶边界的突发。
- `peak_aligned_bucket_starts`：对齐到全局零时刻的固定桶峰值；空桶不输出。
- `retry_peak_concurrency` / `retry_peak_window_starts`：排除首次请求后的对应峰值。
- `time_over_concurrency_limit_ms`：并发严格超过参考值的总时长。
- `excess_concurrency_ms`：超过参考值的并发数量对时间的积分，单位为请求·毫秒。
- `max_client_elapsed_ms`：客户端从启动到最后一个已纳入请求完成的最大时长。
- `min_client_budget_remaining_ms`：最后一个已纳入请求完成后剩余预算的最小值。
- `schedule_end_ms`：全局最后完成时间，包含错峰启动偏移。

`examples/burst.json` 中，完全抖动将重试并发峰值从固定等待的 100 降至 51，但最忙的 100 毫秒窗口中的重试启动次数从 100 增至 109。较短等待可以容纳更多重试。所有策略仍有 100 个同时启动的首次请求。单一种子不代表统计结论。

## CLI 和持续集成

```sh
python -m retrypace --config examples/burst.json --summary-only > report.json
python -m retrypace --config examples/burst.json --strategy exponential
python -m retrypace --config examples/staggered.json \
  --max-peak-concurrency 50 --max-window-starts 200 > report.json
```

阈值检查包含首次请求。等于阈值时通过，严格大于阈值时失败。`--compare` 比较全部五种策略，任一种失败就返回失败。即使失败也会输出 JSON；诊断写入标准错误。CSV 导出字段为 `client,attempt,start_ms,end_ms`，不能与 `--compare` 或 `--summary-only` 同用。

退出码：0 表示成功，1 表示配置无法读取或无效，2 表示超出阈值或命令行用法错误。`--help` 查看帮助，`--version` 查看版本。`--summary-only` 只减少输出，不减少核心模拟所需内存。

## Python 接口

```python
from retrypace import Config, compare, simulate

config = Config(clients=30, max_attempts=4, deadline_ms=1000, seed=42)
report = simulate(config)
print(report["summary"]["retry_peak_concurrency"])
policies = compare(config)
```

`Config` 不可变且会校验输入。`Config.from_dict(mapping)` 可用于读取 JSON 配置。`simulate(config, include_events=False)` 不输出逐次事件。`compare` 返回策略名称到报告的映射。

## 使用边界

这是一种规定场景的压力分析，不是恢复概率预测、排队模型或真实负载测试。它不模拟成功、服务恢复、可变延迟、服务器限流、Retry-After、嵌套重试、取消或幂等性。并发阈值不会改变调度。使用真实服务遥测和负载测试验证生产策略。

[Retry Lab](https://github.com/kyan9400/retry-lab) 提供浏览器交互式恢复模拟；本工具专注可复现的离线截止预算和压力审计。退避策略参考 [AWS 的技术文章](https://aws.amazon.com/blogs/architecture/exponential-backoff-and-jitter/)，没有复制其他项目代码。详细算法见[模型文档（英文）](model.md)。许可证：[MIT](../LICENSE)。
