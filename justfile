set positional-arguments

# Defaults to running `just --list --unsorted` if no recipe is specified.
default:
    @just --list --unsorted

build:
    cargo update
    uv sync
    uv run --no-sync maturin develop --release

check:
    uv run --no-sync ruff check --fix
    uv run --no-sync ty check --fix
    uv run --no-sync ruff format
    cargo clippy --locked --fix --allow-dirty -- -D warnings
    cargo fmt

test-rust *args:
    cargo test --locked "$@"

test-python *args:
    uv run --no-sync pytest "$@"

bench *args: build
    uv run --no-sync benchmarks/bench.py --multiday "$@"

docs-build *args:
    uv run --no-sync zensical build --clean --strict "$@"

docs-serve *args:
    uv run --no-sync zensical serve "$@"
