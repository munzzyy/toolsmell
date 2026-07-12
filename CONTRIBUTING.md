# Contributing

Thanks for looking at this. It's a small, single-purpose tool and
contributions are welcome.

## Setup

```
git clone https://github.com/munzzyy/toolsmell
cd toolsmell
```

There's nothing to install. toolsmell is pure standard library, and so is
its test suite.

## Running the tests

```
python -m unittest discover -s tests -t .
```

or, if you have pytest:

```
pytest
```

That's the whole suite: unit tests per rule, engine tests, and a labeled
corpus in `tests/corpus/`. CI runs both across Linux, macOS, and Windows on
several Python versions.

## Adding or fixing a rule

Every rule lives in `toolsmell/catalog.py` (id, severity, title, general
explanation, generic fix) and is implemented in one of the modules under
`toolsmell/rules/`. Every rule change lands with a fixture, so coverage only
goes up:

- A real smell slipped through? Add a manifest under `tests/corpus/smelly/`.
  The corpus test asserts it scores at or above the recall floor.
- A false positive? Add a manifest under `tests/corpus/clean/`. The corpus
  test asserts it stays under the floor.
- New rule id: add it to `toolsmell/catalog.py`, wire the check into the
  right module under `toolsmell/rules/`, and add a `## TS-0NN` section to
  `docs/rules.md`. `tests/test_docs.py` fails the build if the two drift.

If you fix a bug with no fixture attached, it can silently come back. A
fixture is how the fix stays fixed.

Keep rules specific. A pattern that fires on ordinary, well-written
descriptions is worse than one that misses an edge case, because noise
trains people to ignore the tool.

## Zero dependencies

toolsmell has no runtime dependencies and that's a feature. If a change
needs a new package, that's a reason to reconsider the change, not a to-do.

## License

Contributions come in under the [Blue Oak Model License 1.0.0](https://blueoakcouncil.org/license/1.0.0).
By opening a PR you agree your contribution is offered on those terms.
