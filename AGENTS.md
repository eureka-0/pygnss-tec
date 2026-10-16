# AGENTS.md

## Project Overview

This project is a Python package designed for calculating and processing Total Electron Content (TEC) data from GNSS observations.

## Commands

See [justfile](justfile) for common project commands.

## Development Conventions

- **Agent-generated documentation**: Unless explicitly specified otherwise, save agent-generated documents and helper files in `./docs/agents/`.

- **Docstrings**: Use NumPy-style `Parameters`, `Returns`/`Yields`, `Raises` and `Attributes` sections where applicable.

- **Markdown**: Write one sentence per line without hard-wrapping sentences to a fixed width.

- **README**: Do not modify the README.md file directly unless you are asked to do so or the changes are update to the original content.

## Roadmap Workflow

- Read [ROADMAP.md](ROADMAP.md) and relevant task files for a requested Roadmap task. Reading does not authorize execution; ordinary development requests need not become Roadmap tasks.
- When authorized to advance unspecified work, select from Current Focus, then user-approved plans, then high-priority `ready` tasks with satisfied dependencies. IDs, workstreams and milestones do not prescribe execution order.
- Check the actual repository before implementation. For complex work, update the reviewable Implementation Plan and honor required human review before dependent changes.
- Maintain concise Progress & Handoff notes with implemented work, acceptance progress, open issues, next action and constraints. Keep priority/status/dependencies only in the authoritative Roadmap or archive record.
- Verify all Acceptance Criteria and evidence before `done`; passing tests alone may not suffice. Update the index, task file and affected docs; follow Active Tasks → Recently Completed → [History Archive](docs/roadmap-history.md), keeping concise completion records.
- Check new findings for duplication and scope before assigning stable IDs. Preserve priorities, record real dependencies, use `backlog` for unconfirmed work and `blocked` only for a named obstacle; new records do not authorize extra implementation.
