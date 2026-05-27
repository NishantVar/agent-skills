"""Config loader. Reads ~/.config/cmux-observability/config.toml; missing
fields fall back to defaults defined here."""

from __future__ import annotations

import os
import tomllib
from dataclasses import dataclass, field
from pathlib import Path


def _default_excludes() -> list[str]:
    # Layered on top of the find -prune list; these accept glob patterns.
    return ["~/Library/*", "~/.Trash/*"]


@dataclass
class ProductivityConfig:
    repo_paths: list[str] = field(default_factory=lambda: ["~"])
    exclude: list[str] = field(default_factory=_default_excludes)
    author_emails: list[str] = field(default_factory=list)


@dataclass
class DiscoveryConfig:
    use_mdfind_seed: bool = True
    max_depth: int = 8
    cache_ttl_seconds: int = 3600
    cache_path: str = "~/.local/share/cmux-observability/repo_discovery.json"


@dataclass
class SummarizerConfig:
    enabled: bool = True
    read_screen_lines: int = 150     # hard cap 300 in CLI validation
    prompt_version: int = 1
    themes_enabled: bool = True
    max_scrollback_bytes: int = 4096


@dataclass
class RenderConfig:
    open_browser: bool = True
    retention: int = 100


@dataclass
class Config:
    productivity: ProductivityConfig = field(default_factory=ProductivityConfig)
    discovery: DiscoveryConfig = field(default_factory=DiscoveryConfig)
    summarizer: SummarizerConfig | None = field(default_factory=SummarizerConfig)
    render: RenderConfig | None = field(default_factory=RenderConfig)


def default_config_path() -> Path:
    return Path(os.path.expanduser("~/.config/cmux-observability/config.toml"))


def load(path: Path | None = None) -> Config:
    """Load config from `path` (or the default location). Missing file or
    malformed TOML returns defaults; callers may record a Failure."""
    path = path or default_config_path()
    if not path.exists():
        return Config()
    try:
        data = tomllib.loads(path.read_text())
    except tomllib.TOMLDecodeError:
        return Config()

    prod = data.get("productivity", {}) or {}
    disc = data.get("discovery", {}) or {}
    summ = data.get("summarizer", {}) or {}
    rend = data.get("render", {}) or {}

    return Config(
        productivity=ProductivityConfig(
            repo_paths=prod.get("repo_paths", ["~"]),
            exclude=prod.get("exclude", _default_excludes()),
            author_emails=prod.get("author_emails", []),
        ),
        discovery=DiscoveryConfig(
            use_mdfind_seed=disc.get("use_mdfind_seed", True),
            max_depth=disc.get("max_depth", 8),
            cache_ttl_seconds=disc.get("cache_ttl_seconds", 3600),
            cache_path=disc.get(
                "cache_path",
                "~/.local/share/cmux-observability/repo_discovery.json",
            ),
        ),
        summarizer=SummarizerConfig(
            enabled=summ.get("enabled", True),
            read_screen_lines=summ.get("read_screen_lines", 150),
            prompt_version=summ.get("prompt_version", 1),
            themes_enabled=summ.get("themes_enabled", True),
            max_scrollback_bytes=summ.get("max_scrollback_bytes", 4096),
        ),
        render=RenderConfig(
            open_browser=rend.get("open_browser", True),
            retention=rend.get("retention", 100),
        ),
    )
