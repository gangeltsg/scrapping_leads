import uuid
import threading
import json
import os
from fastapi import FastAPI, Request, HTTPException
from fastapi.responses import HTMLResponse, JSONResponse
from fastapi.templating import Jinja2Templates
from pydantic import BaseModel
from scraper import scrape_domains
from f5bot import monitor_keywords

app = FastAPI()
templates = Jinja2Templates(directory="templates")

# File-based job store — works across multiple gunicorn workers
_JOBS_DIR = os.path.join(os.environ.get("TMPDIR", "/tmp"), "scraper_jobs")
os.makedirs(_JOBS_DIR, exist_ok=True)


def _job_path(job_id: str) -> str:
    return os.path.join(_JOBS_DIR, f"{job_id}.json")


def _get_job(job_id: str) -> dict | None:
    try:
        with open(_job_path(job_id)) as f:
            return json.load(f)
    except FileNotFoundError:
        return None


def _save_job(job_id: str, data: dict) -> None:
    path = _job_path(job_id)
    tmp = path + ".tmp"
    with open(tmp, "w") as f:
        json.dump(data, f)
    os.replace(tmp, path)  # atomic write


def _update_job(job_id: str, **kwargs) -> None:
    job = _get_job(job_id) or {}
    job.update(kwargs)
    _save_job(job_id, job)


@app.get("/", response_class=HTMLResponse)
async def index(request: Request):
    return templates.TemplateResponse(request=request, name="index.html")


class ScrapeRequest(BaseModel):
    domains: list[str] = []
    keywords: list[str] = []


@app.post("/api/scrape")
async def start_scrape(data: ScrapeRequest):
    raw_domains: list[str] = [
        d.strip() for d in data.domains if d.strip()
    ]
    raw_keywords: list[str] = [
        k.strip().lower() for k in data.keywords if k.strip()
    ]

    if not raw_domains:
        raise HTTPException(status_code=400, detail="Debes ingresar al menos un dominio.")
    if not raw_keywords:
        raise HTTPException(status_code=400, detail="Debes ingresar al menos un keyword.")

    job_id = str(uuid.uuid4())
    _save_job(job_id, {"status": "running", "results": [], "errors": []})

    thread = threading.Thread(
        target=_run_job, args=(job_id, raw_domains, raw_keywords), daemon=True
    )
    thread.start()

    return JSONResponse(content={"job_id": job_id}, status_code=202)


def _run_job(job_id: str, domains: list[str], keywords: list[str]) -> None:
    try:
        results, errors = scrape_domains(domains, keywords)
        _update_job(job_id, results=results, errors=errors, status="done")
    except Exception as exc:  # noqa: BLE001
        job = _get_job(job_id) or {}
        job["status"] = "error"
        job.setdefault("errors", []).append(str(exc))
        _save_job(job_id, job)


@app.get("/api/status/{job_id}")
async def job_status(job_id: str):
    job = _get_job(job_id)
    if not job:
        raise HTTPException(status_code=404, detail="Job no encontrado.")
    return job


# ── F5Bot: Reddit / Hacker News monitoring ───────────────────────

class MonitorRequest(BaseModel):
    keywords: list[str] = []
    sources: list[str] = ["reddit", "hn"]
    reddit_limit: int = 25
    hn_limit: int = 15


@app.post("/api/monitor")
async def start_monitor(data: MonitorRequest):
    raw_keywords: list[str] = [
        k.strip() for k in data.keywords if k.strip()
    ]
    sources: list[str] = [
        s for s in data.sources if s in ("reddit", "hn")
    ]

    if not raw_keywords:
        raise HTTPException(status_code=400, detail="Debes ingresar al menos un keyword.")
    if not sources:
        raise HTTPException(status_code=400, detail="Selecciona al menos una fuente (Reddit o HN).")

    reddit_limit = min(data.reddit_limit, 100)
    hn_limit = min(data.hn_limit, 50)

    job_id = str(uuid.uuid4())
    _save_job(job_id, {"status": "running", "results": [], "errors": [], "type": "monitor"})

    thread = threading.Thread(
        target=_run_monitor_job,
        args=(job_id, raw_keywords, sources, reddit_limit, hn_limit),
        daemon=True,
    )
    thread.start()

    return JSONResponse(content={"job_id": job_id}, status_code=202)


def _run_monitor_job(
    job_id: str,
    keywords: list[str],
    sources: list[str],
    reddit_limit: int,
    hn_limit: int,
) -> None:
    try:
        results, errors = monitor_keywords(
            keywords, sources=sources,
            reddit_limit=reddit_limit, hn_limit=hn_limit,
        )
        _update_job(job_id, results=results, errors=errors, status="done")
    except Exception as exc:  # noqa: BLE001
        job = _get_job(job_id) or {}
        job["status"] = "error"
        job.setdefault("errors", []).append(str(exc))
        _save_job(job_id, job)


if __name__ == "__main__":
    import uvicorn
    port = int(os.environ.get("PORT", 8001))
    uvicorn.run("app:app", host="0.0.0.0", port=port, reload=False)
