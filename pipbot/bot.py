"""Bot orchestrator — loads config, spawns router, wires and runs components."""

from __future__ import annotations

import asyncio
import importlib
import logging
import os
import signal
import sys
import time

import yaml

from pipbot.component import BoundPort, Component, _PortDescriptor

log = logging.getLogger("pipbot")


class Bot:
    """Main entry point for a pipbot project.

    Typical usage in a user's main.py::

        from pipbot import Bot
        Bot().run()
    """

    def __init__(self, config: str | None = None):
        self.config_path = (
            config
            or os.environ.get("PIPBOT_CONFIG")
            or "config.yaml"
        )
        self._router_proc: asyncio.subprocess.Process | None = None
        self._components: dict[str, Component] = {}

    def run(self):
        """Blocking call — boots the router, starts all components."""
        try:
            asyncio.run(self._run())
        except KeyboardInterrupt:
            pass

    # ------------------------------------------------------------------
    # Main async lifecycle
    # ------------------------------------------------------------------

    async def _run(self):
        config = self._load_config()

        router_cfg = config.get("router", {})
        host = router_cfg.get("host", "localhost")
        port = router_cfg.get("port", 5555)

        self._router_proc = await self._start_router(host, port)

        try:
            await self._wait_for_router(host, port)
        except RuntimeError:
            if self._router_proc.returncode is None:
                self._router_proc.terminate()
            raise

        comp_configs = config.get("components") or {}
        self._components = self._load_components(comp_configs)

        for comp_name, comp in self._components.items():
            wiring = comp_configs[comp_name].get("wiring", {})
            self._wire_ports(comp, wiring)
            await comp._connect(host, port, comp_name)
            comp._start_message_reader()

        log.info("All components connected — starting")
        await self._run_components()

    # ------------------------------------------------------------------
    # Config
    # ------------------------------------------------------------------

    def _load_config(self) -> dict:
        path = os.path.abspath(self.config_path)
        if not os.path.isfile(path):
            raise FileNotFoundError(f"Config not found: {path}")
        with open(path) as f:
            config = yaml.safe_load(f)
        return config if isinstance(config, dict) else {}

    # ------------------------------------------------------------------
    # Router subprocess
    # ------------------------------------------------------------------

    async def _start_router(self, host: str, port: int):
        proc = await asyncio.create_subprocess_exec(
            sys.executable, "-m", "pipbot.router",
            "--host", host,
            "--port", str(port),
        )
        log.info("Router started (PID %s)", proc.pid)
        return proc

    async def _wait_for_router(self, host: str, port: int,
                               timeout: float = 10.0):
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            if self._router_proc.returncode is not None:
                raise RuntimeError(
                    f"Router exited with code {self._router_proc.returncode}"
                )
            try:
                r, w = await asyncio.open_connection(host, port)
                w.close()
                await w.wait_closed()
                log.info("Router is ready on %s:%s", host, port)
                return
            except (ConnectionRefusedError, OSError):
                await asyncio.sleep(0.1)
        raise RuntimeError(f"Router not ready after {timeout}s")

    # ------------------------------------------------------------------
    # Component loading and wiring
    # ------------------------------------------------------------------

    def _load_components(self, comp_configs: dict) -> dict[str, Component]:
        components: dict[str, Component] = {}
        for comp_name, cfg in comp_configs.items():
            module_path = cfg["module"]
            class_name = cfg["class"]

            mod = importlib.import_module(module_path)
            cls = getattr(mod, class_name)

            if not (isinstance(cls, type) and issubclass(cls, Component)):
                raise TypeError(
                    f"'{class_name}' from '{module_path}' "
                    "must subclass pipbot.Component"
                )

            components[comp_name] = cls()
        return components

    @staticmethod
    def _wire_ports(component: Component, wiring: dict[str, str]):
        ports = component._get_ports()
        for port_name, descriptor in ports.items():
            if port_name not in wiring:
                raise ValueError(
                    f"Port '{port_name}' on {type(component).__name__} "
                    "has no path in config.yaml wiring"
                )
            path = wiring[port_name]
            if not path.startswith(descriptor.prefix):
                raise ValueError(
                    f"Port '{port_name}' expects prefix '{descriptor.prefix}', "
                    f"got '{path}'"
                )
            component._bound_ports[port_name] = BoundPort(path, descriptor.mode)

    # ------------------------------------------------------------------
    # Running
    # ------------------------------------------------------------------

    async def _run_components(self):
        loop = asyncio.get_running_loop()
        stop_event = asyncio.Event()

        try:
            for sig in (signal.SIGINT, signal.SIGTERM):
                loop.add_signal_handler(sig, stop_event.set)
        except NotImplementedError:
            pass  # Windows — KeyboardInterrupt will propagate instead

        tasks = {
            name: asyncio.create_task(comp.start(), name=name)
            for name, comp in self._components.items()
        }

        if not tasks:
            log.info("No components to run — waiting for signal")
            await stop_event.wait()
        else:
            waiter = asyncio.create_task(stop_event.wait())
            done, _ = await asyncio.wait(
                [*tasks.values(), waiter],
                return_when=asyncio.FIRST_COMPLETED,
            )
            waiter.cancel()
            for t in done - {waiter}:
                if t.exception():
                    log.error("Component '%s' crashed: %s",
                              t.get_name(), t.exception())

        await self._shutdown()

    async def _shutdown(self):
        log.info("Shutting down")

        for name, comp in self._components.items():
            try:
                await asyncio.wait_for(comp.stop(), timeout=5.0)
            except Exception as exc:
                log.error("Error stopping '%s': %s", name, exc)
            await comp._shutdown()

        if self._router_proc and self._router_proc.returncode is None:
            self._router_proc.terminate()
            try:
                await asyncio.wait_for(
                    self._router_proc.wait(), timeout=5.0,
                )
            except asyncio.TimeoutError:
                self._router_proc.kill()

        log.info("Shutdown complete")
