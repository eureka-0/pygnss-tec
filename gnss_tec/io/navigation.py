"""Load broadcast navigation into reusable native propagation records."""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass, field
from pathlib import Path

from .._core import _NavigationData, _read_nav
from .rinex import ALL_CONSTELLATIONS, _handle_fn


@dataclass(frozen=True, slots=True)
class NavigationData:
    """Read-only broadcast ephemerides owned by Rust.

    Create instances with `read_rinex_nav`. Reusing an instance shares its
    native records and indexes without rereading the source files. This is
    an in-process geometry dataset, not a lossless navigation-file editor.
    SBAS records can be read, but their propagation is not implemented.
    """

    _handle: _NavigationData = field(repr=False)

    @property
    def sources(self) -> tuple[str, ...]:
        """Sorted source paths, independent of subsequent file changes."""
        return tuple(self._handle.sources)

    @property
    def satellites(self) -> tuple[str, ...]:
        """Sorted satellite identifiers with retained ephemerides."""
        return tuple(self._handle.satellites)

    @property
    def constellations(self) -> str:
        """Sorted one-letter constellation codes present in the dataset."""
        return self._handle.constellations

    @property
    def n_ephemerides(self) -> int:
        """Number of distinct per-satellite reference epochs."""
        return self._handle.n_ephemerides

    @property
    def epoch_range(self) -> tuple[int, int] | None:
        """First/last reference epochs as UTC Unix nanoseconds, not validity bounds."""
        return self._handle.epoch_range

    def __repr__(self) -> str:
        return (
            f"NavigationData(constellations={self.constellations!r}, "
            f"satellites={len(self.satellites)}, n_ephemerides={self.n_ephemerides})"
        )


def read_rinex_nav(
    nav_fn: str | Path | Iterable[str | Path], *, constellations: str | None = None
) -> NavigationData:
    """Read RINEX 2/3 broadcast navigation for repeated geometry calculations.

    Parameters
    ----------
    nav_fn : str, Path, or iterable of str or Path
        Navigation files, optionally gzip compressed. Files are merged in
        sorted path order before indexing.
    constellations : str or None, default None
        One-letter GNSS codes to retain; None retains all parsed constellations.

    Returns
    -------
    NavigationData
        Immutable native records and per-satellite indexes. Reading completes
        before return. No per-record Python objects or DataFrame are created.

    Raises
    ------
    FileNotFoundError
        If a source file does not exist.
    OSError
        If a file cannot be decoded.
    ValueError
        If paths or constellation codes are invalid, files cannot be merged,
        or an input is not RINEX 2/3 navigation.
    """
    if constellations is not None and (
        not constellations or any(c not in ALL_CONSTELLATIONS for c in constellations)
    ):
        raise ValueError("constellations must contain one-letter GNSS codes GCERJIS.")
    paths = sorted(str(Path(p).resolve()) for p in _handle_fn(nav_fn))
    if not paths:
        raise ValueError("No RINEX file paths provided")
    return NavigationData(_read_nav(paths, constellations))
