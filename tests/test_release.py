"""Release-module checks: plugin bundle structure, skill frontmatter, reference paths, README length,
the ZIP builder, and the release stamping script. No network, no ledger, no server imports.

Created by the release module (ownership: plugin/**, scripts/build_plugin_zip.py, scripts/stamp_release.py,
deploy/**, docs/*.md, root README/CLAUDE.md/.env.example/CHANGELOG.md).
"""

from __future__ import annotations

import importlib.util
import json
import re
import shutil
import sys
import zipfile
from pathlib import Path
from types import ModuleType

import pytest

PROJECT_ROOT = Path(__file__).resolve().parent.parent
PLUGIN_DIR = PROJECT_ROOT / "plugin" / "nba-three-leg-parlays"
SKILL_DIR = PLUGIN_DIR / "skills" / "nba-three-leg-parlays"
SCRIPTS = PROJECT_ROOT / "scripts"
DOCS = PROJECT_ROOT / "docs"

EXPECTED_DESCRIPTION = (
    "Research exactly three-leg NBA parlays on Hard Rock Bet Florida with current odds, injury context, "
    "correlation checks, and tracking of user-confirmed wagers. Includes a configurable daily budget, initially $10."
)
TOOL_NAMES = [
    "get_system_status",
    "check_data_coverage",
    "get_nba_slate",
    "get_injury_context",
    "analyze_leg",
    "build_three_leg_parlays",
    "analyze_my_parlay",
    "check_parlay_correlation",
    "import_hardrock_quote",
    "refresh_parlay",
    "select_ticket",
    "release_reservation",
    "get_daily_budget",
    "record_actual_bet",
    "reconcile_settlement",
    "get_performance",
    "generate_30_day_review",
    "set_user_settings",
    "add_cost",
    "export_my_data",
]
BANNED_PHRASES = ("risk-free", "guaranteed win", "sure thing", "can't lose", "cannot lose")
DASHES = (chr(0x2014), chr(0x2013))  # em dash, en dash


def _load_script(name: str) -> ModuleType:
    spec = importlib.util.spec_from_file_location(name, SCRIPTS / f"{name}.py")
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module  # dataclasses resolve postponed annotations through sys.modules
    spec.loader.exec_module(module)
    return module


def _frontmatter(text: str) -> dict[str, str]:
    """Parse the simple ``key: value`` YAML frontmatter without a YAML library (pyyaml is not a dependency)."""
    assert text.startswith("---\n"), "SKILL.md must start with a frontmatter block"
    end = text.index("\n---\n", 4)
    block = text[4:end]
    fields: dict[str, str] = {}
    for line in block.splitlines():
        assert re.match(r"^[a-z][a-z-]*: \S", line), f"unexpected frontmatter line: {line!r}"
        key, _, value = line.partition(": ")
        fields[key] = value.strip()
    return fields


def _words_outside_code_blocks(markdown: str) -> int:
    in_code = False
    count = 0
    for line in markdown.splitlines():
        if line.strip().startswith("```"):
            in_code = not in_code
            continue
        if not in_code:
            count += len(line.split())
    return count


# --------------------------------------------------------------------------------------
# Bundle layout and manifest
# --------------------------------------------------------------------------------------


def test_manifest_fields_exact() -> None:
    manifest = json.loads((PLUGIN_DIR / ".claude-plugin" / "plugin.json").read_text(encoding="utf-8"))
    assert manifest["name"] == "nba-three-leg-parlays"
    assert manifest["displayName"] == "NBA Three-Leg Parlay Analyst"
    assert manifest["version"] == "0.1.0"
    assert manifest["description"] == EXPECTED_DESCRIPTION
    assert manifest["author"] == {"name": "Noel Fernandez"}
    assert manifest["license"] == "MIT"
    assert isinstance(manifest["keywords"], list) and manifest["keywords"]
    for absent in ("homepage", "repository", "supportUrl", "privacyPolicyUrl", "documentationUrl", "icon"):
        assert absent not in manifest, f"{absent} must be stamped later by scripts/stamp_release.py"
    assert re.fullmatch(r"[a-z0-9](?:[a-z0-9-]{0,62}[a-z0-9])?", manifest["name"])
    assert not manifest["name"].startswith(("claude-", "anthropic-", "anthropics-", "cc-plugin-"))


