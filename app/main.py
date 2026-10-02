from collections import OrderedDict
from pathlib import Path
import threading
import uuid
from fastapi import FastAPI, HTTPException, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import FileResponse, HTMLResponse, Response, JSONResponse
from fastapi.staticfiles import StaticFiles
from starlette.concurrency import run_in_threadpool
from .analysis import AnalysisRequest, Requirements, analyze
from .reports import html_report, measurement_csv
from .touchstone import MAX_BYTES, TouchstoneError, parse

ROOT = Path(__file__).resolve().parents[1]
app = FastAPI(title="RF Measurement Analyzer", version="1.0.0")
app.mount("/static", StaticFiles(directory=ROOT / "app/static"), name="static")
lock = threading.Lock()
uploads = OrderedDict()
demos = {
    name: parse(
        (ROOT / "examples" / f"filter-{name}.s2p").read_bytes(), f"filter-{name}.s2p"
    )
    for name in ("nominal", "degraded")
}
demo_hashes = {n.sha256 for n in demos.values()}


@app.exception_handler(RequestValidationError)
async def validation_error(request, exception):
    # Do not echo untrusted values such as NaN/Infinity into strict JSON.
    return JSONResponse(
        status_code=422,
        content={
            "detail": [
                {"loc": list(error["loc"]), "msg": error["msg"], "type": error["type"]}
                for error in exception.errors()
            ]
        },
    )


def get_network(identifier):
    if identifier in demos:
        return demos[identifier]
    with lock:
        if identifier not in uploads:
            raise HTTPException(
                404, "Файл больше не хранится в памяти. Загрузи его снова."
            )
        uploads.move_to_end(identifier)
        return uploads[identifier]


def metadata(identifier, network):
    return {
        "id": identifier,
        "name": network.name,
        "points": len(network.frequency),
        "source": "synthetic" if network.sha256 in demo_hashes else "uploaded",
        "range_ghz": [
            float(network.frequency[0] / 1e9),
            float(network.frequency[-1] / 1e9),
        ],
        "reference_ohm": network.reference,
        "format": network.representation,
    }


def execute(body):
    networks = [get_network(identifier) for identifier in body.dataset_ids]
    if len(networks) == 2 and networks[0].reference != networks[1].reference:
        raise HTTPException(
            422,
            "У файлов разное опорное сопротивление. Сравнение без перенормировки некорректно; экспортируй одинаковое R.",
        )
    return {
        "requirements": body.requirements.model_dump(),
        "datasets": [
            dict(
                analyze(
                    n,
                    body.requirements,
                    "synthetic" if n.sha256 in demo_hashes else "uploaded",
                ),
                id=identifier,
            )
            for identifier, n in zip(body.dataset_ids, networks)
        ],
    }


@app.get("/", response_class=HTMLResponse)
def index():
    return FileResponse(ROOT / "app/static/index.html")


@app.get("/api/health")
def health():
    return {"status": "ok", "version": "1.0.0"}


@app.get("/api/demo")
def demo():
    return {
        "datasets": [metadata(name, n) for name, n in demos.items()],
        "requirements": Requirements().model_dump(),
    }


@app.post("/api/upload", status_code=201)
async def upload(request: Request, filename: str):
    # Raw binary body avoids multipart parsing and bounds memory during receipt.
    body = bytearray()
    async for chunk in request.stream():
        if len(body) + len(chunk) > MAX_BYTES:
            raise HTTPException(413, "Файл больше 2 МиБ.")
        body.extend(chunk)

    def store():
        try:
            n = parse(bytes(body), filename)
        except TouchstoneError as exc:
            raise HTTPException(422, str(exc))
        identifier = uuid.uuid4().hex
        with lock:
            uploads[identifier] = n
            while len(uploads) > 32:
                uploads.popitem(last=False)
        return metadata(identifier, n)

    return await run_in_threadpool(store)


@app.post("/api/analyze")
def analysis(body: AnalysisRequest):
    return execute(body)


@app.post("/api/report")
def report(body: AnalysisRequest):
    return HTMLResponse(
        html_report(execute(body)),
        headers={
            "Content-Disposition": 'attachment; filename="rf-analysis-report.html"'
        },
    )


@app.get("/api/datasets/{identifier}/csv")
def csv_export(identifier: str):
    return Response(
        measurement_csv(get_network(identifier)),
        media_type="text/csv",
        headers={"Content-Disposition": 'attachment; filename="sparameters.csv"'},
    )


@app.get("/api/examples/{name}")
def example(name: str):
    if name not in demos:
        raise HTTPException(404, "Демо-файл не найден.")
    return FileResponse(
        ROOT / "examples" / f"filter-{name}.s2p",
        filename=f"filter-{name}.s2p",
        media_type="text/plain",
    )
