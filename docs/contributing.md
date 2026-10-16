# Contributing to PyGNSS-TEC

This project welcomes contributions from the community. Whether you want to report bugs, suggest new features, improve documentation, or contribute code, your input is valuable.

Thanks for your interest in contributing! Please read the following guidelines to ensure a smooth contribution process.

## Development

Source builds require Python 3.12 or later, Rust 1.88 or later with Cargo, and [uv](https://docs.astral.sh/uv/).
Get started with cloning the repository and syncing the editable Python/Rust package:

```bash
git clone https://github.com/Eureka-0/pygnss-tec.git
cd pygnss-tec
uv sync
```

The project uses a maturin build backend.
Syncing the project builds its rust core and places it in `gnss_tec/_core.abi3.so` automatically.
You can also manually build the shared library with:

```bash
uv run --no-sync maturin develop --release
```

Before making changes, make sure to create your own branch from `main` and keep it up to date with the latest changes:

```bash
git checkout -b my-feature-branch
git pull origin main
```

Then, make your changes, format and test them, commit them with clear messages, and push your branch to the repository.
Finally, open a pull request to propose your changes for review and merging into the main branch.

## Common commands

You can install [just](https://github.com/casey/just) to use the command recipes.
Otherwise, you can run the commands directly from the repository root.
The [justfile](https://github.com/Eureka-0/pygnss-tec/blob/main/justfile) is the command reference.

| Command | Purpose |
|---|---|
| `just build` | Update Cargo dependencies, sync the Python environment and build the release extension. |
| `just check` | Apply Ruff, ty, Clippy and formatting fixes. |
| `just test-python` | Run Python tests; append pytest arguments to select cases. |
| `just test-rust` | Run Rust tests with the lockfile. |
| `just bench` | Build the release extension, then generate the canonical single-/two-day benchmark report. |
| `just docs-build` | Build the documentation with strict validation and a clean cache. |
| `just docs-serve` | Preview the documentation locally. |

`uv sync` uses the editable build backend and may reuse an installed extension instead of rebuilding after Rust source changes.
The benchmark recipe depends on `build`, so dependency updates, environment synchronization and release compilation finish before measurement.

## Roadmap and task workflow

The project follows a roadmap-based approach to manage development tasks and feature implementation.
The roadmap is maintained in the `ROADMAP.md` file, and tasks are tracked in the `docs/tasks/` directory.
General roadmap conventions are described in `AGENTS.md`, and it is recommended to use AI agents to assist with task management and implementation planning.

## Code style

This project uses [Ruff](https://github.com/astral-sh/ruff) for Python code formatting and linting, [ty](https://github.com/astral-sh/ty) for Python type checking, and [Clippy](https://github.com/rust-lang/rust-clippy) for Rust code analysis.
Please run `just check` before committing your changes to ensure that your code adheres to the project's style guidelines.

Other style conventions:

- **Branch naming**: Use descriptive names for your branches, such as `feature/your-feature-name` or `fix/your-fix-name`.
- **Docstrings**: Use NumPy-style `Parameters`, `Returns`/`Yields`, `Raises` and `Attributes` sections.
- **Comments**: Write clear and concise comments to explain the purpose of your code, especially for complex logic.

## Testing and validation

When making changes, it is important to run tests and validate your code to ensure that it works as expected and does not introduce regressions.
This project uses [pytest](https://github.com/pytest-dev/pytest) for Python tests and the built-in Rust test framework for Rust code.

Before submitting a pull request, please run the following commands to ensure that all tests pass:

```bash
just test-rust
just test-python
```

For documentation changes, build and review the site and run the affected examples.
Check generated API pages when changing docstrings or public exports.

## Documentation build and preview

The documentation is built with [Zensical](https://github.com/zensical/zensical) and is available in the `docs/` directory.
You can build and preview the documentation locally with the following commands:

```bash
just docs-serve
just docs-build
```

The strict build writes the static site to `site/`.
Generated site output and caches are ignored by Git.

Navigation, API rendering and publication settings live in `zensical.toml`.
Write mathematical expressions in LaTeX using `$...$` inline or `$$...$$` on separate lines for display equations.
Arithmatex prepares these expressions for MathJax, configured in `docs/assets/javascripts/mathjax.js`.

## Bug reports

If you encounter any bugs or issues while using PyGNSS-TEC, please report them by opening an issue on the [GitHub repository](https://github.com/Eureka-0/pygnss-tec/issues).
When reporting a bug, please provide as much detail as possible, including:

- A clear and descriptive title for the issue.
- The version of PyGNSS-TEC you are using.
- A detailed description of the problem, including steps to reproduce it.
- Any relevant error messages or stack traces.
- Data files or code snippets that can help reproduce the issue, if applicable.

## Feature requests

If you have ideas for new features or improvements to PyGNSS-TEC, please submit a feature request by opening an issue on the [GitHub repository](https://github.com/Eureka-0/pygnss-tec/issues).
When submitting a feature request, please provide a clear and detailed description of the proposed feature, including:

- The problem or use case that the feature would address.
- A description of the proposed solution or enhancement.
- Any relevant examples or references that can help illustrate the feature.
