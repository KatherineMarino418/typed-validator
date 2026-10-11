"""Resolve a symlink chain and report whether the target exists.

The validator walks from a path that may itself be a symlink, following the
chain link-by-link using os.readlink / os.path.exists, up to a caller-defined
maximum depth. It classifies the result into exactly one of:

    * "valid"       — the chain reached a non-symlink that exists
    * "missing"     — the chain reached a non-symlink that does not exist
    * "broken"     — an intermediate link in the chain points at a missing file
    * "circular"   — following the chain re-visited a path already seen
    * "too_deep"   — the chain length exceeded max_depth before resolving

One deliberate decision worth calling out: "broken" and "missing" are
separate outcomes. If the *start* path is not a symlink and is gone, the
result is "missing". If the start *is* a symlink and a later link in the
chain vanishes, the result is "broken". This distinction is useful when
reporting errors back to a user — "the configuration file is missing" versus
"the configuration file is a dangling symlink" are different support tickets.
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from typing import Optional


@dataclass(frozen=True)
class SymlinkResult:
    """The outcome of resolving one symlink chain.

    Attributes:
        start:  The path the caller asked us to resolve (normalised via
                os.path.abspath, so relative inputs are comparable to the
                internal chain).
        target: The final path the chain landed on. For "circular" and
                "too_deep" outcomes this is the path where we gave up, which
                is *not* a resolved final target — callers must check
                ``status`` before trusting it.
        status: One of valid | missing | broken | circular | too_deep.
        depth:  Number of symlink hops actually followed. Zero means the
                start path was not a symlink at all.
    """

    start: str
    target: str
    status: str
    depth: int


class SymlinkValidator:
    """Resolve and classify a single symlink chain.

    Args:
        max_depth: Maximum number of symlink hops permitted before the chain
            is declared "too_deep". Must be at least 1. A typical filesystem
            enforces limits in the low tens (Linux ELOOP fires at ~40); we
            default to 40 to match that ballpark while still catching runaway
            or malicious chains.

    Note:
        All existence checks use os.path.lexists rather than os.path.exists.
        os.path.exists follows symlinks and returns False for a symlink whose
        target is missing, which would prevent us from distinguishing a broken
        link from a missing file. lexists reports True for a symlink
        regardless of its target, which is exactly the property we need when
        walking the chain one link at a time.
    """

    def __init__(self, max_depth: int = 40) -> None:
        if max_depth < 1:
            raise ValueError("max_depth must be >= 1")
        self.max_depth = max_depth

    def validate(self, path: str) -> SymlinkResult:
        """Resolve ``path`` and return a :class:`SymlinkResult`.

        The start path is normalised with os.path.abspath so that the
        ``start`` field of the result is comparable to the internal chain
        and survives round-trips through symlinks that use relative targets.
        """
        current = os.path.abspath(path)
        return self._resolve(current)

    def _resolve(self, start: str) -> SymlinkResult:
        current = start
        seen: list[str] = []
        depth = 0

        while True:
            is_link = os.path.islink(current)

            if not is_link:
                # Non-symlink endpoint. If it exists the chain is valid;
                # otherwise it is either genuinely missing (depth == 0,
                # i.e. the caller's input never existed) or broken (depth > 0,
                # i.e. a symlink led us here).
                if os.path.lexists(current):
                    status = "valid"
                else:
                    status = "missing" if depth == 0 else "broken"
                return SymlinkResult(start=start, target=current,
                                     status=status, depth=depth)

            # We are about to follow a symlink. Check for circular references
            # *before* moving on, using exact-path membership of the chain.
            # Path comparison is done on abspath-normalised values, which is
            # sound for this purpose because every value placed in ``seen``
            # is itself abspath-normalised (either the start, or produced by
            # os.path.join + os.path.abspath below).
            if current in seen:
                return SymlinkResult(start=start, target=current,
                                     status="circular", depth=depth)
            seen.append(current)

            if depth >= self.max_depth:
                return SymlinkResult(start=start, target=current,
                                     status="too_deep", depth=depth)

            # os.readlink returns the raw target as stored in the link — it may
            # be relative. Joining to the link's directory and normalising with
            # abspath yields the canonical next path to inspect.
            raw_target = os.readlink(current)
            next_path = os.path.abspath(os.path.join(os.path.dirname(current),
                                                     raw_target))

            # If the *next* path does not even exist at the filesystem level
            # (not a symlink, not a file, not a directory) we can short-circuit
            # to "broken" without consuming another hop. This is important for
            # depth accounting: a chain of N links whose (N+1)th target is
            # missing should report depth N, not N+1.
            if not os.path.lexists(next_path):
                return SymlinkResult(start=start, target=next_path,
                                     status="broken", depth=depth + 1)

            # If the next path is one we have already visited, we are about
            # to enter a cycle. Detect this *after* consuming the hop so that
            # self-referential links report depth 1 (one hop attempted) rather
            # than depth 0 (which would be indistinguishable from a non-symlink
            # input that never existed).
            if next_path in seen:
                return SymlinkResult(start=start, target=next_path,
                                     status="circular", depth=depth + 1)

            current = next_path
            depth += 1


def resolve(path: str, max_depth: int = 40) -> SymlinkResult:
    """Convenience wrapper: build a validator and validate ``path``.

    Kept as a module-level function for callers who do not want to hold a
    validator instance. The instance is cheap to construct, so this is purely
    ergonomic.
    """
    return SymlinkValidator(max_depth=max_depth).validate(path)


__all__ = ["SymlinkValidator", "SymlinkResult", "resolve"]
