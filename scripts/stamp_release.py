#!/usr/bin/env python3
"""Stamp the real server URL and repository coordinates into the plugin bundle.

The committed bundle ships with ``"url": ""`` in ``.mcp.json`` and without the
``homepage``, ``repository``, ``supportUrl``, ``privacyPolicyUrl``, and
``documentationUrl`` manifest fields, because no public endpoint or repository exists
yet. Run this once the hosted server has a stable HTTPS URL and the public GitHub
repository exists::

    python3 scripts/stamp_release.py \
        --server-url https://<host>/mcp \
        --repo-url https://github.com/<owner>/<repo> \
        [--support-url https://...] [--privacy-url https://...] [--docs-url https://...] \
        [--dry-run]

What it rewrites:

- ``.mcp.json``: ``mcpServers.nba-three-leg-parlays.url`` = ``--server-url``.
- ``.claude-plugin/plugin.json``: ``repository`` and ``homepage`` = ``--repo-url``
  (``homepage`` = ``--docs-url`` when given); ``supportUrl``, ``privacyPolicyUrl``,
  ``documentationUrl`` when the matching option is given.
- ``README.md``: every literal ``OWNER/REPO`` becomes ``<owner>/<repo>`` from ``--repo-url``.

Every URL must be ``https://`` and must not be a placeholder: example.com and friends,
localhost and loopback addresses, any host under the reserved top-level domains
``.test``, ``.example``, ``.invalid``, ``.localhost`` (RFC 2606) or ``.local``, TODO,
CHANGEME, angle brackets, and similar. The GitHub owner and repository names must not
be documentation placeholders such as ``example``, ``owner``, ``repo``, ``user``, or
``org``. Plain Python 3.12, standard library only.

Exit codes: 0 success, 1 validation failure, 2 usage error.
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path
from urllib.parse import urlsplit

PROJECT_ROOT = Path(__file__).resolve().parent.parent
DEFAULT_PLUGIN_DIR = PROJECT_ROOT / "plugin" / "nba-three-leg-parlays"
SERVER_KEY = "nba-three-leg-parlays"
README_REPO_TOKEN = "OWNER/REPO"

PLACEHOLDER_HOSTS = ("example.com", "example.org", "example.net", "localhost", "127.0.0.1", "0.0.0.0", "::1")
# Reserved top-level domains that can never name a public server: RFC 2606 (test, example,
# invalid, localhost) plus the mDNS-only .local (RFC 6762).
RESERVED_TLDS = ("test", "example", "invalid", "localhost", "local")
# Documentation placeholders that are not acceptable as a GitHub owner or repository name.
PLACEHOLDER_REPO_NAMES = frozenset(
    {"example", "owner", "repo", "user", "org", "username", "name", "acme", "foo", "bar", "baz"}
)
# A README sentence that would read as nonsense once the token is replaced (see D4 in
# docs/integration-notes/review-release.md); the script refuses to stamp over it.
README_INSTRUCTION_RE = re.compile(r"replace\s+`?OWNER/REPO`?", re.IGNORECASE)
PLACEHOLDER_FRAGMENTS = (
    "todo",
    "changeme",
    "change-me",
    "placeholder",
    "your-",
    "yourname",
    "<",
    ">",
    "{",
    "}",
    "xxx",
    "tbd",
)
GITHUB_REPO_RE = re.compile(
    r"^/(?P<owner>[A-Za-z0-9](?:[A-Za-z0-9-]*[A-Za-z0-9])?)/(?P<repo>[A-Za-z0-9._-]+?)(?:\.git)?/?$"
)


class StampError(ValueError):
    """A URL failed validation."""


def validate_https_url(value: str, *, label: str) -> str:
    """Return ``value`` when it is a non-placeholder absolute https URL, else raise ``StampError``."""
    text = value.strip()
    lowered = text.lower()
    parts = urlsplit(text)
    if parts.scheme != "https":
        raise StampError(f"{label} must start with https:// (got {text!r})")
    host = (parts.hostname or "").lower()
    if not parts.netloc or not host:
        raise StampError(f"{label} must have a real hostname (got {text!r})")
    if host in PLACEHOLDER_HOSTS or host.endswith(tuple("." + h for h in PLACEHOLDER_HOSTS)):
        raise StampError(f"{label} points at a placeholder host: {host}")
    if "." not in host:
        raise StampError(f"{label} must use a fully qualified hostname (got {host!r})")
    if host.rstrip(".").rsplit(".", 1)[-1] in RESERVED_TLDS:
        raise StampError(f"{label} points at a reserved top-level domain: {host}")
    if any(fragment in lowered for fragment in PLACEHOLDER_FRAGMENTS):
        raise StampError(f"{label} looks like a placeholder: {text!r}")
    if any(ch.isspace() for ch in text):
        raise StampError(f"{label} must not contain whitespace")
    return text


def parse_github_repo(repo_url: str) -> tuple[str, str]:
    """Return ``(owner, repo)`` from a ``https://github.com/<owner>/<repo>`` URL."""
    parts = urlsplit(repo_url)
    if (parts.hostname or "").lower() != "github.com":
        raise StampError(f"--repo-url must be on github.com (got {repo_url!r})")
    match = GITHUB_REPO_RE.match(parts.path)
    if not match:
        raise StampError(f"--repo-url must look like https://github.com/<owner>/<repo> (got {repo_url!r})")
    owner, repo = match.group("owner"), match.group("repo")
    for role, name in (("owner", owner), ("repository", repo)):
        if name.lower() in PLACEHOLDER_REPO_NAMES:
            raise StampError(f"--repo-url {role} name {name!r} is a documentation placeholder")
    return owner, repo


