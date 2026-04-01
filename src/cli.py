"""CLI entry point — registered as the `bot` command."""

from __future__ import annotations

import argparse
import logging
import os
import sys
import textwrap

CONFIG_TEMPLATE = textwrap.dedent("""\
    robot:
      name: {name}

    router:
      host: localhost
      port: 5555

    components:
      # example:
      #   file: components/example.py
      #   channels:
      #     /s/example/data: write
""")

EXAMPLE_COMPONENT = textwrap.dedent("""\
    import asyncio
    import bot


    async def main():
        counter = 0
        while True:
            await bot.publish("/s/example/data", {{"count": counter}})
            counter += 1
            await asyncio.sleep(1.0)


    if __name__ == "__main__":
        bot.run(main())
""")

GITIGNORE_TEMPLATE = textwrap.dedent("""\
    .bot/
    __pycache__/
    *.pyc
""")


def cmd_init(args):
    name = args.name
    if name == ".":
        project_dir = os.getcwd()
        name = os.path.basename(project_dir)
    else:
        project_dir = os.path.join(os.getcwd(), name)
        os.makedirs(project_dir, exist_ok=True)

    def _write_if_missing(rel_path: str, content: str):
        full = os.path.join(project_dir, rel_path)
        if os.path.exists(full):
            print(f"  skip    {rel_path}")
            return
        os.makedirs(os.path.dirname(full) or project_dir, exist_ok=True)
        with open(full, "w") as f:
            f.write(content)
        print(f"  create  {rel_path}")

    print(f"Initializing project '{name}' in {project_dir}")
    _write_if_missing("config.yaml", CONFIG_TEMPLATE.format(name=name))
    _write_if_missing("components/__init__.py", "")
    _write_if_missing("components/example.py", EXAMPLE_COMPONENT)
    _write_if_missing(".gitignore", GITIGNORE_TEMPLATE)

    print(f"\nDone. Edit config.yaml to define your components, then run: bot run")


def cmd_run(args):
    config_path = os.path.abspath(args.config)
    project_dir = os.path.dirname(config_path)

    if project_dir not in sys.path:
        sys.path.insert(0, project_dir)
    os.chdir(project_dir)

    from runtime import Runtime
    Runtime(config_path=config_path, group=args.group).run()


def main():
    parser = argparse.ArgumentParser(prog="bot", description="botOS — modular robotics framework")
    sub = parser.add_subparsers(dest="command")

    p_init = sub.add_parser("init", help="Scaffold a new project")
    p_init.add_argument("name", nargs="?", default=".", help="Project name (default: current directory)")

    p_run = sub.add_parser("run", help="Run the project")
    p_run.add_argument("group", nargs="?", default=None, help="Only run components in this group")
    p_run.add_argument("--config", default="config.yaml", help="Path to config.yaml")

    args = parser.parse_args()

    if args.command is None:
        parser.print_help()
        sys.exit(1)

    logging.basicConfig(level=logging.INFO, format="%(name)s | %(levelname)s | %(message)s")

    {"init": cmd_init, "run": cmd_run}[args.command](args)


if __name__ == "__main__":
    main()
