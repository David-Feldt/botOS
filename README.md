# botOS

A framework for building modular robotics software on Raspberry Pi.

Components communicate through typed channels over a central TCP router.
You declare channels in `config.yaml` and `bot run` handles the rest.

## Install

```bash
./install.sh
```

This installs to `/opt/bot`, links the `bot` command, and sets up shell integration (pip interception, `bot .` shorthand).

## Quickstart

```bash
bot init myrobot
cd myrobot
```

This creates:

```
myrobot/
├── config.yaml          # declares components and wiring
├── components/
│   ├── __init__.py
│   └── example.py       # sample component
└── .botos/              # venv, build artifacts (gitignored)
```

### Write a component

```python
import asyncio
import botos


async def main():
    counter = 0
    while True:
        await botos.publish("/s/example/data", {"count": counter})
        counter += 1
        await asyncio.sleep(1.0)


if __name__ == "__main__":
    botos.run(main())
```

### Wire it in config.yaml

```yaml
router:
  host: localhost
  port: 5555

components:
  example:
    file: components/example.py
    groups: [sensors]
    channels:
      /s/example/data: write
```

### Run

```bash
bot run            # run all components
bot run sensors    # run only a specific group
```

## Installing Python packages

When you run `pip install` inside a botOS project, the shell integration will prompt you to install into the project's own environment (`.botos/venv/`). Components automatically use this environment.

## Channel types

| Prefix | Type    | Pattern                            |
|--------|---------|------------------------------------|
| `/s/`  | Sensor  | 1 writer (producer), many readers  |
| `/c/`  | Command | 1 reader (receiver), many writers  |

## CLI

| Command         | Description                          |
|-----------------|--------------------------------------|
| `bot init`      | Scaffold a new project               |
| `bot run`       | Boot the router and run components   |
| `bot run group` | Run only components in a group       |
| `bot .`         | Reload shell setup                   |
