import asyncio
import os
import shutil
from pathlib import Path
from uuid import uuid4

from fastapi import FastAPI, HTTPException
from fastapi.responses import FileResponse
from pydantic import BaseModel

app = FastAPI()

EXECUTOR_IMAGE = "atlas-sandbox:latest"
EXECUTION_TIMEOUT = 120
OUTPUT_BASE = Path("/sandbox_outputs")
SANDBOX_OUTPUT_VOLUME = os.environ.get(
    "SANDBOX_OUTPUT_VOLUME", "atlas-platform-services_sandbox_outputs"
)


class ExecuteRequest(BaseModel):
    code: str


class JobResult(BaseModel):
    status: str = "pending"
    stdout: str = ""
    stderr: str = ""
    exit_code: int = 0
    output_files: list[str] = []


jobs: dict[str, JobResult] = {}


async def _run_in_container(job_id: str, code: str):
    output_dir = OUTPUT_BASE / job_id
    output_dir.mkdir(parents=True, exist_ok=True)

    wrapped_code = (
        "import os\n"
        "OUTPUT_DIR = os.environ.get('OUTPUT_DIR', '/tmp')\n\n"
        f"{code}"
    )

    cmd = [
        "docker", "run", "--rm",
        "--network", "none",
        "--read-only",
        "--tmpfs", "/tmp:rw,noexec,size=64m",
        "--memory", "256m",
        "--cpus", "0.5",
        "--ulimit", "nproc=64",
        "-v", f"{SANDBOX_OUTPUT_VOLUME}:/sandbox_outputs",
        "-e", f"OUTPUT_DIR=/sandbox_outputs/{job_id}",
        EXECUTOR_IMAGE,
        "python3", "-c", wrapped_code,
    ]

    proc = await asyncio.create_subprocess_exec(
        *cmd,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
    )

    try:
        stdout, stderr = await asyncio.wait_for(
            proc.communicate(), timeout=EXECUTION_TIMEOUT
        )
        output_files = [f.name for f in output_dir.iterdir() if f.is_file()]
        jobs[job_id] = JobResult(
            status="complete",
            stdout=stdout.decode(),
            stderr=stderr.decode(),
            exit_code=proc.returncode or 0,
            output_files=output_files,
        )
    except asyncio.TimeoutError:
        proc.kill()
        await proc.communicate()
        jobs[job_id] = JobResult(
            status="complete",
            stdout="",
            stderr=f"Execution timed out after {EXECUTION_TIMEOUT} seconds.",
            exit_code=124,
        )


@app.get("/health")
async def health():
    return {"status": "ok"}


@app.post("/execute")
async def execute(req: ExecuteRequest) -> dict:
    job_id = str(uuid4())
    jobs[job_id] = JobResult(status="pending")
    asyncio.create_task(_run_in_container(job_id, req.code))
    return {"job_id": job_id}


@app.get("/result/{job_id}", response_model=JobResult)
async def result(job_id: str) -> JobResult:
    if job_id not in jobs:
        raise HTTPException(status_code=404, detail="Job not found.")
    return jobs[job_id]


@app.get("/files/{job_id}/{filename}")
async def get_file(job_id: str, filename: str) -> FileResponse:
    file_path = OUTPUT_BASE / job_id / filename

    if not file_path.is_file():
        raise HTTPException(status_code=404, detail="File not found.")

    return FileResponse(file_path)


@app.delete("/result/{job_id}")
async def cleanup(job_id: str):
    jobs.pop(job_id, None)
    shutil.rmtree(OUTPUT_BASE / job_id, ignore_errors=True)
