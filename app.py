import uuid
import threading
from flask import Flask, render_template, request, jsonify
from scraper import scrape_domains
from f5bot import monitor_keywords

app = Flask(__name__)

# In-memory job store { job_id: { status, results, errors } }
jobs: dict = {}


@app.route("/")
def index():
    return render_template("index.html")


@app.route("/api/scrape", methods=["POST"])
def start_scrape():
    data = request.get_json(force=True)

    raw_domains: list[str] = [
        d.strip() for d in data.get("domains", []) if d.strip()
    ]
    raw_keywords: list[str] = [
        k.strip().lower() for k in data.get("keywords", []) if k.strip()
    ]

    if not raw_domains:
        return jsonify({"error": "Debes ingresar al menos un dominio."}), 400
    if not raw_keywords:
        return jsonify({"error": "Debes ingresar al menos un keyword."}), 400

    job_id = str(uuid.uuid4())
    jobs[job_id] = {"status": "running", "results": [], "errors": []}

    thread = threading.Thread(
        target=_run_job, args=(job_id, raw_domains, raw_keywords), daemon=True
    )
    thread.start()

    return jsonify({"job_id": job_id}), 202


def _run_job(job_id: str, domains: list[str], keywords: list[str]) -> None:
    try:
        results, errors = scrape_domains(domains, keywords)
        jobs[job_id]["results"] = results
        jobs[job_id]["errors"] = errors
        jobs[job_id]["status"] = "done"
    except Exception as exc:  # noqa: BLE001
        jobs[job_id]["status"] = "error"
        jobs[job_id]["errors"].append(str(exc))


@app.route("/api/status/<job_id>")
def job_status(job_id: str):
    job = jobs.get(job_id)
    if not job:
        return jsonify({"error": "Job no encontrado."}), 404
    return jsonify(job)


# ── F5Bot: Reddit / Hacker News monitoring ───────────────────────

@app.route("/api/monitor", methods=["POST"])
def start_monitor():
    data = request.get_json(force=True)

    raw_keywords: list[str] = [
        k.strip() for k in data.get("keywords", []) if k.strip()
    ]
    sources: list[str] = [
        s for s in data.get("sources", ["reddit", "hn"])
        if s in ("reddit", "hn")
    ]

    if not raw_keywords:
        return jsonify({"error": "Debes ingresar al menos un keyword."}), 400
    if not sources:
        return jsonify({"error": "Selecciona al menos una fuente (Reddit o HN)."}), 400

    reddit_limit = min(int(data.get("reddit_limit", 25)), 100)
    hn_limit = min(int(data.get("hn_limit", 15)), 50)

    job_id = str(uuid.uuid4())
    jobs[job_id] = {"status": "running", "results": [], "errors": [], "type": "monitor"}

    thread = threading.Thread(
        target=_run_monitor_job,
        args=(job_id, raw_keywords, sources, reddit_limit, hn_limit),
        daemon=True,
    )
    thread.start()

    return jsonify({"job_id": job_id}), 202


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
        jobs[job_id]["results"] = results
        jobs[job_id]["errors"] = errors
        jobs[job_id]["status"] = "done"
    except Exception as exc:  # noqa: BLE001
        jobs[job_id]["status"] = "error"
        jobs[job_id]["errors"].append(str(exc))


if __name__ == "__main__":
    app.run(debug=True, port=5000)
