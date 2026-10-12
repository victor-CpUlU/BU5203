"""Settings: .env (provider, model, key) and config/analysis.toml (thresholds, keywords, limits)."""
from __future__ import annotations

import os
import tomllib
from dataclasses import dataclass, field
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[2]
HOST = "127.0.0.1"  # fixed: the app only listens on loopback (Req 27.5)
SUPPORTED_PROVIDERS = ("openai", "gemini", "anthropic", "kiro_cli")
UNIT_TYPES = ("percent", "multiple", "days", "amount")

DEFAULT_LARGE_SWING = {"percent": 10.0, "multiple": 2.0, "days": 5.0, "amount": 50.0}
DEFAULT_STABLE_BAND = {"percent": 1.0, "multiple": 0.10, "days": 3.0, "amount": 5.0}

# Test hooks: tests point these at temporary folders.
_overrides: dict[str, object] = {}


def parse_env_file(path: Path) -> dict[str, str]:
    values: dict[str, str] = {}
    if not path.exists():
        return values
    for raw in path.read_text(encoding="utf-8").splitlines():
        line = raw.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, value = line.partition("=")
        values[key.strip()] = value.strip().strip('"').strip("'")
    return values


def _resolve_numbers(raw: dict | None, defaults: dict[str, float], allow_zero: bool) -> tuple[dict[str, float], list[str]]:
    """Apply per-unit-type defaults for missing, non-numeric or invalid values (Req 10.8, 12.9)."""
    raw = raw or {}
    values: dict[str, float] = {}
    defaulted: list[str] = []
    for unit in UNIT_TYPES:
        v = raw.get(unit)
        ok = isinstance(v, (int, float)) and not isinstance(v, bool)
        if ok and (v < 0 or (v == 0 and not allow_zero)):
            ok = False
        if ok:
            values[unit] = float(v)
        else:
            values[unit] = defaults[unit]
            defaulted.append(unit)
    return values, defaulted


def resolve_thresholds(raw: dict | None) -> tuple[dict[str, float], list[str]]:
    return _resolve_numbers(raw, DEFAULT_LARGE_SWING, allow_zero=False)


def resolve_stable_bands(raw: dict | None) -> tuple[dict[str, float], list[str]]:
    return _resolve_numbers(raw, DEFAULT_STABLE_BAND, allow_zero=True)


@dataclass
class Settings:
    llm_provider: str = ""
    llm_model: str = ""
    llm_api_key: str = ""
    kiro_cli_path: str = "kiro-cli"
    support_check_enabled: bool = False
    port: int = 8000
    financial_db_path: Path = PROJECT_ROOT / "intel_quarterly_ratios.csv"
    data_dir: Path = PROJECT_ROOT / "data"
    prompts_dir: Path = PROJECT_ROOT / "backend" / "app" / "prompts"
    max_upload_mb: float = 50
    max_csv_mb: float = 5
    page_limit: int = 30
    llm_timeout_s: float = 120
    llm_max_retries: int = 2
    large_swing: dict[str, float] = field(default_factory=lambda: dict(DEFAULT_LARGE_SWING))
    stable_band: dict[str, float] = field(default_factory=lambda: dict(DEFAULT_STABLE_BAND))
    defaults_applied: list[str] = field(default_factory=list)
    keywords_business: list[str] = field(default_factory=list)
    keywords_debt: list[str] = field(default_factory=list)

    def secrets(self) -> list[str]:
        return [self.llm_api_key] if self.llm_api_key else []

    def llm_settings_problems(self) -> list[str]:
        """Names (never values) of missing or invalid .env settings (Req 25.8, 27.4)."""
        problems = []
        if self.llm_provider not in SUPPORTED_PROVIDERS:
            problems.append("LLM_PROVIDER")
        if self.llm_provider == "kiro_cli":
            # Kiro CLI: model is optional (Kiro's default), and the key is optional when
            # `kiro-cli login` has an active session on this machine.
            return problems
        if not self.llm_model:
            problems.append("LLM_MODEL")
        if not self.llm_api_key:
            problems.append("LLM_API_KEY")
        return problems


def get_settings() -> Settings:
    env_path = Path(_overrides.get("env_path", PROJECT_ROOT / ".env"))
    toml_path = Path(_overrides.get("toml_path", PROJECT_ROOT / "config" / "analysis.toml"))
    env = parse_env_file(env_path)
    for key in ("LLM_PROVIDER", "LLM_MODEL", "LLM_API_KEY", "KIRO_CLI_PATH", "SUPPORT_CHECK_ENABLED", "PORT", "FINANCIAL_DB_PATH"):
        if key in os.environ and key not in env:
            env[key] = os.environ[key]
    cfg: dict = {}
    if toml_path.exists():
        with toml_path.open("rb") as fh:
            cfg = tomllib.load(fh)

    s = Settings()
    s.llm_provider = env.get("LLM_PROVIDER", "").strip().lower()
    s.llm_model = env.get("LLM_MODEL", "").strip()
    s.llm_api_key = env.get("LLM_API_KEY", "").strip()
    s.kiro_cli_path = env.get("KIRO_CLI_PATH", "").strip() or "kiro-cli"
    s.support_check_enabled = env.get("SUPPORT_CHECK_ENABLED", "false").strip().lower() in ("1", "true", "yes")
    try:
        s.port = int(env.get("PORT", "8000"))
    except ValueError:
        s.port = 8000
    db = env.get("FINANCIAL_DB_PATH", "").strip()
    s.financial_db_path = (PROJECT_ROOT / db) if db and not Path(db).is_absolute() else Path(db) if db else PROJECT_ROOT / "intel_quarterly_ratios.csv"
    s.data_dir = Path(_overrides.get("data_dir", PROJECT_ROOT / "data"))
    s.prompts_dir = Path(_overrides.get("prompts_dir", s.prompts_dir))
    s.max_upload_mb = float(cfg.get("max_upload_mb", 50))
    s.max_csv_mb = float(cfg.get("max_csv_mb", 5))
    s.page_limit = min(200, max(1, int(cfg.get("page_limit", 30))))
    s.llm_timeout_s = float(cfg.get("llm_timeout_s", 120))
    s.llm_max_retries = int(cfg.get("llm_max_retries", 2))
    s.large_swing, d1 = resolve_thresholds(cfg.get("large_swing"))
    s.stable_band, d2 = resolve_stable_bands(cfg.get("stable_band"))
    s.defaults_applied = [f"large_swing.{u}" for u in d1] + [f"stable_band.{u}" for u in d2]
    kw = cfg.get("keywords", {})
    s.keywords_business = [k.lower() for k in kw.get("business", [])]
    s.keywords_debt = [k.lower() for k in kw.get("debt", [])]
    return s
