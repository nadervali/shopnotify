"""Merge-tag templating for notification messages.

Templates are plain text with ``{{tag}}`` placeholders::

    Hi {{name}}, your order {{order_id}} is ready for pickup.

Rendering is strict: a tag with no value (or an empty one) raises
``MissingValueError`` naming every missing tag, so a half-personalised
message — "Hi , your order is ready" — never reaches a customer.
Values the template does not use are ignored, and a ``defaults``
mapping can supply fallbacks for optional tags.
"""

import re

_TAG_RE = re.compile(r"\{\{\s*([A-Za-z0-9_]+)\s*\}\}")


class MissingValueError(ValueError):
    """Raised when a template references tags that have no value."""

    def __init__(self, missing: list[str]):
        self.missing = sorted(set(missing))
        super().__init__(
            "no value for template tag(s): " + ", ".join(self.missing))


def find_tags(template: str) -> list[str]:
    """Tags referenced by ``template``, in order of first appearance."""
    seen: list[str] = []
    for match in _TAG_RE.finditer(template):
        tag = match.group(1)
        if tag not in seen:
            seen.append(tag)
    return seen


def render(template: str, values: dict,
           defaults: dict | None = None) -> str:
    """Render ``template`` with ``values`` (plus optional ``defaults``).

    A tag counts as missing when its value is absent, ``None`` or an
    empty string — an empty CSV cell must not produce a message with a
    hole in it.
    """
    merged = {**(defaults or {}), **values}
    missing = [tag for tag in find_tags(template)
               if merged.get(tag) is None or merged.get(tag) == ""]
    if missing:
        raise MissingValueError(missing)
    return _TAG_RE.sub(lambda m: str(merged[m.group(1)]), template)
