"""Run with python -m fieldfox_recording inspect|export."""
from __future__ import annotations

import argparse
import json
import sys
from .parser import FieldFoxRecording, RecordingError, inspect_path


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Independent FieldFox GPSA recording decoder (static reconstruction)")
    sub = parser.add_subparsers(dest="command", required=True)
    inspect = sub.add_parser("inspect", help="Inspect file prefixes, states and trace boundaries")
    inspect.add_argument("path")
    export = sub.add_parser("export", help="Export a complete GPSA session")
    export.add_argument("path")
    export.add_argument("--format", choices=["csv", "npz"], required=True)
    export.add_argument("--output", required=True)
    args = parser.parse_args(argv)
    try:
        if args.command == "inspect":
            result = inspect_path(args.path)
            print(json.dumps(result, indent=2, allow_nan=False))
            return 0 if result["supported"] else 2
        rec = FieldFoxRecording.open(args.path)
        getattr(rec, f"to_{args.format}")(args.output)
        print(f"Exported {len(rec)} sweeps, {rec.states[0].points} points, {rec.states[0].trace_count} trace(s) to {args.output}")
        return 0
    except (RecordingError, OSError) as error:
        print(f"fieldfox-recording: {error}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
