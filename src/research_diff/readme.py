"""The README's generated research map: the picture, and the warnings that stand open."""
from __future__ import annotations

from pathlib import Path
from typing import Optional

from system_diff.pictures import write_if_changed

from . import compare, graph


def section(bp: dict, cfg: dict) -> str:
    r = cfg["readme"]
    warn = "".join(f"- {w}\n" for w in bp["warnings"])
    return (f"{r['begin']}\n![Research map, generated from the notes, configs, results and paper]({r['image'] or r['svg']})\n\n"
            + (f"<details><summary>{len(bp['warnings'])} open warning{'' if len(bp['warnings']) == 1 else 's'}"
               f"</summary>\n\n{warn}\n</details>\n" if warn else "")
            + f"{r['end']}")


def run(root: Path, config_path: Optional[str] = None, check: bool = False) -> int:
    bp, cfg, _ = compare.read(root, ".", config_path)
    r = cfg["readme"]
    path, image = root / r["file"], root / r["svg"]
    text = path.read_text(encoding="utf-8")
    if r["begin"] not in text or r["end"] not in text:
        print(f"{path} has no {r['begin']} … {r['end']} section: add the two lines where the map goes")
        return 1
    start, end = text.index(r["begin"]), text.index(r["end"]) + len(r["end"])
    new_text, svg = text[:start] + section(bp, cfg) + text[end:], graph.map_svg(bp, cfg)
    if check:
        current = new_text == text and image.is_file() and image.read_text(encoding="utf-8") == svg
        print("README research map " + ("is current" if current else "is out of date"))
        return 0 if current else 1
    image.parent.mkdir(parents=True, exist_ok=True)
    changed = write_if_changed(image, svg) | write_if_changed(path, new_text)
    print("README research map " + ("updated" if changed else "already current"))
    return 0
