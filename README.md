# � Factor Loop Evolve

**简体中文** | [English](README.en.md)

> 本地闭环因子进化系统：自动进行验证 → 回测 → 诊断 → 学习 → 变体生成的迭代进化，实现自我改进的因子发现。回测基于 PandaData 真实 A 股数据（CSI 300 / CSI 500，可配置时间范围）。

![type](https://img.shields.io/badge/type-agent--skill-blue)
![license](https://img.shields.io/badge/license-GPLv3-blue)

---

## 📖 这是什么

`skill-factor-loop-evolve` 是一个面向 AI Agent 的本地闭环因子进化技能。传统因子研究中，研究者需要手动编写因子、逐一回测、人工分析结果、凭经验改进。这个技能将整个过程自动化：

1. **验证** — 对每个因子检查语法、字段合法性、前视偏差、数值稳定性，拒绝不合格候选，避免浪费回测资源。
2. **固定回测** — 使用 PandaData API 获取真实 A 股数据，一致的截面多空回测引擎（可配置股票池、频率、标签、成本），保证迭代间可比。组合收益从调仓日计算，无前视偏差。换手率基于实际持仓变化计算。
3. **诊断分类** — 计算 IC、ICIR、Sharpe、收益、回撤、换手率、覆盖率、稳定性、多空行为、相关性，按优先级分类：invalid → overfit → unstable → duplicate → weak → promising。
4. **经验记忆** — 持久化每次迭代的经验：哪些字段有效、哪些模板失败、哪些结构导致高换手、哪些变体相关性过高、哪些改进提升了稳定性。
5. **可控变体生成** — 选取当前最强因子为父本（按**实际 Sharpe** 排序，最高优先）。**默认使用 LLM 驱动的语义变换**（可在 `config.json` 中关闭，回退到 12 种硬编码变换）。LLM 基于完整诊断档案、经验记忆和用户原始查询提出变换建议。
6. **迭代循环** — 重复步骤 2–5，直到 N 轮完成、改进停滞或配置的最大迭代次数到达。

**自包含设计** — 无需任何付费 API 密钥。依赖 PandaData（免费）获取真实 A 股数据。

---

## 📥 输入方式与示例

技能接收因子表达式作为输入，支持四种方式：**显式表达式**、**随机生成**、**用户指令**、**文档提取**。所有输入必须遵循[因子字段/函数契约](references/factor-contract.md)。

### 输入 1️⃣：显式因子表达式（最直接）

直接给出一个或多个合规的因子表达式，Agent 将其包装为因子对象并送入流水线。适合你已有明确想法时使用。

```text
用户: 帮我优化这个因子：rank(returns(close,20) / ts_std(returns(close,1),60))
```

Agent 自动补全 `name`、`description`、`rationale` 等元数据，生成因子对象送入优化流水线。也可以一次给出多个表达式：

```text
用户: 优化这三个因子：
  - returns(close,20) - returns(close,5)
  - zscore(decay_linear(returns(close,1), 20) * volume)
  - (high - low) / ts_mean(close, 10)
```

### 输入 2️⃣：随机生成

Agent 随机组合合法字段和函数，生成 5–15 个候选因子。适合探索性研究——不知道什么有效时广泛撒网。例如自动生成 `returns(close,5) * rank(volume)`、`-ts_rank(returns(close,1),20)`、`ts_argmax(volume,60)` 等组合。

```text
用户: 帮我随机生成 10 个因子跑 5 轮迭代
```

### 输入 3️⃣：根据用户指令生成

用户用自然语言描述研究方向，Agent 将意图转化为合规的因子表达式。

```text
用户: 帮我优化一个动量因子，要求 20 日窗口、风险调整、排除极端值，跑 3 轮迭代
```

Agent 解读意图后生成一系列相关因子变体，如 `returns(close,20)`（基础）、`returns(close,20)/ts_std(returns(close,1),60)`（风险调整）、`clip(returns(close,20), -0.15, 0.15)`（截尾）、`rank(returns(close,20))`（排名化）、`decay_linear(returns(close,1),20)`（衰减加权）等。

更多用户指令示例：

| 用户指令 | Agent 解读 | 候选因子方向 |
|----------|-----------|-------------|
| "优化低换手率的价值因子" | 价值类 + 低 turnover | `rank(1/close)`, `ts_mean(close,60)/close` 等 |
| "找一个量价背离信号" | 价格与成交量趋势背离 | `correlation(close,volume,20)`, `returns(close,10)-delta(volume,10)` 等 |
| "改进 Sharpe > 0.8 的质量因子" | 高质量 + 目标 Sharpe | ROE 类代理、低波动、稳定增长类因子 |
| "帮我跑 5 轮随机探索" | 无特定方向，广泛尝试 | 随机组合多种字段和函数 |
| "基于研报中的反转因子优化" | 反转类 + 文献参考 | 短期反转、隔夜反转、行业调整反转等 |

### 输入 4️⃣：从文档/研报提取

用户提供研究文档（PDF、Markdown、研报摘要），Agent 提取其中的因子描述并转化为合规表达式。

```text
用户: 这篇研报提到"成交量加权的 20 日动量因子表现优于传统动量，
      构建方式为将过去 20 个交易日的日收益率按当日成交量加权求和，
      再做截面标准化"——帮我提取并优化这个因子
```

Agent 提取后生成多种合规变体，如 `zscore(decay_linear(returns(close,1)*volume,20))`（衰减加权版）、`rank(decay_linear(returns(close,1)*volume,20))`（排名版）、`ts_sum(returns(close,1)*volume,20)/ts_sum(volume,20)`（简化版）等。

### 输入格式说明

无论哪种输入方式，每个因子最终表示为包含以下字段的 JSON 对象。Agent 会自动补全元数据。

| 字段 | 类型 | 必填 | 说明 |
|------|------|------|------|
| `name` | string | ✅ | 唯一标识，snake_case，如 `risk_adj_mom_20d` |
| `expression` | string | ✅ | 合规因子公式，仅用 6 个字段 + 允许函数 |
| `description` | string | ✅ | 一句话描述因子含义 |
| `rationale` | string | ✅ | 经济学或统计学理由 |
| `generation` | string | ✅ | 来源：`manual` / `random` / `document` / `variant-*` |
| `parent` | string | ❌ | 父因子名（变体时填写） |
| `transformation` | string | ❌ | 应用的变换描述（变体时填写） |

> ⚠️ 系统会在验证阶段自动拒绝不符合[因子契约](references/factor-contract.md)的表达式。

---

## ⚙️ 超参数配置

所有超参数集中在 `config.json` 中管理，每个字段都有 `_help` 文档说明。直接编辑该文件即可调整行为。每次运行时 `config.json` 会被自动复制到输出目录，确保结果可复现。

> 💡 **用户指令覆盖**：当用户在查询中明确指定了某个超参数（如 "跑 10 轮"、"每轮 5 个父本"、"最少 2 个变换"），Agent 会用用户指定的值覆盖 `config.json` 中的对应默认值，仅对本次运行生效。

---

## 🔍 如何解读结果

每次运行完成后，输出目录 (`output/<run_id>/`) 包含以下最终文件：

### 核心输出文件

| 文件 | 内容 | 如何使用 |
|------|------|----------|
| `final_summary.json` | **汇总报告**：优化日志、最佳 5 个因子、Pareto 前沿、是否值得保留、原始查询、进化图谱、当前配置 | 首先看这个文件，了解整体结果 |
| `evolution_diagram.md` | **进化图谱**：Mermaid 流程图 + 回测配置 + 最佳 10 个因子表 + 变换参考（仅显示实际使用的变换及 LLM 理由） | VS Code 中用 `Cmd+Shift+V` 预览 |
| `diagnosis.json` | **诊断结果**：每个因子的分类、Sharpe、IC、换手率、改进建议 | 深入了解每个因子的优劣 |
| `backtest_results_all.json` | **全部回测**：所有迭代轮回测结果的累积 | 对比各轮迭代间的指标变化 |
| `knowledge_base.json` | **经验记忆**：成功模式、失败模式、字段有效性统计 | 了解什么特征持续有效 |
| `transform_suggestions.json` | **LLM 变换建议**：LLM 对每个父本提出的具体变换及其理由（LLM 模式下保留） | 了解 LLM 的变换思路 |
| `candidate_evolution.json` | **完整系谱树**：每个因子的父子关系及每节点指标 | 追踪因子进化路径 |
| `config.json` | **运行配置**：本次运行使用的完整配置 | 复现运行 |

---

## 🧬 进化机制：变换详解

### 变换模式

变换模式由 `config.json` 中的 `transformations.use_llm_transforms` 控制：

- **`true`（默认）**：使用 LLM 驱动的语义变换。LLM 基于每个父本因子的完整诊断档案（Sharpe、IC、换手率、回撤、多空收益）、经验记忆（成功/失败模式、字段有效性）和用户原始查询，提出 3–5 个语义上有意义的变换。这些不是简单的语法包装（如套一层 `clip()`），而是真正的逻辑改进——组合字段、调整权重、添加互补信号、改变函数族。
- **`false`**：使用原始的 12 种硬编码变换。

可通过 `--use-llm`（强制 LLM）、`--no-llm`（强制静态）命令行参数覆盖。

### 静态变换参考（LLM 关闭时使用）

| 变换 | 理由 |
|------|------|
| `flip-sign` | Sharpe 为负 — 反转表达式符号即可恢复正 Sharpe |
| `reduce-turnover` | 换手率 > 0.8 — 平滑信号以降低交易频率和成本 |
| `adjust-lookback` | IC 信号过于嘈杂或过于平滑 — 调整回看窗口可改善稳定性 |
| `adjust-smoothing` | 换手率极端 — 调整平滑方式以平衡信号衰减与交易成本 |
| `adjust-clipping` | 极端离群值扭曲信号 — 截尾处理可限制其影响 |
| `adjust-normalization` | 因子分布偏斜 — 切换归一化方法改善截面可比性 |
| `combine-factors` | 两个因子均表现良好且相关性低 — 组合可分散 alpha 来源 |
| `simplify` | 表达式过于复杂 — 移除嵌套可降低过拟合风险 |
| `remove-component` | 子成分弱或噪音大 — 移除可提纯剩余信号 |
| `long-only` | 空头端表现差 — 仅保留多头消除无效空头 |
| `short-only` | 多头端表现差 — 仅保留空头消除无效多头 |
| `asymmetric` | 多空收益不对称 — 加权捕捉更强的一端 |

---

## 🚀 快速开始

### 环境准备

创建 `.env` 文件（技能根目录）：

```bash
PANDA_AI_USERNAME="your_username"
PANDA_AI_PASSWORD="your_password"
PANDA_AI_BASE_URL="http://pandadata.pandaaiquant.com"
```

安装依赖：

```bash
pip install -r requirements.txt
# 或直接安装 panda_data wheel：
pip install panda_data/panda_data-0.1.0-py3-none-any.whl
```

### Agent 工作流

```text
用户: 帮我优化动量因子，做 3 轮迭代

Agent:
1. 准备: 设置 FACTOR_OPTIMIZE_RUN_DIR，初始化知识库
2. 将初始候选因子放入 candidates.json
3. 每轮迭代:
   - 验证: python scripts/validator.py --factors candidates.json
   - 回测: python scripts/backtest.py --factors validated_factors_passed.json --output backtest_results_all.json
   - 诊断: python scripts/diagnose.py --results backtest_results_all.json --factors validated_factors_passed.json --output diagnosis.json
   - 学习: python scripts/knowledge_base.py --learn diagnosis.json --knowledge knowledge_base.json
   - 🆕 LLM 变换（默认启用）:
     python scripts/llm_suggest.py --generate-prompt ... → 发送给 LLM → 保存响应 →
     python scripts/llm_suggest.py --apply-response ... → 生成 transform_suggestions.json
   - 生成: python scripts/generate_candidates.py ... --query "$USER_QUERY"
     （默认自动检测并使用 LLM 变换建议）
4. 汇总: python scripts/optimizer.py --summary --knowledge knowledge_base.json --output final_summary.json
5. 报告: 优化日志、最佳 5 个因子、Pareto 前沿、是否值得保留、关键模式
```

### 直接使用

```bash
# 设置运行目录（自动生成时间戳）
export FACTOR_OPTIMIZE_RUN_DIR="output/run_$(date +%Y%m%d_%H%M%S)"

# 初始化知识库
python scripts/knowledge_base.py --init --output "$FACTOR_OPTIMIZE_RUN_DIR/knowledge_base.json"

# 验证 → 回测 → 诊断 → 学习 → 生成（每轮重复）
python scripts/validator.py --factors candidates.json
python scripts/backtest.py --factors validated_factors_passed.json --output backtest_results_all.json
python scripts/diagnose.py --results backtest_results_all.json --factors validated_factors_passed.json --output diagnosis.json
python scripts/knowledge_base.py --learn diagnosis.json --knowledge knowledge_base.json

# 🆕 LLM 变换（默认，自动检测 transform_suggestions.json；无文件时回退到静态变换）
python scripts/generate_candidates.py --diagnosis diagnosis.json --knowledge knowledge_base.json --output next_candidates.json --query "$USER_QUERY"
# 或强制使用静态变换:
python scripts/generate_candidates.py ... --no-llm

# 最终汇总
python scripts/optimizer.py --summary --knowledge knowledge_base.json --output final_summary.json
```

所有路径相对于输出目录。设置 `FACTOR_OPTIMIZE_RUN_DIR` 确保各脚本之间的连续运行。

---

## 📦 目录结构

```
skill-factor-loop-evolve/
├── SKILL.md                              # 技能入口（YAML 声明 + Agent 指令）
├── README.md / README.en.md              # 说明文档
├── config.json                           # 所有超参数 + _help 文档
├── LICENSE                               # GPL-3.0
├── requirements.txt                      # numpy, pandas, pyyaml, python-dotenv, panda_data
├── references/
│   ├── factor-contract.md                # 📚 因子字段/函数契约
│   ├── optimization-protocol.md          # 🔄 优化循环协议、分类体系、停止条件
│   └── agent-integration.md              # 🔌 多 Agent 安装与冒烟测试
├── scripts/
│   ├── contracts.py                      # 共享契约 + 配置加载（单一事实来源）
│   ├── validator.py                      # 🧪 因子验证器（语法、前视偏差、数值稳定性）
│   ├── backtest.py                       # 📊 回测引擎（PandaData 真实 A 股数据）
│   ├── diagnose.py                       # 🔍 因子诊断与分类
│   ├── knowledge_base.py                 # 🧠 经验记忆管理 + 主动学习
│   ├── generate_candidates.py            # 🔀 变体生成（LLM 优先，静态回退）
│   ├── llm_suggest.py                    # 🤖 LLM 变换建议引擎
│   └── optimizer.py                      # 🔁 优化循环协调器 + 进化图谱 + Pareto 前沿
├── agents/
│   ├── openai.yaml                       # OpenAI/Codex 适配
│   ├── cursor-rule.mdc                   # Cursor 规则适配
│   └── portable-loader.md                # 通用 Agent 加载器
└── output/
    └── <run-id>/                         # 每次运行独立子目录
        ├── backtest_results_all.json     # 全部迭代回测累积
        ├── diagnosis.json                # 分类 + 指标 + 建议
        ├── knowledge_base.json           # 经验记忆
        ├── candidate_evolution.json      # 完整系谱树 + 原始查询
        ├── transform_suggestions.json    # LLM 变换建议（LLM 模式下）
        ├── final_summary.json            # 汇总报告 + Pareto 前沿
        ├── evolution_diagram.md          # Mermaid 进化图谱 + 回测配置
        ├── config.json                   # 运行配置（可复现）
        └── trading_data/                 # CSV：收益、IC、持仓
```

---

## ⚠️ 免责声明

本仓库仅作研究方法层面的整理，不构成任何投资建议。

## 👤 维护者

创建与维护：`davideliu`（QuantSkills community）。

## 📜 License

GPL-3.0. See [LICENSE](LICENSE).