def test_only_manifest_inside_claude_plugin_dir() -> None:
    names = sorted(p.name for p in (PLUGIN_DIR / ".claude-plugin").iterdir())
    assert names == ["plugin.json"]


def test_mcp_json_http_entry_with_empty_url() -> None:
    mcp = json.loads((PLUGIN_DIR / ".mcp.json").read_text(encoding="utf-8"))
    assert list(mcp) == ["mcpServers"]
    entry = mcp["mcpServers"]["nba-three-leg-parlays"]
    assert entry == {"type": "http", "url": ""}


def test_required_files_and_forbidden_files() -> None:
    for required in ("README.md", "LICENSE", "CHANGELOG.md", ".mcp.json"):
        assert (PLUGIN_DIR / required).is_file(), required
    for forbidden in ("bin", "CLAUDE.md", "uv.lock", "package-lock.json", ".DS_Store", "__MACOSX"):
        assert not (PLUGIN_DIR / forbidden).exists(), forbidden
    for path in PLUGIN_DIR.rglob("*"):
        if path.is_file():
            assert path.name not in (".DS_Store", "Thumbs.db"), path
            assert path.stat().st_size <= 256 * 1024, f"{path} exceeds 256 KiB"
            assert path.suffix in (".md", ".json", "") or path.name == "LICENSE", (
                f"unexpected file type: {path}"
            )


def test_license_is_mit_for_noel_fernandez() -> None:
    text = (PLUGIN_DIR / "LICENSE").read_text(encoding="utf-8")
    assert text.startswith("MIT License")
    assert "Copyright (c) 2026 Noel Fernandez" in text


def test_plugin_readme_word_count_and_content() -> None:
    readme = (PLUGIN_DIR / "README.md").read_text(encoding="utf-8")
    assert _words_outside_code_blocks(readme) > 40 * 5, (
        "README must be well over 40 words outside code blocks"
    )
    for phrase in ("never", "1-833-PLAYWISE", "21", "AI", "Upload plugin", "not yet submitted", "OWNER/REPO"):
        assert phrase in readme, phrase
    # The token is stamped verbatim; a sentence telling the reader to replace it would read as
    # nonsense in the shipped README (review-release.md D4), and stamp_release.py refuses it.
    assert not re.search(r"replace\s+`?OWNER/REPO`?", readme, re.IGNORECASE)


# --------------------------------------------------------------------------------------
# Skill
# --------------------------------------------------------------------------------------


def test_skill_frontmatter_spec_only_fields() -> None:
    text = (SKILL_DIR / "SKILL.md").read_text(encoding="utf-8")
    fields = _frontmatter(text)
    assert set(fields) == {"name", "description", "license"}
    assert fields["name"] == SKILL_DIR.name == "nba-three-leg-parlays"
    assert 0 < len(fields["description"]) <= 1024
    assert fields["license"] == "MIT"
    body = text[text.index("\n---\n", 4) + 5 :]
    assert len(body.splitlines()) < 400


def test_skill_names_every_tool_and_the_seven_prompts() -> None:
    text = (SKILL_DIR / "SKILL.md").read_text(encoding="utf-8")
    for tool in TOOL_NAMES:
        assert f"`{tool}" in text, tool
    for fragment in (
        "Review today's NBA slate",
        "primary candidate and explain the weakest leg",
        "without assuming independence",
        "bet-slip screenshot",
        "Refresh this ticket",
        "Record it",
        "remaining daily budget",
    ):
        assert fragment in text, fragment
    for state in (
        "RESEARCH_CANDIDATE",
        "NEEDS_BOOK_QUOTE",
        "READY_FOR_USER_REVIEW",
        "EXPIRED",
        "REJECTED",
        "USER_CONFIRMED_PLACED",
        "SETTLED",
    ):
        assert state in text, state
    for rule in ("180 seconds", "60 seconds", "NO SUITABLE TICKET", "WAIT FOR UPDATE", "1-833-PLAYWISE"):
        assert rule in text, rule


