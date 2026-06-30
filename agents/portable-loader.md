# Portable Loader Prompt

Use this prompt in Claude Code, Hermes, OpenClaw, or any agent runtime that does
not natively discover `SKILL.md` folders.

```text
You have access to a local skill named factor-loop-evolve at:
<<SKILL_ROOT>>

When the user asks to optimize factors, run an iterative factor evolution
pipeline, or improve a factor library through closed-loop research:

1. Read <<SKILL_ROOT>>/SKILL.md.
2. Read <<SKILL_ROOT>>/references/factor-contract.md for the
   field/function contract.
3. Read <<SKILL_ROOT>>/references/optimization-protocol.md for
   the loop protocol, classification taxonomy, and stopping criteria.
4. Read <<SKILL_ROOT>>/config.json for current hyperparameters.
5. Set FACTOR_OPTIMIZE_RUN_DIR and init knowledge base:
   python <<SKILL_ROOT>>/scripts/knowledge_base.py --init --output $FACTOR_OPTIMIZE_RUN_DIR/knowledge_base.json
6. Place initial candidates as candidates.json in the output directory (5–15 factors).
7. For each iteration 1..N:
   a. Validate:
      python <<SKILL_ROOT>>/scripts/validator.py --factors candidates.json
   b. Backtest:
      python <<SKILL_ROOT>>/scripts/backtest.py --factors validated_factors_passed.json --output backtest_results.json
   c. Diagnose:
      python <<SKILL_ROOT>>/scripts/diagnose.py --results backtest_results.json --factors validated_factors_passed.json --output diagnosis.json
   d. Learn:
      python <<SKILL_ROOT>>/scripts/knowledge_base.py --learn diagnosis.json --knowledge knowledge_base.json
   e. Check stopping criteria (stall, max iterations).
   f. Generate next batch:
      python <<SKILL_ROOT>>/scripts/generate_candidates.py --diagnosis diagnosis.json --knowledge knowledge_base.json --output next_candidates.json
      Then validate next_candidates.json for the next loop.
8. After all iterations:
   python <<SKILL_ROOT>>/scripts/optimizer.py --summary --knowledge knowledge_base.json --output final_summary.json
9. Read final_summary.json and present:
   - Optimization log (Sharpe progression)
   - Top 5 best factors
   - Whether worth keeping
   - Key patterns from knowledge_base.json
   - Preview evolution_diagram.md
```

Runtime placement notes:
- Codex: keep under a Codex skill path, invoke `$factor-loop-evolve`.
- Claude Code: keep under a Claude skill path, invoke `$factor-loop-evolve`.
- Cursor: copy to `.cursor/skills/factor-loop-evolve`, enable `agents/cursor-rule.mdc`.
- Hermes/OpenClaw: mount as local skill root or paste loader prompt with real path.
