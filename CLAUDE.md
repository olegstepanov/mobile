# Project Guidelines

## Tooling

- **Package manager**: `uv` — always use `uv` for dependency management, virtual environments, and running scripts.
- **Type checker**: `ty` — run via `make typecheck`.
- **Linter & formatter**: `ruff` — run via `make lint` and `make format`.
- **Build targets**: maintain a `Makefile` with `test`, `typecheck`, `lint`, and `format` targets.

## Code Style

Build with Python 3.13 in mind. Channel Guido.

- Pay attention to the type system. Use type annotations everywhere. Prefer `X | Y` over `Union[X, Y]`, `list[X]` over `List[X]`.
- Prioritize simplicity and ease of understanding above all else.
- Stick to the Zen of Python:
  - Beautiful is better than ugly.
  - Explicit is better than implicit.
  - Simple is better than complex.
  - Complex is better than complicated.
  - Flat is better than nested.
  - Sparse is better than dense.
  - Readability counts.
  - Special cases aren't special enough to break the rules.
  - Although practicality beats purity.
  - Errors should never pass silently.
  - Unless explicitly silenced.
  - In the face of ambiguity, refuse the temptation to guess.
  - There should be one-- and preferably only one --obvious way to do it.
  - Now is better than never.
  - If the implementation is hard to explain, it's a bad idea.
  - If the implementation is easy to explain, it may be a good idea.
  - Namespaces are one honking great idea -- let's do more of those!
