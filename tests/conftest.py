"""Shared fixtures.

`ascii_grid` is here from Day 1 so the engine tests written in Week 2 can stay
readable — layouts are drawn, not hand-encoded:

    ##########
    #S.....#E#     # wall   . floor   S spawn   E exit   B barrier   N entrance
    #S.....#.#
    ##########
"""

import pytest

from app import create_app
from app.config import TestConfig

CHAR_TO_CODE = {".": 0, "#": 1, "B": 2, "N": 3, "E": 4, "S": 5}


@pytest.fixture
def app(tmp_path):
    application = create_app(TestConfig, DATABASE_PATH=str(tmp_path / "test.db"))
    yield application


@pytest.fixture
def client(app):
    return app.test_client()


@pytest.fixture
def ascii_grid():
    """Turn a drawn layout into a venue dict."""

    def _build(text: str, name: str = "Test venue") -> dict:
        rows = [line for line in (raw.strip() for raw in text.strip().splitlines()) if line]
        width = len(rows[0])
        if any(len(row) != width for row in rows):
            raise ValueError("All rows in an ASCII grid must be the same width")
        cells = "".join(str(CHAR_TO_CODE[char]) for row in rows for char in row)
        return {"name": name, "width": width, "height": len(rows), "cells": cells}

    return _build
