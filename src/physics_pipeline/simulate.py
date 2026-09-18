"""Thin EnergyPlus runner + scoped-output helpers, matching the
configuration Step 0.5's storage/runtime estimate was measured against: a
short time window (not a full annual run) with a small, targeted set of
hourly output variables rather than full sub-hourly detail on everything.
"""

from __future__ import annotations

import shutil
import subprocess
from dataclasses import dataclass
from pathlib import Path

import openstudio

DEFAULT_OUTPUT_VARIABLES: tuple[str, ...] = (
    "Zone Mean Air Temperature",
    "System Node Mass Flow Rate",
    "System Node Temperature",
    "System Node Setpoint Temperature",
    "Fan Electricity Rate",
    "Cooling Coil Total Cooling Rate",
    "Heating Coil Heating Rate",
    "Zone Thermostat Heating Setpoint Temperature",
    "Zone Thermostat Cooling Setpoint Temperature",
)


def set_scoped_output(model: "openstudio.model.Model", begin_month: int, begin_day: int,
                       end_month: int, end_day: int,
                       variables: tuple[str, ...] = DEFAULT_OUTPUT_VARIABLES) -> None:
    rp = model.getRunPeriod()
    rp.setBeginMonth(begin_month)
    rp.setBeginDayOfMonth(begin_day)
    rp.setEndMonth(end_month)
    rp.setEndDayOfMonth(end_day)
    for v in variables:
        openstudio.model.OutputVariable(v, model).setReportingFrequency("Hourly")


@dataclass
class SimulationResult:
    success: bool
    severe_error_count: int
    warning_count: int
    runtime_seconds: float | None
    output_dir: Path
    err_tail: str


def run_energyplus(idf_path: Path, weather_path: Path, output_dir: Path,
                    energyplus_bin: Path, idd_path: Path, timeout_s: int = 120) -> SimulationResult:
    output_dir.mkdir(parents=True, exist_ok=True)
    proc = subprocess.run(
        [str(energyplus_bin), "--weather", str(weather_path), "--output-directory", str(output_dir),
         "--idd", str(idd_path), str(idf_path)],
        capture_output=True, text=True, timeout=timeout_s,
    )
    err_path = output_dir / "eplusout.err"
    severe = 0
    warnings = 0
    runtime = None
    tail = ""
    if err_path.exists():
        text = err_path.read_text(errors="replace")
        tail = "\n".join(text.splitlines()[-15:])
        for line in text.splitlines():
            if "Severe" in line and "*************" in line and "Summary" not in line:
                severe += 1
        for line in text.splitlines():
            if line.strip().startswith("************* EnergyPlus Completed Successfully"):
                # e.g. "...Successfully-- 23 Warning; 0 Severe Errors; Elapsed Time=00hr 00min  0.42sec"
                parts = line.split("--", 1)[-1]
                try:
                    warnings = int(parts.strip().split("Warning")[0].strip())
                    severe = int(parts.split(";")[1].strip().split("Severe")[0].strip())
                except (IndexError, ValueError):
                    pass
                try:
                    time_part = parts.split("Elapsed Time=")[-1].strip()
                    h, m, s = time_part.replace("hr", "").replace("min", "").replace("sec", "").split()
                    runtime = int(h) * 3600 + int(m) * 60 + float(s)
                except (IndexError, ValueError):
                    pass
    success = proc.returncode == 0 and (output_dir / "eplusout.sql").exists() and severe == 0
    return SimulationResult(
        success=success,
        severe_error_count=severe,
        warning_count=warnings,
        runtime_seconds=runtime,
        output_dir=output_dir,
        err_tail=tail,
    )


def save_workspace_as_idf(workspace: "openstudio.Workspace", path: Path) -> None:
    workspace.save(openstudio.path(str(path)), True)


def forward_translate(model: "openstudio.model.Model") -> "openstudio.Workspace":
    ft = openstudio.energyplus.ForwardTranslator()
    ws = ft.translateModel(model)
    errs = ft.errors()
    if errs:
        raise RuntimeError(f"forward translation errors: {[e.logMessage() for e in errs]}")
    return ws


def clear_dir(path: Path) -> None:
    if path.exists():
        shutil.rmtree(path)