def test_skill_references_exist_and_are_linked() -> None:
    text = (SKILL_DIR / "SKILL.md").read_text(encoding="utf-8")
    for ref in ("methodology.md", "hard-rock-rules.md", "workflows.md", "settlement-and-review.md"):
        assert f"references/{ref}" in text, ref
        assert (SKILL_DIR / "references" / ref).is_file(), ref


def test_methodology_contains_worked_examples() -> None:
    text = (SKILL_DIR / "references" / "methodology.md").read_text(encoding="utf-8")
    for example in ("0.343", "0.10", "$55.00", "$45.00", "1 / 5.50", "p1 = q1 / (q1 + q2)"):
        assert example in text, example


def test_hard_rock_rules_cite_sources_with_retrieval_dates() -> None:
    text = (SKILL_DIR / "references" / "hard-rock-rules.md").read_text(encoding="utf-8")
    assert "retrieved 2026-10-19" in text
    assert "docs.google.com/document/d/1LohHmj-8bnU9wnJO8yMsi6Ttvee_EZf3RWg4bfUul7s" in text
    for rule in (
        "48 hours",
        "dressed",
        "overtime",
        "Same Game Parlay",
        "21",
        "1-833-PLAYWISE",
        "Seminole Tribe",
    ):
        assert rule in text, rule


# --------------------------------------------------------------------------------------
# Document hygiene (release-owned docs only)
# --------------------------------------------------------------------------------------


def _release_docs() -> list[Path]:
    files = [p for p in PLUGIN_DIR.rglob("*.md")]
    files += [p for p in DOCS.glob("*.md") if p.name != "ARCHITECTURE.md"]
    files += [
        DOCS / "integration-notes" / "release.md",
        PROJECT_ROOT / "README.md",
        PROJECT_ROOT / "CLAUDE.md",
    ]
    files += [PROJECT_ROOT / "CHANGELOG.md", PROJECT_ROOT / "deploy" / "README.md"]
    return files


@pytest.mark.parametrize("path", _release_docs(), ids=lambda p: str(p.relative_to(PROJECT_ROOT)))
def test_no_dashes_in_release_documents(path: Path) -> None:
    text = path.read_text(encoding="utf-8")
    offending = [i + 1 for i, line in enumerate(text.splitlines()) if any(d in line for d in DASHES)]
    assert not offending, f"{path} has em/en dashes on lines {offending}"


@pytest.mark.parametrize("path", [SKILL_DIR / "SKILL.md", PLUGIN_DIR / "README.md"], ids=["skill", "readme"])
def test_no_banned_marketing_phrases(path: Path) -> None:
    text = path.read_text(encoding="utf-8").lower()
    # The words appear only inside the rule that forbids them.
    for phrase in BANNED_PHRASES:
        occurrences = [m.start() for m in re.finditer(re.escape(phrase), text)]
        for pos in occurrences:
            context = text[max(0, pos - 120) : pos]
            assert "never" in context, f"{phrase!r} used outside the prohibition in {path}"


# --------------------------------------------------------------------------------------
# Marketplace manifest and env example
# --------------------------------------------------------------------------------------


def test_marketplace_manifest() -> None:
    marketplace = json.loads(
        (PROJECT_ROOT / ".claude-plugin" / "marketplace.json").read_text(encoding="utf-8")
    )
    assert marketplace["name"] == "hardrock-nba-parlay-marketplace"
    assert marketplace["owner"] == {"name": "Noel Fernandez"}
    assert marketplace["description"]
    [entry] = marketplace["plugins"]
    assert entry["name"] == "nba-three-leg-parlays"
    assert entry["source"] == "./plugin/nba-three-leg-parlays"
    assert "version" not in entry
    assert (PROJECT_ROOT / entry["source"] / ".claude-plugin" / "plugin.json").is_file()


