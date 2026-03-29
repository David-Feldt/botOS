"""CLI entry point — registered as the ``bot`` console script."""

from __future__ import annotations

import argparse
import logging
import os
import sys
import textwrap

# ── templates ────────────────────────────────────────────────────────

CONFIG_TEMPLATE = textwrap.dedent("""\
    router:
      host: localhost
      port: 5555

    components:
      # example_sensor:
      #   module: components.my_sensor
      #   class: MySensor
      #   wiring:
      #     data_out: /s/sensor/data
      #
      # example_actuator:
      #   module: components.my_actuator
      #   class: MyActuator
      #   wiring:
      #     command_in: /c/actuator/cmd
""")

MAIN_TEMPLATE = textwrap.dedent("""\
    from pipbot import Bot

    bot = Bot()

    if __name__ == "__main__":
        bot.run()
""")

EXAMPLE_COMPONENT = textwrap.dedent("""\
    import asyncio
    from pipbot import Component, SensorPort, CommandPort


    class ExampleSensor(Component):
        \"\"\"Produces sensor data on a timer.\"\"\"

        data_out = SensorPort()  # mode='write' by default

        async def start(self):
            counter = 0
            while True:
                await self.data_out.write({"count": counter})
                counter += 1
                await asyncio.sleep(1.0)


    class ExampleActuator(Component):
        \"\"\"Receives commands and prints them.\"\"\"

        command_in = CommandPort()  # mode='read' by default

        async def start(self):
            async for cmd in self.command_in:
                print(f"Received command: {cmd}")
""")

GITIGNORE_TEMPLATE = textwrap.dedent("""\
    .bot/
    __pycache__/
    *.pyc
""")


# ── commands ─────────────────────────────────────────────────────────

def cmd_init(args):
    name = args.name
    if name == ".":
        project_dir = os.getcwd()
    else:
        project_dir = os.path.join(os.getcwd(), name)
        os.makedirs(project_dir, exist_ok=True)

    def _write_if_missing(rel_path: str, content: str):
        full = os.path.join(project_dir, rel_path)
        if os.path.exists(full):
            print(f"  skip  {rel_path}  (already exists)")
            return
        os.makedirs(os.path.dirname(full) or project_dir, exist_ok=True)
        with open(full, "w") as f:
            f.write(content)
        print(f"  create  {rel_path}")

    print(f"Initializing project in {project_dir}")
    _write_if_missing("config.yaml", CONFIG_TEMPLATE)
    _write_if_missing("main.py", MAIN_TEMPLATE)
    _write_if_missing("components/__init__.py", "")
    _write_if_missing("components/example.py", EXAMPLE_COMPONENT)
    _write_if_missing(".gitignore", GITIGNORE_TEMPLATE)

    for subdir in ("build", "cache", "logs"):
        path = os.path.join(project_dir, ".bot", subdir)
        os.makedirs(path, exist_ok=True)

    print("Done. Edit config.yaml to wire your components, then run: bot run")


def cmd_run(args):
    config_path = os.path.abspath(args.config)
    project_dir = os.path.dirname(config_path) or os.getcwd()

    if project_dir not in sys.path:
        sys.path.insert(0, project_dir)
    os.chdir(project_dir)

    os.environ["PIPBOT_CONFIG"] = config_path

    main_path = os.path.abspath(args.main)
    if os.path.isfile(main_path):
        import runpy
        runpy.run_path(main_path, run_name="__main__")
    else:
        from pipbot.bot import Bot
        Bot(config=config_path).run()


# ── main ─────────────────────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser(
        prog="bot",
        description="pipbot — modular robotics framework",
    )
    sub = parser.add_subparsers(dest="command")

    # bot init
    p_init = sub.add_parser("init", help="Scaffold a new project")
    p_init.add_argument(
        "name", nargs="?", default=".",
        help="Project directory name (default: current directory)",
    )

    # bot run
    p_run = sub.add_parser("run", help="Build and run the project")
    p_run.add_argument(
        "--config", default="config.yaml",
        help="Path to config.yaml (default: config.yaml)",
    )
    p_run.add_argument(
        "--main", default="main.py",
        help="Path to main.py entry point (default: main.py)",
    )

    args = parser.parse_args()

    if args.command is None:
        parser.print_help()
        sys.exit(1)

    logging.basicConfig(
        level=logging.INFO,
        format="%(name)s | %(levelname)s | %(message)s",
    )

    dispatch = {
        "init": cmd_init,
        "run": cmd_run,
    }
    dispatch[args.command](args)


if __name__ == "__main__":
    main()
