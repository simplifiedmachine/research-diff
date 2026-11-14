"""The README's generated research section: the research map, the evidence graph, and the warnings that stand open."""
from __future__ import annotations

from pathlib import Path
from typing import Optional

from system_diff.pictures import write_if_changed

from . import compare, evgraph, evidence, graph


def _image(cfg: dict, path: str) -> str:
    """Where the README links a picture: beside `image` (an absolute URL, so PyPI shows it too) when one is set."""
    r = cfg["readme"]
    if r["image"] and r["image"].endswith(r["svg"].rsplit("/", 1)[-1]):
        return r["image"][: -len(r["svg"].rsplit("/", 1)[-1])] + path.rsplit("/", 1)[-1]
    return path


def section(bp: dict, cfg: dict, g: Optional[dict] = None) -> str:
    r = cfg["readme"]
    g = g or evidence.build(bp, cfg)
    warn = "".join(f"- {w}\n" for w in bp["warnings"])
    ev = (f"![Evidence graph: what supports and what contradicts each claim of the paper]"
          f"({_image(cfg, cfg['evidence']['svg'])})\n\n") if g["statements"] else ""
    return (f"{r['begin']}\n{ev}![Research map, generated from the notes, configs, results and paper]"
            f"({r['image'] or r['svg']})\n\n"
            + (f"<details><summary>{len(bp['warnings'])} open warning{'' if len(bp['warnings']) == 1 else 's'}"
               f"</summary>\n\n{warn}\n</details>\n" if warn else "")
            + f"{r['end']}")


def run(root: Path, config_path: Optional[str] = None, check: bool = False) -> int:
    bp, cfg, _ = compare.read(root, ".", config_path)
    g = evidence.build(bp, cfg)
    r = cfg["readme"]
    path, image, ev_image = root / r["file"], root / r["svg"], root / cfg["evidence"]["svg"]
    text = path.read_text(encoding="utf-8")
    if r["begin"] not in text or r["end"] not in text:
        print(f"{path} has no {r['begin']} … {r['end']} section: add the two lines where the map goes")
        return 1
    start, end = text.index(r["begin"]), text.index(r["end"]) + len(r["end"])
    new_text, svg, ev_svg = text[:start] + section(bp, cfg, g) + text[end:], graph.map_svg(bp, cfg), evgraph.svg(g)
    if check:
        current = new_text == text and image.is_file() and image.read_text(encoding="utf-8") == svg and \
            (not g["statements"] or (ev_image.is_file() and ev_image.read_text(encoding="utf-8") == ev_svg))
        print("README research map " + ("is current" if current else "is out of date"))
        return 0 if current else 1
    image.parent.mkdir(parents=True, exist_ok=True)
    ev_image.parent.mkdir(parents=True, exist_ok=True)
    changed = write_if_changed(image, svg) | write_if_changed(path, new_text)
    if g["statements"]:
        changed |= write_if_changed(ev_image, ev_svg)
    print("README research map " + ("updated" if changed else "already current"))
    return 0
