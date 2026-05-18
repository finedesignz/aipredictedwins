import json, pathlib

data = {
  "metadata": {
    "skill_name": "ui-data-audit",
    "skill_path": ".claude/skills/ui-data-audit",
    "executor_model": "claude-sonnet-4-6",
    "analyzer_model": "claude-sonnet-4-6",
    "timestamp": "2026-04-10T16:30:00Z",
    "evals_run": [1, 2, 3],
    "runs_per_configuration": 1
  },
  "runs": [
    {"eval_id": 1, "eval_name": "Full dashboard audit", "configuration": "with_skill", "run_number": 1,
     "result": {"pass_rate": 1.0, "passed": 5, "failed": 0, "total": 5, "time_seconds": 574.6, "tokens": 107954, "tool_calls": 58, "errors": 0},
     "expectations": [
       {"text": "Report references at least 6 of the 8 standard checks by name", "passed": True, "evidence": "8-check summary table used across all 8 pages"},
       {"text": "Report covers at least 5 distinct pages", "passed": True, "evidence": "8 pages covered"},
       {"text": "Report contains summary table with PASS/FAIL/WARN columns", "passed": True, "evidence": "Summary table uses PASS/WARN/FAIL per check per page"},
       {"text": "Each issue includes specific file path reference", "passed": True, "evidence": "All issues include paths like dashboard/web/types/index.ts:77-95"},
       {"text": "Report does not say everything PASSES without reading code", "passed": True, "evidence": "Found 4 FAILs and 8 WARNs"}
     ], "notes": []},
    {"eval_id": 1, "eval_name": "Full dashboard audit", "configuration": "without_skill", "run_number": 1,
     "result": {"pass_rate": 0.60, "passed": 3, "failed": 2, "total": 5, "time_seconds": 309.1, "tokens": 97463, "tool_calls": 52, "errors": 0},
     "expectations": [
       {"text": "Report references at least 6 of the 8 standard checks by name", "passed": False, "evidence": "Uses Status+KeyIssue table, no structured 8-check framework"},
       {"text": "Report covers at least 5 distinct pages", "passed": True, "evidence": "10 entries covering 8 pages"},
       {"text": "Report contains summary table with PASS/FAIL/WARN columns", "passed": False, "evidence": "Uses Mostly working/Working/Broken labels, not PASS/FAIL/WARN per-check"},
       {"text": "Each issue includes specific file path reference", "passed": True, "evidence": "Issues include file paths"},
       {"text": "Report does not say everything PASSES without reading code", "passed": True, "evidence": "Found signals broken, risk gate broken"}
     ], "notes": ["Found unique bugs: pnl_percent always null, exit_price.toFixed bug, dead benchmark fetch"]},
    {"eval_id": 2, "eval_name": "Signals page targeted check", "configuration": "with_skill", "run_number": 1,
     "result": {"pass_rate": 1.0, "passed": 5, "failed": 0, "total": 5, "time_seconds": 108.5, "tokens": 37652, "tool_calls": 16, "errors": 0},
     "expectations": [
       {"text": "Agent reads the backend signals route not just the frontend", "passed": True, "evidence": "Read signals.py, quoted TODO comments from lines 6 and 133"},
       {"text": "Agent reads the Signal TypeScript type definition", "passed": True, "evidence": "Read dashboard/web/types/index.ts"},
       {"text": "Report correctly identifies useAPI hook not hardcoded data", "passed": True, "evidence": "PASS on Endpoint exists with correct useAPI identification"},
       {"text": "Report produces a per-page check table with individual pass/fail/warn", "passed": True, "evidence": "8-row table with Check, Status, Notes columns"},
       {"text": "Report covers loading state check", "passed": True, "evidence": "Loading state PASS with page.tsx lines 32-36 reference"}
     ], "notes": []},
    {"eval_id": 2, "eval_name": "Signals page targeted check", "configuration": "without_skill", "run_number": 1,
     "result": {"pass_rate": 0.40, "passed": 2, "failed": 3, "total": 5, "time_seconds": 71.6, "tokens": 31095, "tool_calls": 13, "errors": 0},
     "expectations": [
       {"text": "Agent reads the backend signals route not just the frontend", "passed": True, "evidence": "Confirmed _PLACEHOLDER_SIGNALS in signals.py"},
       {"text": "Agent reads the Signal TypeScript type definition", "passed": False, "evidence": "Did not explicitly read Signal type fields"},
       {"text": "Report correctly identifies useAPI hook not hardcoded data", "passed": True, "evidence": "Frontend wiring correctly identified as correct"},
       {"text": "Report produces a per-page check table with individual pass/fail/warn", "passed": False, "evidence": "Prose format only, no structured per-check table"},
       {"text": "Report covers loading state check", "passed": False, "evidence": "Loading state not mentioned or checked"}
     ], "notes": []},
    {"eval_id": 3, "eval_name": "Loading and error states check", "configuration": "with_skill", "run_number": 1,
     "result": {"pass_rate": 1.0, "passed": 5, "failed": 0, "total": 5, "time_seconds": 362.2, "tokens": 105989, "tool_calls": 51, "errors": 0},
     "expectations": [
       {"text": "Report covers at least 5 distinct pages", "passed": True, "evidence": "8 pages covered"},
       {"text": "Report explicitly distinguishes loading state from error state", "passed": True, "evidence": "Separate Check 4 and Check 5 rows in every per-page table"},
       {"text": "Report applies all 8 checks not just checks 4 and 5", "passed": True, "evidence": "Found Risk Gate shape/field FAILs beyond loading/error"},
       {"text": "If any pages missing error states flagged as FAIL or WARN", "passed": True, "evidence": "Error state FAIL on 6 pages with specific file:line references"},
       {"text": "Report is structured table format", "passed": True, "evidence": "Summary table with 8 check columns plus per-page tables"}
     ], "notes": ["Identified shared ErrorBanner pattern as single fix for all 6 affected pages"]},
    {"eval_id": 3, "eval_name": "Loading and error states check", "configuration": "without_skill", "run_number": 1,
     "result": {"pass_rate": 0.80, "passed": 4, "failed": 1, "total": 5, "time_seconds": 205.9, "tokens": 65594, "tool_calls": 36, "errors": 0},
     "expectations": [
       {"text": "Report covers at least 5 distinct pages", "passed": True, "evidence": "13 entries covering 8 pages plus components"},
       {"text": "Report explicitly distinguishes loading state from error state", "passed": True, "evidence": "2-column summary table with separate Loading and Error"},
       {"text": "Report applies all 8 checks not just checks 4 and 5", "passed": False, "evidence": "Only Loading and Error checked"},
       {"text": "If any pages missing error states flagged as FAIL or WARN", "passed": True, "evidence": "MISSING flagged for all pages without error state"},
       {"text": "Report is structured table format", "passed": True, "evidence": "Summary table present"}
     ], "notes": ["Did not find Risk Gate TypeError crash"]}
  ],
  "run_summary": {
    "with_skill": {
      "pass_rate": {"mean": 1.0, "stddev": 0.0, "min": 1.0, "max": 1.0},
      "time_seconds": {"mean": 348.4, "stddev": 191.8, "min": 108.5, "max": 574.6},
      "tokens": {"mean": 83865, "stddev": 32001, "min": 37652, "max": 107954}
    },
    "without_skill": {
      "pass_rate": {"mean": 0.60, "stddev": 0.17, "min": 0.40, "max": 0.80},
      "time_seconds": {"mean": 195.5, "stddev": 99.9, "min": 71.6, "max": 309.1},
      "tokens": {"mean": 64717, "stddev": 27611, "min": 31095, "max": 97463}
    },
    "delta": {"pass_rate": "+0.40", "time_seconds": "+152.9", "tokens": "+19148"}
  },
  "notes": [
    "PASS/FAIL/WARN table assertion: passes 100% with skill, 0% without — the 8-check framework is the core differentiator",
    "Eval 1: without-skill found some unique bugs (pnl_percent null, exit_price.toFixed) that with-skill missed",
    "Eval 3: with-skill found Risk Gate TypeError crash that without-skill missed — from checking all 8 dimensions",
    "Skill costs ~153s and ~19k tokens more — reasonable tradeoff for structured actionable output",
    "Interactive design validation step (Step 3.5) not exercised in evals — requires live user interaction"
  ]
}

p = pathlib.Path("C:/Users/artic/GitHub/aipredictedwins/.claude/skills/ui-data-audit-workspace/iteration-1/benchmark.json")
p.write_text(json.dumps(data, indent=2))
print("Written", p)
