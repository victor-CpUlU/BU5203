"""Prompt files, provider-agnostic LLM_Client and the single validation/retry runner (Req 1.8, 1.10, 19, 25)."""
from __future__ import annotations

import hashlib
import json
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Callable, Protocol

import httpx
from pydantic import ValidationError

from .schemas import SCHEMAS
from .security import redact
from .settings import Settings
from .storage import AppError

PROMPT_FILES = {"MASTER": "master_system.md", "S2A": "s2a_business.md", "S2B": "s2b_debt.md", "S3": "s3_trend.md",
                "S4": "s4_risks.md", "S5": "s5_memo.md", "S6": "s6_support.md"}


# --------------------------------------------------------------------------- prompts
@dataclass(frozen=True)
class PromptFile:
    prompt_id: str
    version: str
    text: str


class PromptLoadError(Exception):
    def __init__(self, prompt_id: str, reason: str):
        super().__init__(f"Prompt {prompt_id}: {reason}")
        self.prompt_id, self.reason = prompt_id, reason


def parse_prompt_file(prompt_id: str, raw: str) -> PromptFile:
    raw = raw.replace("\r\n", "\n")
    m = re.match(r"^version:\s*(\S+)\s*\n---\n", raw)
    if not m:
        raise PromptLoadError(prompt_id, "no version identifier")
    return PromptFile(prompt_id, m.group(1), raw[m.end():].rstrip("\n"))


def load_prompts(folder: Path) -> dict[str, PromptFile]:
    prompts = {}
    for pid, name in PROMPT_FILES.items():
        p = Path(folder) / name
        try:
            raw = p.read_text(encoding="utf-8")
        except OSError as exc:
            raise PromptLoadError(pid, f"missing or unreadable file {name}") from exc
        prompts[pid] = parse_prompt_file(pid, raw)
    return prompts


def extract_instruction_prompts(md_text: str) -> dict[str, PromptFile]:
    """Read every '<!-- PROMPT: ID | VERSION -->' + fenced text block from Instructions.md."""
    md_text = md_text.replace("\r\n", "\n")
    out = {}
    for m in re.finditer(r"<!-- PROMPT: (\w+) \| (\S+) -->\n```text\n(.*?)\n```", md_text, re.S):
        out[m.group(1)] = PromptFile(m.group(1), m.group(2), m.group(3).rstrip("\n"))
    return out


# --------------------------------------------------------------------------- clients
class LLMTransportError(Exception):
    pass


class LLMClient(Protocol):
    model_name: str

    def complete(self, system: str, user: str, timeout_s: float) -> str: ...


class _HttpClient:
    def __init__(self, model: str, key: str):
        self.model_name, self._key = model, key

    def _post(self, url: str, headers: dict, body: dict, timeout_s: float) -> dict:
        try:
            resp = httpx.post(url, headers=headers, json=body, timeout=timeout_s)
        except httpx.TimeoutException as exc:
            raise LLMTransportError(f"The AI provider did not respond within {int(timeout_s)} seconds.") from exc
        except httpx.HTTPError as exc:
            raise LLMTransportError(redact(f"Network error contacting the AI provider: {exc}", [self._key])) from exc
        if resp.status_code >= 400:
            raise LLMTransportError(redact(f"AI provider error {resp.status_code}: {resp.text[:600]}", [self._key]))
        try:
            return resp.json()
        except ValueError as exc:
            raise LLMTransportError("The AI provider returned a response that is not JSON.") from exc


class OpenAIClient(_HttpClient):
    def complete(self, system: str, user: str, timeout_s: float) -> str:
        data = self._post("https://api.openai.com/v1/chat/completions",
                          {"Authorization": f"Bearer {self._key}"},
                          {"model": self.model_name, "temperature": 0, "response_format": {"type": "json_object"},
                           "messages": [{"role": "system", "content": system}, {"role": "user", "content": user}]}, timeout_s)
        try:
            return data["choices"][0]["message"]["content"]
        except (KeyError, IndexError, TypeError) as exc:
            raise LLMTransportError("Unexpected response shape from OpenAI.") from exc


class GeminiClient(_HttpClient):
    def complete(self, system: str, user: str, timeout_s: float) -> str:
        url = f"https://generativelanguage.googleapis.com/v1beta/models/{self.model_name}:generateContent"
        data = self._post(url, {"x-goog-api-key": self._key},
                          {"systemInstruction": {"parts": [{"text": system}]},
                           "contents": [{"role": "user", "parts": [{"text": user}]}],
                           "generationConfig": {"temperature": 0, "responseMimeType": "application/json"}}, timeout_s)
        try:
            return "".join(p.get("text", "") for p in data["candidates"][0]["content"]["parts"])
        except (KeyError, IndexError, TypeError) as exc:
            raise LLMTransportError("Unexpected response shape from Gemini.") from exc


