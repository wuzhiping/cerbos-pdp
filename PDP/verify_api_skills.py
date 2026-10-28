"""Verify the rewritten skills against openapi-spec.json.

1. Every API path a skill cites must exist in the spec, or be one of the
   operational endpoints the PDP serves outside the OpenAPI document.
2. No CLI invocation may be presented as the way to do the job. A mention is
   allowed only inside a passage that marks the tool as unavailable, optional
   or out of scope.
"""

import json
import pathlib
import re
import sys

ROOT = pathlib.Path(__file__).resolve().parent
SKILLS = ROOT / ".dsh" / "skills"
SPEC = json.loads((ROOT / "openapi-spec.json").read_text(encoding="utf-8"))

OPERATIONAL = {"/_cerbos/health", "/_cerbos/metrics", "/schema/swagger.json"}


def normalise(path: str) -> str:
    return re.sub(r"\{[^}]+\}", "{}", path)


spec_templates = {normalise(p) for p in SPEC["paths"]}

PATH_RE = re.compile(r"(/(?:admin|api|_cerbos|schema)/[A-Za-z0-9_{}/.\-]+)")
CLI_RE = re.compile(
    r"\b(cerbos\s+(?:compile|test|server|repl)\b|cerbosctl\b|docker\s+run\b|ghcr\.io/cerbos)"
)

ALLOWED_CONTEXT = (
    "no cerbos binary",
    "no `cerbosctl`",
    "no docker",
    "outside the api-only workflow",
    "needs `cerbosctl`",
    "cerbos binary *is* available",
    "binary is available",
    "optional",
    "not available",
    "hub store",
    "the `cerbos` binary",
    "cli reference",
    "install `cerbosctl`",
    "testcontainers",
    "out of scope",
    # Chinese phrasing that marks the tool as unavailable / out of scope
    "不需要",
    "无需",
    "不用",
    "不属于",
    "不在本流程范围内",
    "没有",
)


def matches_spec(cited: str) -> bool:
    key = normalise(cited)
    if key in spec_templates:
        return True
    for template in spec_templates:
        if "{}" not in template:
            continue
        head = template.split("{}")[0]
        if cited.startswith(head) and len(cited) > len(head):
            return True
    return False


problems = []
cli_hits = []
cited = {}
chinese = {}

for skill in sorted(SKILLS.iterdir()):
    if not skill.is_dir():
        continue
    for md in sorted(skill.rglob("*.md")):
        text = md.read_text(encoding="utf-8")
        rel = md.relative_to(ROOT)
        lines = text.splitlines()

        han = sum(1 for ch in text if "\u4e00" <= ch <= "\u9fff")
        chinese[str(rel)] = han

        for raw in set(PATH_RE.findall(text)):
            path = raw.split("?")[0].rstrip(".,;:)")
            for occurrence in re.finditer(re.escape(raw), text):
                window = text[max(0, occurrence.start() - 100) : occurrence.end() + 100]
                if any(h in window for h in ("docs.cerbos.dev", "github.com", "hub.cerbos.cloud")):
                    continue
                cited.setdefault(path, set()).add(str(rel))
                if path not in OPERATIONAL and not matches_spec(path):
                    problems.append(f"UNKNOWN ENDPOINT  {path}   (cited in {rel})")

        for i, line in enumerate(lines, 1):
            for hit in CLI_RE.finditer(line):
                window = "\n".join(lines[max(0, i - 5) : i + 4]).lower()
                if not any(phrase in window for phrase in ALLOWED_CONTEXT):
                    cli_hits.append(f"{rel}:{i}: {hit.group(0)}   |  {line.strip()[:100]}")

print("=== endpoints cited ===")
for path in sorted(cited):
    mark = "OK " if path in OPERATIONAL or matches_spec(path) else "BAD"
    print(f"  {mark} {path}")

print("\n=== unknown endpoints ===")
print("\n".join("  " + p for p in problems) if problems else "  none")

print("\n=== CLI presented as the way to do the job ===")
print("\n".join("  " + c for c in cli_hits) if cli_hits else "  none")

print("\n=== Chinese coverage per file (CJK chars) ===")
for rel in sorted(chinese):
    if chinese[rel]:
        print(f"  {rel:<62} {chinese[rel]:>5}")

sys.exit(1 if problems or cli_hits else 0)