def test_env_example_lists_every_setting_without_values() -> None:
    from hardrock_nba_parlay.config import Settings

    text = (PROJECT_ROOT / ".env.example").read_text(encoding="utf-8")
    assignments = dict(
        line.split("=", 1) for line in text.splitlines() if line and not line.startswith("#") and "=" in line
    )
    for field in Settings.model_fields:
        assert f"HRNBA_{field.upper()}" in assignments, field
    assert all(value.strip() == "" for value in assignments.values()), "no values allowed in .env.example"


# --------------------------------------------------------------------------------------
# Scripts
# --------------------------------------------------------------------------------------


def test_build_plugin_zip_dry_run_and_real_build(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    build = _load_script("build_plugin_zip")
    assert build.main(["--dry-run", "--dist-dir", str(tmp_path)]) == 0
    out = capsys.readouterr().out
    assert "nba-three-leg-parlays/.claude-plugin/plugin.json" in out
    assert "dry run: would write" in out
    assert not list(tmp_path.iterdir())

    assert build.main(["--dist-dir", str(tmp_path)]) == 0
    zip_path = tmp_path / "nba-three-leg-parlays-0.1.0.zip"
    assert zip_path.is_file()
    with zipfile.ZipFile(zip_path) as archive:
        names = archive.namelist()
    tops = {name.split("/", 1)[0] for name in names}
    assert tops == {"nba-three-leg-parlays"}
    assert "nba-three-leg-parlays/.claude-plugin/plugin.json" in names
    assert "nba-three-leg-parlays/skills/nba-three-leg-parlays/SKILL.md" in names
    assert not any(".DS_Store" in n or "__MACOSX" in n for n in names)


def test_build_plugin_zip_refuses_bin_and_ds_store(tmp_path: Path) -> None:
    build = _load_script("build_plugin_zip")
    copy = tmp_path / "nba-three-leg-parlays"
    shutil.copytree(PLUGIN_DIR, copy)
    (copy / "bin").mkdir()
    (copy / ".DS_Store").write_bytes(b"junk")
    with pytest.raises(SystemExit) as excinfo:
        build.build(copy, tmp_path / "dist", dry_run=True)
    assert excinfo.value.code == 1
    # .DS_Store would have been excluded from the file list even if bin/ were absent.
    entries = build.collect_entries(copy)
    assert not any(e.arcname.endswith(".DS_Store") for e in entries)


def test_stamp_release_rewrites_bundle(tmp_path: Path) -> None:
    stamp = _load_script("stamp_release")
    copy = tmp_path / "nba-three-leg-parlays"
    shutil.copytree(PLUGIN_DIR, copy)
    rc = stamp.main(
        [
            "--plugin-dir",
            str(copy),
            "--server-url",
            "https://parlays.noelfernandez.dev/mcp",
            "--repo-url",
            "https://github.com/noelfernandez/hardrock-nba-parlay-mcp",
            "--support-url",
            "https://github.com/noelfernandez/hardrock-nba-parlay-mcp/issues",
            "--privacy-url",
            "https://github.com/noelfernandez/hardrock-nba-parlay-mcp/blob/main/docs/privacy-policy.md",
        ]
    )
    assert rc == 0
    mcp = json.loads((copy / ".mcp.json").read_text(encoding="utf-8"))
    assert mcp["mcpServers"]["nba-three-leg-parlays"] == {
        "type": "http",
        "url": "https://parlays.noelfernandez.dev/mcp",
    }
    manifest = json.loads((copy / ".claude-plugin" / "plugin.json").read_text(encoding="utf-8"))
    assert manifest["repository"] == "https://github.com/noelfernandez/hardrock-nba-parlay-mcp"
    assert manifest["homepage"] == manifest["repository"]
    assert manifest["supportUrl"].endswith("/issues")
    assert manifest["privacyPolicyUrl"].endswith("privacy-policy.md")
    assert "documentationUrl" not in manifest
    readme = (copy / "README.md").read_text(encoding="utf-8")
    assert "OWNER/REPO" not in readme
    assert "claude plugin marketplace add noelfernandez/hardrock-nba-parlay-mcp" in readme
    # The committed bundle is untouched.
    assert (
        json.loads((PLUGIN_DIR / ".mcp.json").read_text(encoding="utf-8"))["mcpServers"][
            "nba-three-leg-parlays"
        ]["url"]
        == ""
    )


def test_stamp_release_dry_run_writes_nothing(tmp_path: Path) -> None:
    stamp = _load_script("stamp_release")
    copy = tmp_path / "nba-three-leg-parlays"
    shutil.copytree(PLUGIN_DIR, copy)
    before = {p: p.read_bytes() for p in copy.rglob("*") if p.is_file()}
    rc = stamp.main(
        [
            "--plugin-dir",
            str(copy),
            "--server-url",
            "https://parlays.noelfernandez.dev/mcp",
            "--repo-url",
            "https://github.com/noelfernandez/hardrock-nba-parlay-mcp",
            "--dry-run",
        ]
    )
    assert rc == 0
    assert {p: p.read_bytes() for p in copy.rglob("*") if p.is_file()} == before


@pytest.mark.parametrize(
    ("server_url", "repo_url"),
    [
        ("http://parlays.noelfernandez.dev/mcp", "https://github.com/o/r"),
        ("https://localhost:8080/mcp", "https://github.com/o/r"),
        ("https://example.com/mcp", "https://github.com/o/r"),
        ("https://TODO.example.net/mcp", "https://github.com/o/r"),
        ("https://<host>/mcp", "https://github.com/o/r"),
        ("https://parlays.noelfernandez.dev/mcp", "https://gitlab.com/o/r"),
        ("https://parlays.noelfernandez.dev/mcp", "https://github.com/only-owner"),
        ("https://parlays.noelfernandez.dev/mcp", "https://github.com/your-name/your-repo"),
        # RFC 2606 reserved top-level domains and .local (review-release.md D3)
        ("https://example.invalid/mcp", "https://github.com/o/r"),
        ("https://mcp.example/mcp", "https://github.com/o/r"),
        ("https://parlays.test/mcp", "https://github.com/o/r"),
        ("https://srv.localhost/mcp", "https://github.com/o/r"),
        ("https://mac.local/mcp", "https://github.com/o/r"),
        # documentation placeholders as GitHub owner or repository name
        ("https://parlays.noelfernandez.dev/mcp", "https://github.com/example/example"),
        ("https://parlays.noelfernandez.dev/mcp", "https://github.com/owner/repo"),
        ("https://parlays.noelfernandez.dev/mcp", "https://github.com/noelfernandez/Example"),
        ("https://parlays.noelfernandez.dev/mcp", "https://github.com/user/hardrock-nba-parlay-mcp"),
    ],
)
def test_stamp_release_refuses_placeholders_and_non_https(
    tmp_path: Path, server_url: str, repo_url: str
) -> None:
    stamp = _load_script("stamp_release")
    copy = tmp_path / "nba-three-leg-parlays"
    shutil.copytree(PLUGIN_DIR, copy)
    rc = stamp.main(["--plugin-dir", str(copy), "--server-url", server_url, "--repo-url", repo_url])
    assert rc == 1
    assert (
        json.loads((copy / ".mcp.json").read_text(encoding="utf-8"))["mcpServers"]["nba-three-leg-parlays"][
            "url"
        ]
        == ""
    )


def test_stamp_release_refuses_readme_with_replace_instruction(tmp_path: Path) -> None:
    stamp = _load_script("stamp_release")
    copy = tmp_path / "nba-three-leg-parlays"
    shutil.copytree(PLUGIN_DIR, copy)
    readme = copy / "README.md"
    readme.write_text(
        readme.read_text(encoding="utf-8") + "\nOnce the repository exists, replace OWNER/REPO with it.\n",
        encoding="utf-8",
    )
    before = readme.read_bytes()
    rc = stamp.main(
        [
            "--plugin-dir",
            str(copy),
            "--server-url",
            "https://parlays.noelfernandez.dev/mcp",
            "--repo-url",
            "https://github.com/noelfernandez/hardrock-nba-parlay-mcp",
        ]
    )
    assert rc == 1
    assert readme.read_bytes() == before
    assert (
        json.loads((copy / ".mcp.json").read_text(encoding="utf-8"))["mcpServers"]["nba-three-leg-parlays"][
            "url"
        ]
        == ""
    )


# --------------------------------------------------------------------------------------
# Docs cross-checks
# --------------------------------------------------------------------------------------


def test_docs_exist_and_carry_required_markers() -> None:
    expectations = {
        "publication-readiness.md": [
            "April 15, 2026",
            "March 16, 2026",
            "September 15, 2025",
            "November 12, 2026",
            "UNRESOLVED",
            "4.A",
            "3.H",
            "executes financial transactions on behalf of users",
        ],
        "sources.md": ["the-odds-api.com", "support.claude.com", "Retrieved (UTC)", "mcp | 2.3.0"],
        "install.md": [
            "NOT YET TESTED",
            "--plugin-dir",
            "claude mcp add --transport http",
            "Upload plugin",
            "Connectors",
            "uninstall",
            "rollback",
            "export_my_data",
        ],
        "costs.md": ["500", "$30", "20,000", "balldontlie", "$9.99", "100 users", "Railway", "30-day"],
        "privacy-policy.md": ["OWNER TO FILL IN", "argon2id", "The Odds API", "Delete"],
        "terms.md": ["OWNER TO FILL IN", "never places", "21"],
        "support.md": ["OWNER TO FILL IN"],
        "test-account.md": ["signup", "owner's ledger", "Test & launch"],
        "use-cases.md": [
            "PENDING INTEGRATION TEST",
            "get_system_status",
            "record_actual_bet",
            "get_performance",
        ],
        "launch-readiness.md": ["PENDING INTEGRATION TEST", "manual", "automatic", "13.H", "NOT SUBMITTED"],
    }
    for name, markers in expectations.items():
        text = (DOCS / name).read_text(encoding="utf-8")
        for marker in markers:
            assert marker in text, f"{name} lacks {marker!r}"
    for name in ("Dockerfile", "railway.toml", "fly.toml", "docker-compose.yml", "README.md"):
        assert (PROJECT_ROOT / "deploy" / name).is_file(), name
    dockerfile = (PROJECT_ROOT / "deploy" / "Dockerfile").read_text(encoding="utf-8")
    assert "python:3.12-slim" in dockerfile
    assert "uv sync --frozen --no-dev" in dockerfile
    assert "USER hrnba" in dockerfile
    assert '"hrnba", "serve", "--transport", "http", "--host", "0.0.0.0", "--port", "8080"' in dockerfile
    compose = (PROJECT_ROOT / "deploy" / "docker-compose.yml").read_text(encoding="utf-8")
    assert "POSTGRES_PASSWORD: ${POSTGRES_PASSWORD" in compose
    assert not re.search(r"POSTGRES_PASSWORD:\s*[A-Za-z0-9]", compose), "no literal password in compose"
    fly = (PROJECT_ROOT / "deploy" / "fly.toml").read_text(encoding="utf-8")
    assert (
        'auto_stop_machines = "off"' in fly
        and "min_machines_running = 1" in fly
        and 'primary_region = "iad"' in fly
    )


def test_no_secret_looking_values_in_release_files() -> None:
    key_like = re.compile(r"(?:apiKey=|api_key=|Bearer\s+)[A-Za-z0-9_-]{20,}")
    secret_assignment = re.compile(
        r"(HRNBA_SECRET_KEY|HRNBA_ODDS_API_KEY|HRNBA_DATABASE_URL|POSTGRES_PASSWORD)\s*[=:]\s*(\S*)"
    )
    files = [*PLUGIN_DIR.rglob("*"), *(PROJECT_ROOT / "deploy").rglob("*"), PROJECT_ROOT / ".env.example"]
    for path in files:
        if not path.is_file():
            continue
        for line in path.read_text(encoding="utf-8").splitlines():
            if line.lstrip().startswith("#"):
                continue
            assert not key_like.search(line), f"{path}: {line}"
            for match in secret_assignment.finditer(line):
                value = match.group(2).strip("`'\"")
                placeholder = value in ("", "...") or "${" in value or value.startswith(("<", "$("))
                assert placeholder, f"{path}: literal secret value in {line!r}"
