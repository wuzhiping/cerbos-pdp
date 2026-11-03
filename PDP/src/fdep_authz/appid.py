"""The FDEP api id, and where each of its segments belongs.

An app id is `@<org-key>.<c4-path>.<operation>`:

    @jev.systemone.LAYA.Choice
     │    │            │        └──► operation = Choice
     │    │            └───────────► C4 path  = systemone.LAYA
     │    └────────────────────────► org      = jev
     └─────────────────────────────► the org's key in FDEP's org map

    @fdep.twseMops.todayMaterial
     │     │              └──► operation = todayMaterial
     │     └─────────────────► C4 path  = twseMops
     └──────────────────────► org      = fdep

**The last segment is the operation; everything before it is the C4 path.**
The C4 path is a folder path, so it may have several segments —
`systemone.LAYA` is the folder `systemone/LAYA`.

So the Cerbos resource is:

    kind   = namespace.task_queue.workflow      pip.JEV.LAYA
    id     = the C4 path                       systemone.LAYA
    action = the operation                     Choice
    attr   = { accessMode, riskLevel }

There is **no scope**: the provider is the kind, the app family inside it
is the id, and the operation is the action. One policy per provider covers
every app family that provider serves.

The `C4.` prefix that FDEP adds on the way to Temporal is not part of this
and never appears here: it is a server-side routing detail, and
authorization looks at the app the caller asked for.
"""

from __future__ import annotations

from dataclasses import dataclass


class InvalidApi(ValueError):
    """The api id is not of the shape `<c4-path>.<operation>`."""


@dataclass(frozen=True)
class AppId:
    """A parsed FDEP api id."""

    path: str
    operation: str
    org: str = ""

    @property
    def action(self) -> str:
        """The action: the operation's name — `Choice`.

        The plugin file is where the operation lives (`Choice.py`), but the
        **action is the operation's name**. The policy names the operation,
        and the file is an implementation detail of the plugin.
        """
        return self.operation

    @property
    def registry_key(self) -> str:
        """The key the app registry stores this family's control fields under.

        The registry is keyed by the C4 path, because that is what the risk
        level belongs to.
        """
        return self.path

    def __str__(self) -> str:
        prefix = f"@{self.org}." if self.org else ""
        return f"{prefix}{self.path}.{self.operation}"


def parse_api(api: str) -> AppId:
    """Parse `systemone.LAYA.Choice` into its C4 path and its operation.

    The last dot-separated segment is the operation; everything before it is
    the C4 path. An `@org.` prefix is tolerated and kept — it names the
    provider. The `C4.` prefix is not: it is added on the way to Temporal,
    and it is not part of what the caller asked for.
    """
    if not isinstance(api, str) or not api.strip():
        raise InvalidApi("the api id is empty")

    text = api.strip()
    org = ""
    if text.startswith("@"):
        body = text[1:]
        if "." not in body:
            raise InvalidApi(f"the api id must name an app and an operation: {api!r}")
        org, text = body.split(".", 1)

    if "." not in text:
        raise InvalidApi(f"the api id must name an app and an operation: {api!r}")

    path, operation = text.rsplit(".", 1)
    if not path or not operation:
        raise InvalidApi(f"the api id must name an app and an operation: {api!r}")

    return AppId(path=path, operation=operation, org=org)


__all__ = ["AppId", "InvalidApi", "parse_api"]
