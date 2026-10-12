# AGENTS.md

## Project Overview

This project, `PyGNSS-TEC`, is a Python package designed for processing and analyzing Total Electron Content (TEC) data from Global Navigation Satellite System (GNSS) observations. It is a hybrid Python and Rust project, with the performance-intensive RINEX file parsing implemented in Rust and exposed to Python using `pyo3` and `maturin`.

The core functionalities of the library include:
- Reading RINEX observation and navigation files (versions 2.x and 3.x), including Hatanaka compressed files.
- Calculating Slant and Vertical Total Electron Content (STEC and VTEC).
- Correcting for satellite and receiver differential code biases (DCBs).
- Supporting multiple GNSS constellations.

The library uses the [Polars](https://pola.rs/) DataFrame library for efficient data manipulation.

## Building and Running

### Dependencies

- Python >= 3.12
- Rust
- `uv` (recommended for Python environment management)

### Building the project

1.  Clone the repository:
    ```bash
    git clone https://github.com/Eureka-0/pygnss-tec.git
    cd pygnss-tec
    ```

2.  Build the project using `maturin`:
    ```bash
    uv run --with maturin maturin build --release
    ```
    The compiled wheel will be in the `target/wheels` directory.

### Running tests

The project uses `pytest` for testing. To run the tests, execute the following command from the root of the project:

```bash
uv run pytest
```

## Development Conventions

Use `uv` for Python environments/scripts and prefix shell commands with `rtk` (`rtk proxy` for unsupported commands).

- **Linting**: The project uses `ruff` for Python code linting.
- **Code Formatting**: The project uses `ruff` to format the Python code.

You can run the linter and formatter with the following commands:

```bash
# Lint
uv run ruff check .

# Format
uv run ruff format .
```

- **Rust**: The Rust code follows standard Rust conventions and is formatted using `cargo fmt`.
- **Testing**: Tests are located in the `tests` directory and use `pytest`. The tests cover both the Python and the Rust parts of the library.
- **Commits**: There are no explicit commit message conventions mentioned, but the commit history shows a preference for descriptive and concise messages.

## Roadmap Workflow

- Read [ROADMAP.md](ROADMAP.md) and relevant task files for a requested Roadmap task. Reading does not authorize execution; ordinary development requests need not become Roadmap tasks.
- When authorized to advance unspecified work, select from Current Focus, then user-approved plans, then high-priority `ready` tasks with satisfied dependencies. IDs, workstreams and milestones do not prescribe execution order.
- Check the actual repository before implementation. For complex work, update the reviewable Implementation Plan and honor required human review before dependent changes.
- Maintain concise Progress & Handoff notes with implemented work, acceptance progress, open issues, next action and constraints. Keep priority/status/dependencies only in the authoritative Roadmap or archive record.
- Verify all Acceptance Criteria and evidence before `done`; passing tests alone may not suffice. Update the index, task file and affected docs; follow Active Tasks → Recently Completed → [History Archive](docs/roadmap-history.md), keeping concise completion records.
- Check new findings for duplication and scope before assigning stable IDs. Preserve priorities, record real dependencies, use `backlog` for unconfirmed work and `blocked` only for a named obstacle; new records do not authorize extra implementation.
