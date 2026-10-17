# AGENTS.md

## Project Overview

This project is a Python package designed for calculating and processing Total Electron Content (TEC) data from GNSS observations.

## Commands

Use `uv` for Python and release builds for the Rust extension; see [justfile](justfile) for project commands.
Rebuild the extension after Rust changes before running Python validation.
`build` intentionally updates dependencies/locks and `check` applies fixes; use non-mutating commands for read-only reviews.

## Development Conventions

- **Agent-generated documentation**: Unless explicitly specified otherwise, save agent-generated documents and helper files in `./docs/agents/` which are ignored by git and may be deleted at any time.
- **Docstrings**: Use NumPy-style `Parameters`, `Returns`/`Yields`, `Raises` and `Attributes` sections where applicable.
- **Markdown**: Keep project documentation in English and match the surrounding style unless requested otherwise; write one sentence per line without fixed-width wrapping.
- **README**: Do not modify the README.md file directly unless you are asked to do so or the changes are update to outdated original content.
- **Refactoring**: Preserve numerical behavior and public contracts unless a change is requested; update callers, tests and affected docs together.
- **Scientific validation**: Follow [Scientific Conventions](docs/guide/scientific-conventions.md), clarify uncertain scientific assumptions and distinguish test results from scientific claims.
- **Tests**: Prefer small fixtures and distinct scientific/API regressions over redundant parameter combinations or repeated full-day processing.
- **Benchmarks**: Compare release builds with the same inputs/settings and measure end-to-end runtime and peak memory; generate [benchmark.md](benchmarks/benchmark.md) only with [bench.py](benchmarks/bench.py).
- **Temporary files**: Remove task-created temporary files and comparison environments when finished (keep only the final report).

## Roadmap Workflow

- Read [ROADMAP.md](ROADMAP.md) and relevant task files for Roadmap work; reading does not authorize execution, and ordinary requests need not become tasks.
- When authorized to advance unspecified work, follow Current Focus, then approved plans, then high-priority `ready` tasks with satisfied dependencies; IDs, workstreams and milestones do not set execution order.
- Check the current repository before implementation; update complex-task plans and complete required human reviews before dependent changes.
- Keep Progress & Handoff notes brief: completed work, acceptance progress, validation results, open issues, next steps and constraints; maintain priority, status and dependencies only in the Roadmap or history.
- Mark a task `done` only after all acceptance criteria are verified; update its Roadmap entry, task file and affected docs, then move it to Recently Completed.
- Once confirmed safe to archive, move completed tasks to [history](docs/roadmap-history.md), retain concise outcomes, known limits and references, delete the corresponding `docs/tasks/<ID>.md` files and update incoming links.
- Check new issues for duplication and scope before assigning stable IDs; preserve priorities, record real dependencies, use `backlog` for unconfirmed work and `blocked` for a named obstacle, and keep implementation within the authorized scope.
