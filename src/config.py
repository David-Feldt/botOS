"""Loads and validates config.yaml."""

import os
import yaml


def load(path: str = "config.yaml") -> dict:
    path = os.path.abspath(path)
    if not os.path.isfile(path):
        raise FileNotFoundError(f"Config not found: {path}")
    with open(path) as f:
        data = yaml.safe_load(f)
    return data if isinstance(data, dict) else {}
