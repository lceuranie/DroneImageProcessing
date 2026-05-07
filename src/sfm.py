"""Stage 5 — Structure-from-Motion + dense MVS via COLMAP.

NOTE: stub. See AGENTS.md §5 "Stage 5". Implementation uses pycolmap for the
sparse reconstruction and the COLMAP CLI for PatchMatch stereo / fusion. Outputs
a dense PLY and a LAS file in EPSG:32632.
"""

from __future__ import annotations

import argparse
from pathlib import Path


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--images",  type=Path, required=True)
    parser.add_argument("--workdir", type=Path, required=True,
                        help="COLMAP workspace (database, sparse/, dense/)")
    parser.add_argument("--gps-prior", action="store_true",
                        help="Use EXIF GPS as a prior for model alignment")
    parser.parse_args(argv)
    raise NotImplementedError(
        "Stage 5 not yet implemented — see AGENTS.md §5 for the contract."
    )


if __name__ == "__main__":
    main()
