"""Internal, dependency-ordered score layout implementation.

Import policies from their owning modules; :mod:`re_tomato.render.layout` is the
compatibility facade. Keeping this package initializer inert prevents unrelated layout
domains from becoming coupled through eager imports.
"""

__all__: list[str] = []