class AnthropicClient(_HttpClient):
    def complete(self, system: str, user: str, timeout_s: float) -> str:
        data = self._post("https://api.anthropic.com/v1/messages",
                          {"x-api-key": self._key, "anthropic-version": "2023-06-01"},
                          {"model": self.model_name, "max_tokens": 16000, "temperature": 0, "system": system,
                           "messages": [{"role": "user", "content": user}]}, timeout_s)
        try:
            return "".join(b.get("text", "") for b in data["content"] if b.get("type") == "text")
        except (KeyError, TypeError) as exc:
            raise LLMTransportError("Unexpected response shape from Anthropic.") from exc


ANSI_RE = re.compile(r"\x1b\[[0-9;?]*[ -/]*[@-~]|\x1b\][^\x07]*\x07")


def extract_json_object(text: str) -> str:
    """Return the last complete top-level JSON object in `text` (CLI output can include extra lines)."""
    t = ANSI_RE.sub("", text or "")
    fenced = re.findall(r"```(?:json)?\s*\n(\{.*?\})\s*\n```", t, re.S)
    if fenced:
        return fenced[-1]
    decoder = json.JSONDecoder()
    best = None
    i = t.find("{")
    while i != -1:
        try:
            obj, end = decoder.raw_decode(t, i)
            if isinstance(obj, dict):
                best = t[i:end]
                i = t.find("{", end)
                continue
        except json.JSONDecodeError:
            pass
        i = t.find("{", i + 1)
    return best if best is not None else t.strip()


class KiroCliClient:
    """Calls the Kiro CLI in headless mode (`kiro-cli chat --no-interactive`), using the Kiro subscription.

    The prompt goes through stdin (no command-line length limit). The CLI runs in an empty temporary
    folder with no tool-trust flags, so it has no project files to read and no tool can be auto-approved.
    Authentication: an active `kiro-cli login` session, or KIRO_API_KEY (taken from LLM_API_KEY).
    """

    def __init__(self, model: str, key: str, cli_path: str = "kiro-cli"):
        self.model_name = f"kiro-cli:{model or 'default'}"
        self._model, self._key, self._cli = model, key, cli_path

    def complete(self, system: str, user: str, timeout_s: float) -> str:
        import os
        import shutil
        import subprocess
        import tempfile

        exe = shutil.which(self._cli) or (self._cli if Path(self._cli).exists() else None)
        if not exe:
            raise LLMTransportError("Kiro CLI not found. Install it (PowerShell: irm 'https://cli.kiro.dev/install.ps1' | iex), "
                                    "run `kiro-cli login`, or set KIRO_CLI_PATH in .env.")
        args = [exe, "chat", "--no-interactive"]
        if self._model:
            args += ["--model", self._model]
        prompt = ("Follow the SYSTEM INSTRUCTIONS, then complete the TASK. Do not use any tools, do not read or write files. "
                  "Reply with the JSON object only.\n\n=== SYSTEM INSTRUCTIONS ===\n" + system + "\n\n=== TASK ===\n" + user)
        env = dict(os.environ)
        env["NO_COLOR"] = "1"
        if self._key:
            env["KIRO_API_KEY"] = self._key
        from . import lifecycle

        with tempfile.TemporaryDirectory(prefix="kiro_task_") as workdir:
            try:
                proc = subprocess.Popen(args, stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True,
                                        encoding="utf-8", errors="replace", cwd=workdir, env=env)
            except OSError as exc:
                raise LLMTransportError(f"The Kiro CLI could not be started: {exc}") from exc
            lifecycle.register(proc)  # stopped too if the app is closed mid-call
            try:
                stdout, stderr = proc.communicate(prompt, timeout=timeout_s)
            except subprocess.TimeoutExpired as exc:
                lifecycle.kill_tree(proc)
                proc.communicate()
                raise LLMTransportError(f"The Kiro CLI did not respond within {int(timeout_s)} seconds.") from exc
            finally:
                lifecycle.unregister(proc)
        if proc.returncode != 0:
            detail = ANSI_RE.sub("", (stderr or stdout or "").strip())[-600:]
            hint = " Run `kiro-cli login` or set LLM_API_KEY to a Kiro API key." if "auth" in detail.lower() or "login" in detail.lower() else ""
            raise LLMTransportError(redact(f"Kiro CLI exited with code {proc.returncode}: {detail}{hint}", [self._key]))
        return extract_json_object(stdout)


