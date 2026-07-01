# Factor Loop Evolve

**简体中文** | [English](README.en.md)

面向 AI Agent 的本地闭环因子进化技能：生成候选因子、验证、用
PandaData A 股数据回测、诊断表现、让 LLM 提出语义改进，然后迭代。

本技能仅用于研究流程，不构成投资建议。

## 功能概览

- 按因子契约验证表达式是否合法。
- 使用真实 A 股 OHLCV 数据进行固定口径多空回测。
- 用 Sharpe、IC、换手率、回撤和分类结果诊断因子。
- 在单次运行内记录有效模式和失败模式。
- 默认优先使用 LLM 生成改进建议，再生成下一批候选因子。
- 输出最终汇总和进化图，方便复盘。

## 输入方式

可以从以下内容开始：

- 一个或多个明确的因子表达式。
- 自然语言因子想法，例如动量、反转、量价背离。
- 随机探索请求。
- 研报、论文或笔记中的因子描述。

所有表达式都必须遵循[因子契约](references/factor-contract.md)。

示例：

```text
帮我优化这个因子，跑 3 轮：
rank(returns(close,20) / ts_std(returns(close,1),60))
```

```text
随机生成 10 个动量和反转候选因子，跑 5 轮进化。
```

## 环境准备

在技能根目录创建 `.env`：

```bash
PANDA_AI_USERNAME="your_username"
PANDA_AI_PASSWORD="your_password"
PANDA_AI_BASE_URL="http://pandadata.pandaaiquant.com"
```

安装依赖：

```bash
pip install -r requirements.txt
```

## 结果解读

优先阅读 `final_summary.json`，其中包含：

- 每轮最佳 Sharpe 变化。
- 最佳因子列表。
- Pareto 前沿。
- 是否值得保留。
- 原始用户请求。
- 本次运行配置。

其他常用输出：

- `diagnosis.json`：每个因子的指标和分类。
- `backtest_results_all.json`：所有迭代的回测结果。
- `knowledge_base.json`：本次运行学到的模式。
- `candidate_evolution.json`：因子父子关系。
- `evolution_diagram.md`：进化图。
- `trading_data/`：组合收益、IC 序列和持仓。

## 配置

通过 `config.json` 调整回测区间、股票池、成本、停止条件、分类阈值和变换设置。

如果用户明确指定参数，例如“跑 10 轮”或“用 CSI 500”，本次运行应优先使用用户指定值。

## 参考文件

- `SKILL.md`：Agent 主说明。
- `references/factor-contract.md`：字段、函数和表达式规则。
- `references/optimization-protocol.md`：循环协议和分类规则。
- `references/agent-integration.md`：安装和冒烟测试。

## License

GPL-3.0. See [LICENSE](LICENSE).
