"""
Render the dashboard pages from the test fixtures, without Home Assistant or a calendar.

Usage (from the repo root, with the dev requirements installed and chromium on PATH):

    python scripts/preview.py OUTDIR [--items N] [--battery PCT]

Writes OUTDIR/page1.png, page2.png, ... (the exact PNGs the Kindle would show) and
OUTDIR/preview.html (open it in a browser to tweak the CSS).
"""

import argparse
import sys
from pathlib import Path

SERVER = Path(__file__).resolve().parents[1] / "server"
sys.path[:0] = [str(SERVER), str(SERVER / "tests")]

from conftest import sample_data  # noqa: E402
from fridgedash.config import Settings  # noqa: E402
from fridgedash.render import render_pages  # noqa: E402

# Filler for --items, so the shopping pages can be checked with a long list.
GROCERIES = [
    "Chicken breast",
    "Tuna",
    "Ginger",
    "Yellow pepper",
    "Pak choi",
    "Toothpaste",
    "Hand soap",
    "Honey",
    "Yogurt",
    "Hummus",
    "Parmigiano Reggiano 24 months",
    "Olive oil",
    "Basmati rice",
    "Lemons",
    "Spinach",
    "Oat milk",
    "Butter",
    "Coffee",
    "Tinned tomatoes",
    "Garlic",
    "Red onions",
    "Spaghetti",
    "Mozzarella",
    "Basil",
    "Apples",
    "Kitchen roll",
    "Bin bags",
    "Dishwasher tablets",
    "Frozen peas",
    "Porridge oats",
]


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    """
    Parse the command line.

    Args:
        argv (list[str] | None): Arguments; None reads sys.argv.

    Returns:
        argparse.Namespace: ``outdir``, ``items`` and ``battery``.
    """
    parser = argparse.ArgumentParser(description=__doc__.strip().split("\n\n")[0])
    parser.add_argument("outdir", type=Path, help="directory for the PNGs and HTML")
    parser.add_argument(
        "--items",
        type=int,
        default=0,
        help="replace the sample shopping list with N items (0 = keep the fixture)",
    )
    parser.add_argument(
        "--battery", type=int, default=87, help="Kindle battery %% shown in the footer"
    )
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> None:
    """
    Render the sample pages and print the files written.

    Args:
        argv (list[str] | None): Arguments; None reads sys.argv.
    """
    args = parse_args(argv)
    args.outdir.mkdir(parents=True, exist_ok=True)
    settings = Settings(data_dir=args.outdir)
    data = sample_data(settings, battery=args.battery)
    if args.items:
        data.shopping = [
            GROCERIES[i % len(GROCERIES)] + ("" if i < len(GROCERIES) else f" {i}")
            for i in range(args.items)
        ]
    html, pages = render_pages(data, settings, args.outdir)
    (args.outdir / "preview.html").write_text(html)
    for n in range(1, pages + 1):
        print(args.outdir / f"page{n}.png")


if __name__ == "__main__":
    main()
