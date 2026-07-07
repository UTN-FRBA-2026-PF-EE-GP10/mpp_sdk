# improve/ - advisor audit runs

Output of codebase audits run with the `improve` skill. Each dated folder is
one audit run; its `plans/` subfolder holds self-contained implementation
plans an executor (human or agent) can pick up with zero prior context, plus
a `plans/README.md` index with execution order and status.

## Runs

| Date | Scope | Index |
|------|-------|-------|
| 2026-07-06 | Python SDK + harness + tests + firmware (INA sensing emphasis) | [2026-07-06/plans/README.md](2026-07-06/plans/README.md) |

Conventions:

- Plans are numbered in recommended execution order (`NNN-slug.md`).
- Executors update their plan's status row in the run's `plans/README.md`.
- Plans never contain secrets; findings reference `file:line` only.
