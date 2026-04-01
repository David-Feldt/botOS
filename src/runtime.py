"""Runtime — starts router, compiles C components, launches all as subprocesses."""

from __future__ import annotations

import asyncio
import json
import logging
import os
import shutil
import subprocess
import sys
import time

import config as _config

log = logging.getLogger("bot")


class Runtime:
    def __init__(self, config_path: str = "config.yaml", group: str | None = None):
        self.config_path = config_path
        self.group = group
        self._router_proc: asyncio.subprocess.Process | None = None
        self._component_procs: list[tuple[str, asyncio.subprocess.Process]] = []

    def run(self):
        try:
            asyncio.run(self._run())
        except KeyboardInterrupt:
            pass

    async def _run(self):
        cfg = _config.load(self.config_path)
        project_dir = os.path.dirname(os.path.abspath(self.config_path))

        router_cfg = cfg.get("router", {})
        host = router_cfg.get("host", "localhost")
        port = router_cfg.get("port", 5555)

        self._router_proc = await self._start_router(host, port)
        await self._wait_for_router(host, port)

        comp_configs = cfg.get("components") or {}

        if self.group:
            comp_configs = {
                name: c for name, c in comp_configs.items()
                if self.group in c.get("groups", [])
            }

        src_dir = os.path.dirname(os.path.abspath(__file__))
        vendor_dir = os.path.join(src_dir, "vendor")
        botos_h_dir = os.path.join(src_dir, "botos_c")
        bin_dir = os.path.join(project_dir, ".bot", "bin")
        os.makedirs(bin_dir, exist_ok=True)

        # check requirements and filter out components that can't run
        runnable = {}
        for name, comp_cfg in comp_configs.items():
            missing = [r for r in comp_cfg.get("requires", []) if not shutil.which(r)]
            if missing:
                log.warning("Skipping '%s' — missing: %s", name, ", ".join(missing))
            else:
                runnable[name] = comp_cfg
        comp_configs = runnable

        # compile C/C++ components first
        executables: dict[str, str] = {}
        for name, comp_cfg in comp_configs.items():
            file_path = os.path.join(project_dir, comp_cfg["file"])
            if file_path.endswith((".c", ".cpp")):
                executables[name] = self._compile(name, file_path, botos_h_dir, bin_dir)

        # launch all components as subprocesses
        for name, comp_cfg in comp_configs.items():
            file_path = os.path.join(project_dir, comp_cfg["file"])
            channels = comp_cfg.get("channels", {})

            env = os.environ.copy()
            env["BOTOS_ROUTER_HOST"] = host
            env["BOTOS_ROUTER_PORT"] = str(port)
            env["BOTOS_COMPONENT_NAME"] = name
            env["BOTOS_CHANNELS"] = json.dumps(channels)
            env["PYTHONPATH"] = f"{vendor_dir}:{src_dir}:" + env.get("PYTHONPATH", "")

            venv_python = os.path.join(project_dir, ".bot", "venv", "bin", "python")
            python = venv_python if os.path.isfile(venv_python) else sys.executable

            if name in executables:
                proc = await asyncio.create_subprocess_exec(executables[name], env=env)
            else:
                proc = await asyncio.create_subprocess_exec(python, file_path, env=env)

            log.info("Started component '%s' (PID %s)", name, proc.pid)
            self._component_procs.append((name, proc))

        if not self._component_procs:
            log.info("No components defined — waiting for signal")
            try:
                await asyncio.Event().wait()
            except asyncio.CancelledError:
                pass
        else:
            tasks = [
                asyncio.create_task(proc.wait(), name=name)
                for name, proc in self._component_procs
            ]
            done, pending = await asyncio.wait(tasks, return_when=asyncio.FIRST_COMPLETED)
            for t in pending:
                t.cancel()
            for t in done:
                code = t.result()
                if code != 0:
                    log.error("Component '%s' exited with code %s", t.get_name(), code)

        await self._shutdown()

    def _compile(self, name: str, file_path: str, botos_h_dir: str, bin_dir: str) -> str:
        exe = os.path.join(bin_dir, name)
        compiler = "g++" if file_path.endswith(".cpp") else "gcc"
        cmd = [compiler, file_path, f"-I{botos_h_dir}", "-o", exe]
        log.info("Compiling '%s'...", file_path)
        result = subprocess.run(cmd, capture_output=True, text=True)
        if result.returncode != 0:
            raise RuntimeError(f"Compile failed for '{name}':\n{result.stderr}")
        log.info("Compiled '%s' -> %s", name, exe)
        return exe

    async def _start_router(self, host: str, port: int):
        src_dir = os.path.dirname(os.path.abspath(__file__))
        vendor_dir = os.path.join(src_dir, "vendor")
        env = os.environ.copy()
        env["PYTHONPATH"] = f"{vendor_dir}:{src_dir}:" + env.get("PYTHONPATH", "")
        proc = await asyncio.create_subprocess_exec(
            sys.executable, "-c",
            f"import asyncio; from router import Router; asyncio.run(Router(host='{host}', port={port}).start())",
            env=env,
        )
        log.info("Router started (PID %s)", proc.pid)
        return proc

    async def _wait_for_router(self, host: str, port: int, timeout: float = 10.0):
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            if self._router_proc.returncode is not None:
                raise RuntimeError(f"Router exited with code {self._router_proc.returncode}")
            try:
                r, w = await asyncio.open_connection(host, port)
                w.close()
                await w.wait_closed()
                log.info("Router ready on %s:%s", host, port)
                return
            except (ConnectionRefusedError, OSError):
                await asyncio.sleep(0.1)
        raise RuntimeError(f"Router not ready after {timeout}s")

    async def _shutdown(self):
        log.info("Shutting down")
        for name, proc in self._component_procs:
            if proc.returncode is None:
                proc.terminate()
                try:
                    await asyncio.wait_for(proc.wait(), timeout=5.0)
                except asyncio.TimeoutError:
                    proc.kill()

        if self._router_proc and self._router_proc.returncode is None:
            self._router_proc.terminate()
            try:
                await asyncio.wait_for(self._router_proc.wait(), timeout=5.0)
            except asyncio.TimeoutError:
                self._router_proc.kill()

        log.info("Shutdown complete")