def make_client(settings: Settings) -> LLMClient:
    problems = settings.llm_settings_problems()
    if problems:
        raise AppError(412, "llm_not_configured",
                       "The AI provider is not configured. Missing or invalid .env setting(s): " + ", ".join(problems), details=problems)
    if settings.llm_provider == "kiro_cli":
        return KiroCliClient(settings.llm_model, settings.llm_api_key, settings.kiro_cli_path)
    cls = {"openai": OpenAIClient, "gemini": GeminiClient, "anthropic": AnthropicClient}[settings.llm_provider]
    return cls(settings.llm_model, settings.llm_api_key)


# Tests replace this factory with a fake client.
client_factory: Callable[[Settings], LLMClient] = make_client


# --------------------------------------------------------------------------- runner
@dataclass
class TaskSpec:
    prompt_id: str
    rules: Callable[[dict], list[str]] | None = None          # section rules on the validated output
    refs: Callable[[dict], list[tuple[str, str]]] | None = None  # (owner_id, evidence_id) pairs cited
    retry_transport: bool = False                              # True only for Section 2 (confirmed rule)
    soft_unknown_refs: bool = False                            # True only for Section 5 (Req 25.6)


def canonical_json(obj) -> str:
    return json.dumps(obj, sort_keys=True, ensure_ascii=False, separators=(",", ":"), default=str)


def strip_fences(text: str) -> str:
    t = text.strip()
    m = re.match(r"^```(?:json)?\s*\n(.*)\n```$", t, re.S)
    return m.group(1) if m else t


def _schema_errors(exc: ValidationError) -> list[str]:
    errs = []
    for e in exc.errors()[:25]:
        loc = ".".join(str(x) for x in e["loc"])
        errs.append(f"{loc}: {e['msg']}")
    return errs


def run_llm_task(task: TaskSpec, input_obj: dict, prompts: dict[str, PromptFile], settings: Settings,
                 known_ids: set[str], audit: Callable[[dict], None]) -> dict:
    """Call -> parse -> schema -> section rules -> Reference_Validator, retrying with errors (max 3 attempts)."""
    client = client_factory(settings)
    prompt = prompts[task.prompt_id]
    system = prompts["MASTER"].text
    base_user = prompt.text.replace("{{INPUT_JSON}}", canonical_json(input_obj))
    schema = SCHEMAS[task.prompt_id]
    secrets = settings.secrets()
    attempts = settings.llm_max_retries + 1
    errors: list[str] = []
    for attempt in range(1, attempts + 1):
        user = base_user
        if errors:
            user += "\n\nVALIDATION ERRORS FROM PREVIOUS ATTEMPT (fix all of them and return the full JSON again):\n- " + "\n- ".join(errors)
        input_hash = hashlib.sha256((system + "\n" + base_user).encode("utf-8")).hexdigest()
        try:
            raw = client.complete(system, user, settings.llm_timeout_s)
        except LLMTransportError as exc:
            msg = redact(str(exc), secrets)
            if task.retry_transport and attempt < attempts:
                errors = []
                continue
            return {"ok": False, "errors": [msg], "transport": True, "attempts": attempt}
        audit({"type": "llm_output", "prompt_id": prompt.prompt_id, "prompt_version": prompt.version,
               "model": getattr(client, "model_name", "unknown"), "input_hash": input_hash, "attempt": attempt})
        try:
            data = json.loads(strip_fences(raw))
        except json.JSONDecodeError as exc:
            errors = [f"Output is not valid JSON: {exc}"]
            continue
        try:
            parsed = schema.model_validate(data).model_dump()
        except ValidationError as exc:
            errors = _schema_errors(exc)
            continue
        errors = list(task.rules(parsed)) if task.rules else []
        unknown = [(o, e) for o, e in (task.refs(parsed) if task.refs else []) if e not in known_ids]
        if not errors and not unknown:
            return {"ok": True, "output": parsed, "unknown_refs": [], "attempts": attempt}
        if not errors and unknown and task.soft_unknown_refs and attempt == attempts:
            return {"ok": True, "output": parsed, "unknown_refs": unknown, "attempts": attempt}
        errors += [f"{o} cites unknown Evidence_ID {e}; cite only IDs supplied in the input" for o, e in unknown]
    return {"ok": False, "errors": [redact(e, secrets) for e in errors], "transport": False, "attempts": attempts}
