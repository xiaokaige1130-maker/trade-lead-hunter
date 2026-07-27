#!/usr/bin/env bash
cd "$(dirname "$0")"
export PYTHONPATH="$PWD:$PYTHONPATH"
exec .venv/bin/uvicorn app.main:app --host 127.0.0.1 --port 8866 --reload
