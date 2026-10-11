# typed-validator

Resolves a symlink chain and reports whether the target exists, is circular, or exceeds a max depth.

```python
from typed_validator import SymlinkValidator, SymlinkResult

v = SymlinkValidator(max_depth=40)
r: SymlinkResult = v.validate("/etc/alternatives/python")
print(r.status)  # "valid" | "missing" | "broken" | "circular" | "too_deep"
print(r.target)  # final resolved path (or the path where we gave up)
print(r.depth)  # number of symlink hops followed
```

## Why this exists

Walking a symlink chain by hand with `os.path.realpath` tells you where you
landed but not *why* you might have stopped short. A caller that needs to
tell a user "your config file is a dangling symlink" versus "your config
file is missing" versus "your config file is in a loop" has to re-derive
those cases every time. `typed-validator` does that one walk and returns a
labelled result.

The trade-off: this library reads the chain itself, one `os.readlink` at a
time, rather than delegating to `os.path.realpath`. That is slower on long
chains but gives exact depth accounting and lets us distinguish "broken"
from "missing". `realpath` would collapse both into a missing path and lose
the distinction.

## Edge you will hit

`os.path.exists` follows symlinks and returns `False` for a symlink whose
target is missing, which would conflate "broken symlink" with "missing
file". The implementation uses `os.path.lexists` for existence checks so a
symlink reads as present regardless of its target; only the explicit
non-symlink endpoint check uses ordinary existence to decide between `valid`
and `missing`/`broken`.

A second edge: the chain is walked with `max_depth` as a hard hop limit. A
chain that resolves on hop `max_depth` exactly is `valid`; a chain that
would need hop `max_depth + 1` is `too_deep`. There is no partial credit.

## Statuses

- `valid` — the chain reached an existing non-symlink.
- `missing` — the start path was not a symlink and did not exist.
- `broken` — an intermediate symlink pointed at a path that does not exist.
- `circular` — the chain re-visited a path already on the visited list.
- `too_deep` — the chain length exceeded `max_depth` before resolving.

## Exports

- `SymlinkValidator` — class; constructor takes `max_depth: int = 40`.
  Method `validate(path: str) -> SymlinkResult`.
- `SymlinkResult` — frozen dataclass with fields `start`, `target`,
  `status`, `depth`.

Zero third-party dependencies. Standard library only.
