"""Persistent local experiment jobs.

Jobs deliberately build configurations from server-declared profiles and
scenario ids. A request is data for an experiment, never shell or network
configuration. Execution stays in a non-daemon thread so shutdown can wait for
the runner's own ``finally`` block to close clinic and double processes.
"""
from __future__ import annotations

import asyncio
import json
import threading
import uuid
from datetime import UTC, datetime
from pathlib import Path
from typing import Any
from urllib.parse import urlsplit

import yaml

from evaluator.clinic.dataset import Dataset
from evaluator.harness.tts import provider_available
from evaluator.profiles import (
    LaboratoryRefusal,
    ProfileCatalog,
    ProfileNotFound,
    assert_laboratory_profile,
)
from evaluator.profiles.guard import inspect_profile
from evaluator.runner.experiment import run_experiment, verify_clinic

TERMINAL = {"completed", "failed", "cancelled"}
ACTIVE = {"pending", "preparing", "running", "cancelling"}


class JobError(ValueError):
    pass


class JobStore:
    def __init__(self, results_root: Path | str, catalog: ProfileCatalog, scenario_root: Path | str) -> None:
        self.root = Path(results_root)
        self.catalog = catalog
        self.scenario_root = Path(scenario_root)
        self.path = self.root / "_jobs" / "jobs-v1.json"
        self._lock = threading.Lock()
        self._threads: dict[str, threading.Thread] = {}
        self._recover_after_restart()

    def _load(self) -> dict[str, dict[str, Any]]:
        try:
            value = json.loads(self.path.read_text(encoding="utf-8"))
        except (FileNotFoundError, json.JSONDecodeError):
            return {}
        jobs = value.get("jobs", {}) if isinstance(value, dict) else {}
        return jobs if isinstance(jobs, dict) else {}

    def _save(self, jobs: dict[str, dict[str, Any]]) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        temp = self.path.with_suffix(".tmp")
        temp.write_text(json.dumps({"schema_version": 1, "jobs": jobs}, ensure_ascii=False, indent=2), encoding="utf-8")
        temp.replace(self.path)

    def _recover_after_restart(self) -> None:
        with self._lock:
            jobs = self._load()
            changed = False
            for job in jobs.values():
                if job.get("status") in ACTIVE:
                    job.update({"status": "failed", "error": "servidor reiniciado", "ended_at": _now()})
                    changed = True
            if changed:
                self._save(jobs)

    def list(self) -> list[dict[str, Any]]:
        with self._lock:
            return sorted(self._load().values(), key=lambda job: job["created_at"], reverse=True)

    def get(self, job_id: str) -> dict[str, Any] | None:
        with self._lock:
            return self._load().get(job_id)

    def create(self, body: dict[str, Any]) -> dict[str, Any]:
        profiles = body.get("profile_ids")
        scenarios = body.get("scenario_ids")
        mode = body.get("mode", "text")
        repetitions = body.get("repetitions", 1)
        allowed = {"profile_ids", "scenario_ids", "mode", "repetitions"}
        unknown = sorted(set(body) - allowed)
        if unknown:
            raise JobError(f"campos desconocidos: {', '.join(unknown)}")
        if not isinstance(profiles, list) or not profiles or not all(isinstance(v, str) for v in profiles):
            raise JobError("profile_ids debe ser una lista no vacía de ids")
        if not isinstance(scenarios, list) or not scenarios or not all(isinstance(v, str) for v in scenarios):
            raise JobError("scenario_ids debe ser una lista no vacía de ids")
        if mode not in {"text", "voice"}:
            raise JobError("mode debe ser text o voice")
        if isinstance(repetitions, bool) or not isinstance(repetitions, int) or not 1 <= repetitions <= 10:
            raise JobError("repetitions debe estar entre 1 y 10")
        if len(profiles) != len(set(profiles)) or len(scenarios) != len(set(scenarios)):
            raise JobError("Los perfiles y escenarios no pueden repetirse en la selección")
        selected = []
        for profile_id in profiles:
            try:
                profile = self.catalog.get(profile_id)
                assert_laboratory_profile(profile, probe_ports=bool(profile.start_command))
            except (ProfileNotFound, LaboratoryRefusal) as exc:
                raise JobError(str(exc)) from None
            endpoint = profile.endpoints.text_url if mode == "text" else profile.endpoints.ws_url
            if not endpoint:
                raise JobError(f"perfil {profile_id} no declara la modalidad {mode}")
            selected.append(profile)
        paths = [self._scenario_path(scenario_id) for scenario_id in scenarios]
        endpoints = [p.endpoints.text_url if mode == "text" else p.endpoints.ws_url for p in selected]
        if len(endpoints) != len(set(endpoints)):
            raise JobError("Dos candidatos comparten endpoint. Arranca cada motor en un puerto separado")
        bindings = {(p.laboratory.clinic_url, p.laboratory.submit_key, p.laboratory.tts if mode == "voice" else None) for p in selected}
        if len(bindings) != 1:
            raise JobError("Un experimento debe compartir clínica y TTS; separa los perfiles incompatibles")
        first = selected[0].laboratory
        if mode == "voice" and not provider_available(first.tts):
            raise JobError("El TTS del perfil no está disponible. Instálalo antes de ejecutar voz")
        try:
            verify_clinic(first.clinic_url, Dataset.load(Path(__file__).parents[3] / "data/clinic_dataset.json"), first.submit_key)
            for profile in selected:
                if not profile.start_command:
                    status = asyncio.run(inspect_profile(profile))
                    if not status["ready"]:
                        raise JobError(status["reason"])
        except ValueError as exc:
            raise JobError(str(exc)) from None
        job_id = f"job-{uuid.uuid4().hex[:12]}"
        job = {
            "id": job_id, "status": "pending", "created_at": _now(), "started_at": None, "ended_at": None,
            "profile_ids": profiles, "scenario_ids": scenarios, "mode": mode, "repetitions": repetitions,
            "progress": {"completed": 0, "total": len(selected) * len(paths) * repetitions},
            "run_id": None, "error": None, "cancel_requested": False,
        }
        with self._lock:
            jobs = self._load()
            if any(item["status"] in ACTIVE for item in jobs.values()):
                raise JobError("Ya hay un experimento activo. Espera o cancélalo antes de crear otro")
            jobs[job_id] = job
            self._save(jobs)
        thread = threading.Thread(target=self._run, args=(job_id, selected, paths), name=job_id, daemon=False)
        self._threads[job_id] = thread
        thread.start()
        return job

    def scenarios(self) -> list[dict[str, str]]:
        """Browser-safe scenarios, addressed by id rather than filesystem path."""
        import glob

        from evaluator.models import Scenario

        rows: list[dict[str, str]] = []
        for name in glob.glob(str(self.scenario_root / "**" / "*.yaml"), recursive=True):
            try:
                scenario = Scenario.load(name)
            except (OSError, ValueError, yaml.YAMLError):
                # One malformed fixture must not hide valid declared scenarios.
                pass
            else:
                rows.append({"id": scenario.id, "problem_id": scenario.problem_id, "split": scenario.split})
        return sorted(rows, key=lambda row: row["id"])

    def cancel(self, job_id: str) -> dict[str, Any]:
        with self._lock:
            jobs = self._load()
            job = jobs.get(job_id)
            if job is None:
                raise KeyError(job_id)
            if job["status"] in TERMINAL:
                raise RuntimeError("el trabajo ya terminó")
            job["cancel_requested"] = True
            job["status"] = "cancelling"
            self._save(jobs)
            return job

    def _scenario_path(self, scenario_id: str) -> Path:
        # Scenario IDs are matched against parsed YAML. A client cannot smuggle
        # a filesystem path through this lookup.
        import glob

        from evaluator.models import Scenario
        for name in glob.glob(str(self.scenario_root / "**" / "*.yaml"), recursive=True):
            path = Path(name)
            try:
                if Scenario.load(str(path)).id == scenario_id:
                    return path.resolve()
            except (OSError, ValueError, yaml.YAMLError):
                # A broken YAML file is not selectable; the other declarations
                # remain useful to the operator.
                pass
        raise JobError(f"scenario_id desconocido: {scenario_id}")

    def _run(self, job_id: str, profiles: list[Any], paths: list[Path]) -> None:
        with self._lock:
            jobs = self._load()
            job = jobs[job_id]
            if job["cancel_requested"]:
                job.update({"status": "cancelled", "ended_at": _now()})
                self._save(jobs)
                return
            job.update({"status": "preparing", "started_at": _now()})
            self._save(jobs)
        try:
            config = self._write_config(job_id, profiles, paths)
            self._set(job_id, status="running")
            out = run_experiment(str(config), str(self.root), cancel_requested=lambda: self._cancelled(job_id),
                on_progress=lambda path, completed, total: self._set(job_id, run_id=path.name,
                    progress={"completed": completed, "total": total}))
            manifest = _read_manifest(out)
            completed = int(manifest.get("completed_cases", 0))
            status = "cancelled" if manifest.get("status") == "cancelled" else "completed"
            self._set(job_id, status=status, run_id=out.name, ended_at=_now(), progress={"completed": completed, "total": self.get(job_id)["progress"]["total"]})
        except Exception as exc:  # noqa: BLE001 - worker must persist every failure
            self._set(job_id, status="failed", ended_at=_now(), error=f"ejecución falló: {type(exc).__name__}")

    def _write_config(self, job_id: str, profiles: list[Any], paths: list[Path]) -> Path:
        job = self.get(job_id)
        job_dir = self.root / "_jobs" / job_id
        job_dir.mkdir(parents=True, exist_ok=True)
        first = profiles[0]
        candidates = []
        for profile in profiles:
            candidates.append({
                "name": profile.id, "kind": "external", "version": profile.version,
                "text_url": profile.endpoints.text_url if job["mode"] == "text" else None,
                "ws_url": profile.endpoints.ws_url if job["mode"] == "voice" else None,
                "usage_url": profile.endpoints.usage_url, "engine": profile.engine,
                "start_command": profile.start_command,
                "start_cwd": str(Path(__file__).resolve().parents[4]),
                "env": {**profile.launch_env, "PROSPER_API_KEY": profile.laboratory.submit_key,
                        "PROSPER_API_BASE_URL": profile.laboratory.clinic_url},
            })
        config = {
            "name": job_id, "clinic_dataset": str((Path(__file__).parents[3] / "data" / "clinic_dataset.json").resolve()),
            "clinic_port": urlsplit(first.laboratory.clinic_url).port or 80,
            "clinic_mode": "existing", "clinic_url": first.laboratory.clinic_url,
            "tts_command": first.laboratory.tts if job["mode"] == "voice" else None,
            "submit_key": first.laboratory.submit_key,
            "repetitions": job["repetitions"], "candidates": candidates,
            "scenarios": [str(path) for path in paths],
        }
        path = job_dir / "experiment.yaml"
        path.write_text(yaml.safe_dump(config, sort_keys=False), encoding="utf-8")
        return path

    def _cancelled(self, job_id: str) -> bool:
        job = self.get(job_id)
        return bool(job and job.get("cancel_requested"))

    def _set(self, job_id: str, **changes: Any) -> None:
        with self._lock:
            jobs = self._load()
            jobs[job_id].update(changes)
            self._save(jobs)


def _now() -> str:
    return datetime.now(UTC).isoformat()


def _read_manifest(path: Path) -> dict[str, Any]:
    try:
        value = json.loads((path / "manifest.json").read_text(encoding="utf-8"))
    except (FileNotFoundError, json.JSONDecodeError):
        return {}
    return value if isinstance(value, dict) else {}
