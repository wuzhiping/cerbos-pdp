"""The app registry: the control fields of each FDEP app.

The two fields a policy reads come from FDEP's own data, never from the
caller:

    accessMode  read | execute    (actually derived from the `do` flag —
                                  see `token.access_mode`)
    riskLevel   low | medium | high

The registry is keyed by the **kind** — the folder the plugin lives in,
`systemone.LAYA` — because that is what the risk level belongs to.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Mapping

RISK_LEVELS = ("low", "medium", "high")


class UnknownApp(LookupError):
    """The api id names a kind the registry does not know.

    This is the caller's error: the app does not exist, so there is nothing
    to call and nothing to authorize.
    """


class InvalidRegistryEntry(RuntimeError):
    """The registry has the kind but its control fields are unusable.

    This is FDEP's error, not the caller's: the server's own data is
    incomplete, so the call cannot be judged. Answering 403 here would
    blame the caller for a gap on our side.
    """


@dataclass(frozen=True)
class AppRegistry:
    """The control fields of every FDEP app kind, keyed by the kind."""

    entries: Mapping[str, Mapping[str, Any]]
    default_risk_level: str | None = None

    @classmethod
    def from_mapping(
        cls,
        entries: Mapping[str, Mapping[str, Any]],
        *,
        default_risk_level: str | None = None,
    ) -> "AppRegistry":
        return cls(
            entries=dict(entries), default_risk_level=default_risk_level
        )

    def __contains__(self, key: str) -> bool:
        return key in self.entries

    def require(self, path: str) -> None:
        """Raise UnknownApp when the app is not registered.

        The registry is the list of apps FDEP serves, so an app id that
        names nothing is the caller's mistake — there is nothing to call
        and nothing to authorize.

        The risk level is **not** consulted here: while the attributes are
        switched off, nothing reads it. The default risk level still means
        "this registry accepts anything", which is what the placeholder
        registry says.
        """
        if path in self.entries:
            return
        if self.default_risk_level is None:
            raise UnknownApp(f"the app registry has no entry for {path!r}")

    def risk_level(self, kind: str) -> str:
        """The risk level of one app kind.

        Raises UnknownApp when the kind is not registered and there is no
        default, and InvalidRegistryEntry when it is registered but carries
        no usable risk level. The two are different failures and they get
        different answers: one is the caller's fault, the other is ours.
        """
        entry = self.entries.get(kind)

        if entry is None:
            if self.default_risk_level is None:
                raise UnknownApp(f"the app registry has no entry for {kind!r}")
            return self.default_risk_level

        risk = entry.get("riskLevel")
        if risk not in RISK_LEVELS:
            raise InvalidRegistryEntry(
                f"the app registry entry for {kind!r} has riskLevel={risk!r}, "
                f"which is not one of {RISK_LEVELS}"
            )
        return str(risk)


__all__ = [
    "AppRegistry",
    "InvalidRegistryEntry",
    "RISK_LEVELS",
    "UnknownApp",
]
