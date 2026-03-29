# pipbot

A framework for building modular robotics software on Raspberry Pi.

Components communicate through typed channels over a central TCP router.
You declare ports on your classes, wire them to paths in `config.yaml`,
and `bot run` handles the rest.

## Install

```bash
pip install -e .
```

## Quickstart

```bash
bot init myrobot
cd myrobot
```

This creates:

```
myrobot/
├── config.yaml          # declares components and wiring
├── main.py              # entry point
├── components/
│   ├── __init__.py
│   └── example.py       # sample sensor + actuator
└── .bot/                # build artifacts and logs (gitignored)
```

### Write a component

```python
import asyncio
from pipbot import Component, SensorPort

class Thermometer(Component):
    temperature = SensorPort()  # produces sensor data

    async def start(self):
        while True:
            reading = await self.read_sensor()
            await self.temperature.write({"celsius": reading})
            await asyncio.sleep(1.0)
```

### Wire it in config.yaml

```yaml
router:
  host: localhost
  port: 5555

components:
  therm:
    module: components.thermometer
    class: Thermometer
    wiring:
      temperature: /s/temperature/reading
```

### Run

```bash
bot run
```

## Channel types

| Prefix | Type    | Pattern                            |
|--------|---------|------------------------------------|
| `/s/`  | Sensor  | 1 writer (producer), many readers  |
| `/c/`  | Command | 1 reader (receiver), many writers  |

## CLI

| Command    | Description                          |
|------------|--------------------------------------|
| `bot init` | Scaffold a new project               |
| `bot run`  | Boot the router and run components   |