def load_json(path: Path) -> dict[str, object]:
    """Read a JSON object file."""
    data = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(data, dict):
        raise StampError(f"{path} must contain a JSON object")
    return data


def dump_json(data: dict[str, object]) -> str:
    """Serialise with two-space indentation and a trailing newline, matching the committed files."""
    return json.dumps(data, indent=2, ensure_ascii=False) + "\n"


def stamp(
    plugin_dir: Path,
    *,
    server_url: str,
    repo_url: str,
    support_url: str | None,
    privacy_url: str | None,
    docs_url: str | None,
    dry_run: bool,
) -> dict[str, str]:
    """Validate inputs, compute the new file contents, and write them unless ``dry_run``.

    Returns a map of relative file path to a one-line description of the change.
    """
    server_url = validate_https_url(server_url, label="--server-url")
    repo_url = validate_https_url(repo_url, label="--repo-url")
    owner, repo = parse_github_repo(repo_url)
    optional = {
        "supportUrl": validate_https_url(support_url, label="--support-url") if support_url else None,
        "privacyPolicyUrl": validate_https_url(privacy_url, label="--privacy-url") if privacy_url else None,
        "documentationUrl": validate_https_url(docs_url, label="--docs-url") if docs_url else None,
    }
    warnings: list[str] = []
    if not urlsplit(server_url).path.rstrip("/").endswith("/mcp"):
        warnings.append("server URL does not end with /mcp; the hosted server mounts Streamable HTTP at /mcp")

    mcp_path = plugin_dir / ".mcp.json"
    manifest_path = plugin_dir / ".claude-plugin" / "plugin.json"
    readme_path = plugin_dir / "README.md"
    changes: dict[str, str] = {}

    mcp = load_json(mcp_path)
    servers = mcp.get("mcpServers")
    if (
        not isinstance(servers, dict)
        or SERVER_KEY not in servers
        or not isinstance(servers[SERVER_KEY], dict)
    ):
        raise StampError(f".mcp.json must declare mcpServers.{SERVER_KEY}")
    entry = dict(servers[SERVER_KEY])
    entry["type"] = "http"
    entry["url"] = server_url
    servers[SERVER_KEY] = entry
    changes[".mcp.json"] = f"url -> {server_url}"

    manifest = load_json(manifest_path)
    manifest["repository"] = repo_url
    manifest["homepage"] = optional["documentationUrl"] or repo_url
    for key, value in optional.items():
        if value:
            manifest[key] = value
    changes[".claude-plugin/plugin.json"] = ", ".join(
        f"{k} -> {manifest[k]}" for k in ("repository", "homepage", *[k for k, v in optional.items() if v])
    )

    readme_text = readme_path.read_text(encoding="utf-8")
    if README_INSTRUCTION_RE.search(readme_text):
        raise StampError(
            "README.md tells the reader to replace OWNER/REPO; that sentence would become nonsense "
            "after stamping. Reword it so the line reads correctly with the real coordinates."
        )
    replaced = readme_text.count(README_REPO_TOKEN)
    if replaced == 0:
        warnings.append(f"README.md contains no {README_REPO_TOKEN} token; nothing to stamp there")
    new_readme = readme_text.replace(README_REPO_TOKEN, f"{owner}/{repo}")
    changes["README.md"] = f"{replaced} occurrence(s) of {README_REPO_TOKEN} -> {owner}/{repo}"

    for path, description in changes.items():
        print(f"{'would update' if dry_run else 'updating'} {path}: {description}")
    for warning in warnings:
        print(f"warning: {warning}")

    if not dry_run:
        mcp_path.write_text(dump_json(mcp), encoding="utf-8")
        manifest_path.write_text(dump_json(manifest), encoding="utf-8")
        readme_path.write_text(new_readme, encoding="utf-8")
    return changes


def main(argv: list[str] | None = None) -> int:
    """Command-line entry point."""
    parser = argparse.ArgumentParser(
        description="Stamp the server URL and repository into the plugin bundle."
    )
    parser.add_argument(
        "--server-url", required=True, help="public https URL of the MCP endpoint, ending in /mcp"
    )
    parser.add_argument("--repo-url", required=True, help="https://github.com/<owner>/<repo>")
    parser.add_argument("--support-url", help="https URL for support (plugin.json supportUrl)")
    parser.add_argument(
        "--privacy-url", help="https URL of the privacy policy (plugin.json privacyPolicyUrl)"
    )
    parser.add_argument(
        "--docs-url", help="https URL of the documentation (plugin.json documentationUrl and homepage)"
    )
    parser.add_argument("--plugin-dir", type=Path, default=DEFAULT_PLUGIN_DIR, help="plugin folder to stamp")
    parser.add_argument("--dry-run", action="store_true", help="print the changes, write nothing")
    args = parser.parse_args(argv)
    try:
        stamp(
            args.plugin_dir.resolve(),
            server_url=args.server_url,
            repo_url=args.repo_url,
            support_url=args.support_url,
            privacy_url=args.privacy_url,
            docs_url=args.docs_url,
            dry_run=args.dry_run,
        )
    except (StampError, FileNotFoundError, json.JSONDecodeError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
