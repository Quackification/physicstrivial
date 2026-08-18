#!/usr/bin/env python3
"""Parse the user-supplied AAPT ZIP into a website-ready JSON dataset.

Requires pypdf (already installed in Prism). Run from the project root:
  python3 parse_aapt_archive.py prism-uploads/aapt-exams.zip aapt-problems.json
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import shutil
import subprocess
import tempfile
import time
import zipfile
from collections import Counter
from pathlib import Path
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

from pypdf import PdfReader
from PIL import Image, ImageChops


SOLUTION_WORDS = ("solution", "soln", "answer")
EXCLUDED_WORDS = ("quarter", "qtr", "tst", "plus")
FMA_WORDS = ("fma", "f-ma", "fnet_ma", "fnet-ma", "exam1", "webassign")
USAPHO_WORDS = ("usapho", "semi-final", "semifinal")

FMA_LLM_CATEGORIES = (
    "Collisions", "Dynamics", "Energy", "Fluids", "Gravity", "Kinematics",
    "Oscillatory Motion", "Dimensional Analysis", "Rigid Bodies", "Other",
)
USAPHO_LLM_CATEGORIES = (
    "Mechanics", "Electromagnetism", "Thermodynamics", "Relativity", "Nuclear",
    "Particle Physics", "Waves", "Optics", "Other",
)
LLM_PROMPT_VERSION = "aapt-physics-taxonomy-v1"
LLM_CONFIDENCE = ("high", "medium", "low")

LLM_DEFINITIONS = {
    "F=ma": """Collisions: collisions, impulse, momentum transfer, and center-of-mass interactions.
Dynamics: Newtonian forces, friction, tension, and circular dynamics not primarily about rigid bodies.
Energy: work, energy, power, and conservation of mechanical energy.
Fluids: hydrostatics, buoyancy, flow, Bernoulli effects, and viscosity.
Gravity: universal gravitation, gravitational fields, planetary motion, and orbits; ordinary near-Earth projectiles are Kinematics unless gravity itself is the concept tested.
Kinematics: motion descriptions, projectiles, relative motion, and motion graphs where force or energy is not the main method.
Oscillatory Motion: simple harmonic motion, pendula, springs, and periodic oscillations.
Dimensional Analysis: units, dimensions, scaling, estimation, uncertainty, and order-of-magnitude reasoning.
Rigid Bodies: torque, rotational dynamics, angular momentum of extended bodies, rolling, moment of inertia, and statics of extended bodies.
Other: use only when none of the named F=ma categories is a defensible primary classification.""",
    "USAPhO": """Mechanics: classical mechanics, including fluids and oscillations, unless another listed category more directly describes the main physics.
Electromagnetism: electrostatics, circuits, electric and magnetic fields, induction, and electromagnetic dynamics.
Thermodynamics: heat, gases, entropy, engines, and statistical mechanics.
Relativity: special or general relativity.
Nuclear: nuclei, radioactivity, nuclear reactions, and nuclear structure.
Particle Physics: elementary particles, particle interactions, and high-energy physics.
Waves: non-optical waves, acoustics, wave equations, and mechanical wave phenomena.
Optics: geometric optics, interference or diffraction of light, polarization, and lasers.
Other: use only when none of the named USAPhO categories is a defensible primary classification.""",
}

TOPICS = {
    "Modern physics": {
        "relativity": ("relativ", "lorentz factor", "speed of light", "proper time"),
        "quantum physics": ("photon", "photoelectric", "de broglie", "wavefunction", "quantum"),
        "atomic/nuclear physics": ("nucleus", "radioactive", "half-life", "atomic", "electron transition"),
    },
    "Optics": {
        "geometric optics": ("lens", "mirror", "focal", "image distance", "refraction", "refractive"),
        "wave optics": ("diffraction", "interference", "polariz", "double slit"),
    },
    "Thermodynamics": {
        "ideal gases": ("ideal gas", "piston", "mole of gas", "gas law"),
        "heat and temperature": ("temperature", "heat engine", "entropy", "thermal", "carnot", "specific heat"),
    },
    "Electricity": {
        "electrostatics": ("electric field", "electric potential", "point charge", "coulomb", "capacitor", "capacitance", "dielectric"),
        "circuits": ("resistor", "circuit", "current", "voltage", "battery", "resistance", "rc circuit"),
    },
    "Magnetism": {
        "magnetic forces": ("magnetic field", "lorentz force", "tesla", "solenoid"),
        "induction": ("magnetic flux", "faraday", "induced emf", "induction", "inductor"),
    },
    "Fluids": {
        "fluid dynamics": ("bernoulli", "fluid flow", "pipe", "viscos", "terminal velocity"),
        "hydrostatics": ("buoyant", "density of water", "liquid", "fluid pressure", "submerged"),
    },
    "Waves": {
        "standing waves": ("standing wave", "node", "antinode", "string fixed", "harmonic"),
        "wave motion": ("wavelength", "wave speed", "frequency", "sound wave", "doppler"),
    },
    "Oscillations": {
        "simple harmonic motion": ("simple harmonic", "oscillat", "pendulum", "spring constant", "period of"),
    },
    "Gravitation": {
        "orbits": ("orbit", "satellite", "planet", "escape speed", "kepler"),
        "gravitational fields": ("gravitational field", "gravitational potential", "newton's law of gravitation"),
    },
    "Rotation": {
        "rotational dynamics": ("moment of inertia", "angular momentum", "torque", "angular acceleration"),
        "rolling motion": ("rolls without slipping", "rolling without slipping", "uniform disk", "uniform sphere"),
    },
    "Momentum": {
        "collisions": ("collision", "collides", "inelastic", "elastic collision"),
        "impulse/momentum": ("momentum", "impulse", "center of mass"),
    },
    "Energy": {
        "work and energy": ("kinetic energy", "potential energy", "work done", "mechanical energy", "conservation of energy"),
        "power": ("power delivered", "power output"),
    },
    "Circular motion": {
        "centripetal motion": ("centripetal", "circular path", "vertical circle", "banked", "revolutions per"),
    },
    "Dynamics": {
        "forces and friction": ("friction", "coefficient of", "normal force", "tension", "newton's second", "inclined plane"),
        "statics": ("static equilibrium", "in equilibrium", "truss", "bridge"),
    },
    "Kinematics": {
        "projectile motion": ("projectile", "thrown horizontally", "launched", "trajectory"),
        "one-dimensional motion": ("acceleration", "velocity versus time", "position versus time", "free fall", "falls from rest"),
    },
}

HEADER_PATTERNS = (
    r"^\s*Copyright .*?$",
    r"^\s*AAPT\s*$",
    r"^\s*AIP\s+\d{4}\s*$",
    r"^\s*UNITED\s+STATES\s+PHYSICS\s+TEAM\s*$",
    r"^\s*\d{4}\s+.*?(?:Exam|Contest|Part [A-C]|Cover Sheet).*?\d+\s*$",
    r"^\s*This page is intentionally blank\.?\s*$",
)


def pdf_text(path: Path) -> str:
    pages = []
    for page in PdfReader(path).pages:
        pages.append(page.extract_text() or "")
    return clean_raw("\n".join(pages))


def clean_raw(text: str) -> str:
    replacements = {"ﬁ": "fi", "ﬂ": "fl", "−": "−", "⃝": "", "©": "©", "\x00": ""}
    for old, new in replacements.items():
        text = text.replace(old, new)
    for pattern in HEADER_PATTERNS:
        text = re.sub(pattern, "", text, flags=re.MULTILINE | re.IGNORECASE)
    text = re.sub(r"\n{3,}", "\n\n", text)
    return text


def compact(text: str, limit: int | None = None) -> str:
    text = re.sub(r"\s+", " ", text).strip()
    if limit and len(text) > limit:
        text = text[:limit].rsplit(" ", 1)[0] + "…"
    return text


GREEK_LATEX = {
    "α": r"\alpha", "β": r"\beta", "γ": r"\gamma", "δ": r"\delta",
    "ε": r"\epsilon", "ϵ": r"\varepsilon", "θ": r"\theta", "κ": r"\kappa",
    "λ": r"\lambda", "μ": r"\mu", "ν": r"\nu", "ξ": r"\xi",
    "π": r"\pi", "ρ": r"\rho", "σ": r"\sigma", "τ": r"\tau",
    "φ": r"\phi", "ϕ": r"\varphi", "χ": r"\chi", "ψ": r"\psi",
    "ω": r"\omega", "Γ": r"\Gamma", "Δ": r"\Delta", "Θ": r"\Theta",
    "Λ": r"\Lambda", "Ξ": r"\Xi", "Π": r"\Pi", "Σ": r"\Sigma",
    "Φ": r"\Phi", "Ψ": r"\Psi", "Ω": r"\Omega", "ℓ": r"\ell",
}
SUPERSCRIPTS = str.maketrans("⁰¹²³⁴⁵⁶⁷⁸⁹⁺⁻", "0123456789+-")
SUBSCRIPTS = str.maketrans("₀₁₂₃₄₅₆₇₈₉₊₋", "0123456789+-")
MATH_SIGNAL = re.compile(r"[=≈≃≤≥≪≫∝√∑∫²³⁰¹⁴⁵⁶⁷⁸⁹₀₁₂₃₄₅₆₇₈₉α-ωΑ-Ωℓ∞±∓×·]")
EQUATION_FRAGMENT = re.compile(
    r"(?<!\w)([A-Za-zΑ-Ωα-ωℓ][A-Za-z0-9Α-Ωα-ωℓ_²³⁰¹⁴⁵⁶⁷⁸⁹₀₁₂₃₄₅₆₇₈₉]{0,18}"
    r"\s*(?:=|≈|≃|≤|≥|≪|≫|∝)\s*[^,;.!?]{1,80})"
)
ROOT_FRAGMENT = re.compile(r"(?<!\w)([A-Za-z0-9Α-Ωα-ωℓ()\[\]/+*·×−-]*√[^,;.!? ]+(?:\s*[A-Za-z0-9]+)?)")


def tex_expression(value: str) -> str:
    """Convert a PDF-extracted math fragment to conservative TeX."""
    value = compact(value)
    value = value.replace("\\", r"\backslash ")

    def superscript(match):
        return "^{" + match.group(0).translate(SUPERSCRIPTS) + "}"

    def subscript(match):
        return "_{" + match.group(0).translate(SUBSCRIPTS) + "}"

    value = re.sub(r"[⁰¹²³⁴⁵⁶⁷⁸⁹⁺⁻]+", superscript, value)
    value = re.sub(r"[₀₁₂₃₄₅₆₇₈₉₊₋]+", subscript, value)
    for symbol, letter in {"ₐ": "a", "ₑ": "e", "ₕ": "h", "ᵢ": "i", "ⱼ": "j", "ₖ": "k",
                           "ₗ": "l", "ₘ": "m", "ₙ": "n", "ₒ": "o", "ₚ": "p", "ᵣ": "r",
                           "ₛ": "s", "ₜ": "t", "ᵤ": "u", "ᵥ": "v", "ₓ": "x", "꜀": "c"}.items():
        value = value.replace(symbol, "_{" + letter + "}")
    for symbol, command in GREEK_LATEX.items():
        value = value.replace(symbol, command + " ")
    value = (value.replace("×", r"\times ").replace("·", r"\cdot ")
                  .replace("−", "-").replace("±", r"\pm ").replace("∓", r"\mp ")
                  .replace("≈", r"\approx ").replace("≃", r"\simeq ")
                  .replace("≤", r"\le ").replace("≥", r"\ge ")
                  .replace("≪", r"\ll ").replace("≫", r"\gg ")
                  .replace("∝", r"\propto ").replace("∞", r"\infty "))
    value = re.sub(r"√\s*\(([^()]+)\)", r"\\sqrt{\1}", value)
    value = re.sub(r"√\s*([A-Za-z0-9\\_^{}.+-]+(?:\s*[A-Za-z0-9]+)?)", r"\\sqrt{\1}", value)
    value = value.replace("√", r"\sqrt{}")
    return re.sub(r"\s+", " ", value).strip()


def latexify_choice(value: str) -> str:
    """Wrap formula-like answer choices for MathJax; leave prose untouched."""
    value = compact(value)
    if len(value.split()) > 5 and len(re.findall(r"\b[A-Za-z]{3,}\b", value)) >= 2:
        return latexify_prose(value)
    operator_expression = re.search(r"[A-Za-zΑ-Ωα-ωℓ].*[+−\-/].*[A-Za-z0-9Α-Ωα-ωℓ]", value)
    if not value or (not MATH_SIGNAL.search(value) and not operator_expression):
        return value
    return rf"\({tex_expression(value)}\)"


def latexify_prose(value: str) -> str:
    """Add MathJax delimiters around high-confidence inline math fragments."""
    value = compact(value)

    def wrap_equation(match):
        return rf"\({tex_expression(match.group(1))}\)"

    value = EQUATION_FRAGMENT.sub(wrap_equation, value)
    pieces = re.split(r"(\\\(.*?\\\))", value)
    for index in range(0, len(pieces), 2):
        pieces[index] = ROOT_FRAGMENT.sub(
            lambda match: rf"\({tex_expression(match.group(1))}\)", pieces[index]
        )
    return "".join(pieces)


def latexify_answer(value: str) -> str:
    """Keep the multiple-choice label as text and TeX-render its answer body."""
    match = re.match(r"^([A-E]\s*[—-]\s*)(.*)$", compact(value))
    if not match:
        return latexify_prose(value)
    return match.group(1) + latexify_choice(match.group(2))


def file_kind(path: Path) -> str | None:
    name = path.name.lower().replace("_", "-")
    if any(word in name for word in EXCLUDED_WORDS):
        return None
    if any(word in name for word in FMA_WORDS):
        return "F=ma"
    if any(word in name for word in USAPHO_WORDS) or re.match(r"e3-", name):
        return "USAPhO"
    return None


def is_solution(path: Path) -> bool:
    return any(word in path.name.lower() for word in SOLUTION_WORDS)


def variant(path: Path, kind: str) -> str:
    if kind != "F=ma":
        return ""
    name = path.stem.lower().replace("_", "-")
    if re.search(r"(?:exam-?|fma-?|f-ma-)(?:2018-|2019-|2020-|2022-)?a(?:-|$)", name):
        return "A"
    if re.search(r"(?:exam-?|fma-?|f-ma-)(?:2018-|2019-|2020-|2022-)?b(?:-|$)", name):
        return "B"
    return ""


def pair_files(root: Path):
    pdfs = sorted(root.rglob("*.pdf"))
    exams = [p for p in pdfs if file_kind(p) and not is_solution(p)]
    solutions = [p for p in pdfs if file_kind(p) and is_solution(p)]
    for exam in exams:
        kind = file_kind(exam)
        year_match = re.search(r"20\d{2}|19\d{2}", str(exam))
        if not year_match:
            continue
        year = int(year_match.group())
        var = variant(exam, kind)
        candidates = [p for p in solutions if file_kind(p) == kind and str(year) in str(p)]
        if var:
            matching = [p for p in candidates if variant(p, kind) == var]
            if matching:
                candidates = matching
        elif kind == "F=ma":
            no_variant = [p for p in candidates if not variant(p, kind)]
            if no_variant:
                candidates = no_variant
        solution = candidates[0] if candidates else None
        yield exam, solution, kind, year, var


def question_positions(path: Path, kind: str):
    """Return question labels with PDF page/y coordinates in reading order."""
    reader = PdfReader(path)
    found = []
    for page_index, page in enumerate(reader.pages):
        chunks = []

        def visitor(text, _cm, tm, _font, _size):
            cleaned = " ".join(text.split())
            if cleaned and tm and len(tm) >= 6:
                chunks.append((float(tm[5]), float(tm[4]), cleaned))

        page.extract_text(visitor_text=visitor)
        shared_y = None
        last_question_y = None
        for y, x, text in sorted(chunks, key=lambda item: -item[0]):
            if re.search(r"information (?:below )?(?:applies|is used) (?:to|for)", text, re.I):
                if last_question_y is None or abs(last_question_y - y) > 3:
                    shared_y = y
            if kind == "F=ma":
                match = re.match(r"^\s*(\d{1,2})\.(?:\s+|$)", text)
                if not match or x > 76 or not 1 <= int(match.group(1)) <= 25:
                    continue
                label = match.group(1)
            else:
                match = re.match(r"^\s*(?:Question|Problem)\s+([ABC]?\d+)(?::|\s|$)", text, re.I)
                if not match:
                    continue
                label = match.group(1).upper()
            start_y = max(y, shared_y) if shared_y is not None else y
            found.append({"label": label, "page": page_index, "y": start_y})
            last_question_y = y
            shared_y = None

    unique = []
    seen = set()
    for item in sorted(found, key=lambda value: (value["page"], -value["y"])):
        if item["label"] not in seen:
            seen.add(item["label"])
            unique.append(item)
    return reader, unique


def likely_content_end(reader: PdfReader, start_page: int) -> int:
    """Avoid trailing answer sheets and intentionally blank pages."""
    last = start_page
    sparse_run = 0
    for page_index in range(start_page, len(reader.pages)):
        text = compact(reader.pages[page_index].extract_text() or "")
        lower = text.lower()
        trailing_sheet = any(phrase in lower for phrase in (
            "answer sheet", "additional answer", "this page is intentionally blank", "graph paper"
        ))
        if page_index > start_page and trailing_sheet and not re.search(r"(?:question|problem)\s+[ab]?\d", lower):
            break
        if len(text) < 90:
            sparse_run += 1
            if sparse_run >= 2 and page_index > start_page:
                break
        else:
            sparse_run = 0
            last = page_index
    return last


def question_segments(path: Path, kind: str):
    """Map each question to one or more page-coordinate crop segments."""
    reader, positions = question_positions(path, kind)
    segments = {}
    for index, start in enumerate(positions):
        next_start = positions[index + 1] if index + 1 < len(positions) else None
        end_page = next_start["page"] if next_start else likely_content_end(reader, start["page"])
        pieces = []
        for page_index in range(start["page"], end_page + 1):
            height = float(reader.pages[page_index].mediabox.height)
            width = float(reader.pages[page_index].mediabox.width)
            top_y = min(height - 34, start["y"] + 13) if page_index == start["page"] else height - 42
            bottom_y = 43.0
            if next_start and page_index == next_start["page"]:
                bottom_y = min(height - 43, next_start["y"] + 13)
            if top_y - bottom_y >= 35:
                pieces.append({"page": page_index, "left": 31.0, "right": width - 31.0,
                               "top_y": top_y, "bottom_y": bottom_y, "page_height": height})
        if pieces:
            segments[start["label"]] = pieces
    return segments


def shared_question_groups(path: Path, kind: str):
    """Map later F=ma questions to the lead question containing their shared stem."""
    if kind != "F=ma":
        return {}
    reader, positions = question_positions(path, kind)
    position_by_label = {item["label"]: item for item in positions}
    groups = {}
    trigger = re.compile(
        r"following information|information below|information is used|information is relevant|"
        r"refer to the following information",
        re.I,
    )
    number_list = r"(\d{1,2}(?:\s*,\s*\d{1,2})*(?:\s*,?\s*(?:and|through|-)\s*\d{1,2})?)"

    for page_index, page in enumerate(reader.pages):
        chunks = []

        def visitor(text, _cm, tm, _font, _size):
            cleaned = " ".join(text.split())
            if cleaned and tm and len(tm) >= 6:
                chunks.append((float(tm[5]), cleaned))

        page.extract_text(visitor_text=visitor)
        for y, text in chunks:
            if not trigger.search(text):
                continue
            targets = []
            explicit = re.search(
                rf"(?:questions|problems)\s+{number_list}",
                text,
                re.I,
            )
            if not explicit:
                explicit = re.search(
                    rf"applies to\s+{number_list}",
                    text,
                    re.I,
                )
            if explicit:
                targets = re.findall(r"\d{1,2}", explicit.group(1))
            elif re.search(r"next\s+two\s+(?:questions|problems)", text, re.I):
                following = [
                    item for item in positions
                    if item["page"] > page_index or
                    (item["page"] == page_index and item["y"] <= y + 3)
                ]
                targets = [item["label"] for item in following[:2]]

            targets = [label for label in targets if label in position_by_label]
            if len(targets) < 2:
                continue
            leader = targets[0]
            for label in targets[1:]:
                groups[label] = {"leader": leader, "members": targets}
    return groups


def render_pdf_pages(path: Path, destination: Path, dpi: int):
    destination.mkdir(parents=True, exist_ok=True)
    pattern = destination / "page-%03d.png"
    command = [
        "gs", "-q", "-dSAFER", "-dBATCH", "-dNOPAUSE", "-sDEVICE=png16m",
        f"-r{dpi}", f"-sOutputFile={pattern}", str(path),
    ]
    subprocess.run(command, check=True, stdout=subprocess.DEVNULL, stderr=subprocess.PIPE)


def generate_pdf_snippets(path: Path | None, kind: str, year: int, var: str, role: str,
                          assets_root: Path | None, dpi: int, expected_labels=None):
    """Render/crop exact PDF snippets and return label -> relative asset paths."""
    if path is None or assets_root is None:
        return {}
    if not shutil.which("gs"):
        raise RuntimeError("Ghostscript (gs) is required for --assets-dir PDF snippet generation")
    spans = question_segments(path, kind)
    if not spans:
        return {}
    if role == "problems":
        expected = (set(map(str, range(1, 26))) if kind == "F=ma"
                    else set(expected_labels or ()))
        if kind == "USAPhO" and len(expected) != 6:
            raise RuntimeError(
                f"Expected six parsed USAPhO problems for {year}, found {sorted(expected)}"
            )
        missing_labels = expected - set(spans)
        if missing_labels:
            exam_name = f"{year} {kind}{(' ' + var) if var else ''}"
            raise RuntimeError(
                f"Refusing to generate mismatched assets for {exam_name}; "
                f"missing question labels: {sorted(missing_labels)}"
            )
    source_slug = "fma" if kind == "F=ma" else "usapho"
    variant_slug = f"-{var.lower()}" if var else ""
    output_dir = assets_root / role
    output_dir.mkdir(parents=True, exist_ok=True)
    result = {}
    scale = dpi / 72.0
    with tempfile.TemporaryDirectory(prefix="aapt-pages-") as temporary:
        page_dir = Path(temporary)
        render_pdf_pages(path, page_dir, dpi)
        for label, pieces in spans.items():
            paths = []
            for part_index, piece in enumerate(pieces, 1):
                rendered = page_dir / f"page-{piece['page'] + 1:03d}.png"
                if not rendered.exists():
                    continue
                with Image.open(rendered) as image:
                    left = max(0, round(piece["left"] * scale))
                    right = min(image.width, round(piece["right"] * scale))
                    top = max(0, round((piece["page_height"] - piece["top_y"]) * scale))
                    bottom = min(image.height, round((piece["page_height"] - piece["bottom_y"]) * scale))
                    if right - left < 100 or bottom - top < 60:
                        continue
                    crop = image.crop((left, top, right, bottom)).convert("L")
                    ink = ImageChops.invert(crop).point(lambda value: 255 if value > 14 else 0)
                    content_box = ink.getbbox()
                    if content_box is None:
                        continue
                    padding = 16
                    content_box = (
                        max(0, content_box[0] - padding), max(0, content_box[1] - padding),
                        min(crop.width, content_box[2] + padding), min(crop.height, content_box[3] + padding),
                    )
                    crop = crop.crop(content_box)
                    if crop.width < 100 or crop.height < 35:
                        continue
                    filename = f"{year}-{source_slug}{variant_slug}-{label.lower()}-{part_index}.webp"
                    target = output_dir / filename
                    crop.save(target, "WEBP", lossless=True, method=6)
                    paths.append((Path("assets") / role / filename).as_posix())
            if paths:
                result[label] = paths
    if role == "problems":
        missing_renders = set(spans) - set(result)
        if missing_renders:
            raise RuntimeError(
                f"PDF crops were blank or missing for {path.name}: {sorted(missing_renders)}"
            )
    return result


def split_numbered(text: str):
    starts = list(re.finditer(r"(?m)^\s*(\d{1,2})\.\s+", text))
    result = {}
    for index, match in enumerate(starts):
        number = int(match.group(1))
        if not 1 <= number <= 25 or number in result:
            continue
        end = starts[index + 1].start() if index + 1 < len(starts) else len(text)
        result[number] = text[match.end():end].strip()
    return result


def parse_choices(block: str):
    matches = list(re.finditer(r"(?<!\w)\(([A-Ea-e])\)\s*", block))
    if len(matches) < 4:
        return compact(block), []
    matches = matches[:5]
    statement = compact(block[:matches[0].start()])
    choices = []
    for index, match in enumerate(matches):
        end = matches[index + 1].start() if index + 1 < len(matches) else len(block)
        choices.append(compact(block[match.end():end]))
    return statement, choices


def answer_keys(solution_text: str, solution_blocks: dict[int, str]):
    keys = {}
    for letter, number in re.findall(r"\b([A-E])A(\d{1,2})\b", solution_text):
        keys[int(number)] = letter
    for number, letter in re.findall(r"(?m)^\s*(\d{1,2})\s*[.)-]?\s*([A-E])\s*$", solution_text):
        keys[int(number)] = letter
    for number, block in solution_blocks.items():
        for match in re.finditer(r"\(([A-E])\)(?:(?!\([A-E]\)).){0,500}?←\s*CORRECT", block, re.DOTALL | re.I):
            keys[number] = match.group(1).upper()
            break
        direct = re.search(r"\b([A-E])\s*←\s*CORRECT", block, re.I)
        if direct:
            keys[number] = direct.group(1).upper()
    return keys


def bold_answer_keys(solution_path: Path | None):
    """Read answer letters emphasized in bold inside official solution PDFs."""
    if solution_path is None:
        return {}
    spans = question_segments(solution_path, "F=ma")
    if not spans:
        return {}
    reader = PdfReader(solution_path)
    page_chunks = {}
    for page_index, page in enumerate(reader.pages):
        chunks = []

        def visitor(text, _cm, tm, font, _size):
            cleaned = " ".join(text.split())
            base_font = str((font or {}).get("/BaseFont", "")).upper()
            if cleaned and tm and len(tm) >= 6:
                chunks.append({"text": cleaned, "x": float(tm[4]), "y": float(tm[5]),
                               "bold": "CMBX" in base_font or "BOLD" in base_font})

        page.extract_text(visitor_text=visitor)
        page_chunks[page_index] = chunks

    keys = {}
    for label, pieces in spans.items():
        candidates = []
        for piece in pieces:
            for chunk in page_chunks.get(piece["page"], []):
                if not chunk["bold"] or chunk["y"] <= 25:
                    continue
                if not (piece["bottom_y"] <= chunk["y"] <= piece["top_y"]):
                    continue
                match = re.match(r"^\(?([A-E])\)?(?:\s|$)", chunk["text"])
                if match:
                    candidates.append((piece["page"], -chunk["y"], chunk["x"], match.group(1)))
        if candidates:
            candidates.sort()
            keys[int(label)] = candidates[0][3]
    return keys


def solution_excerpt(block: str, choices: list[str]) -> str:
    marker = re.search(r"\bSolution\b", block, re.I)
    if marker:
        return compact(block[marker.end():], 1800)
    if choices:
        normalized = compact(block)
        tail = compact(choices[-1])
        probe = tail[: min(55, len(tail))]
        at = normalized.find(probe)
        if at >= 0:
            return compact(normalized[at + len(tail):], 1800)
    return ""


def classify(text: str):
    lower = text.lower()
    scores = []
    for topic, subtopics in TOPICS.items():
        for subtopic, words in subtopics.items():
            score = sum(lower.count(word) for word in words)
            if score:
                scores.append((score, topic, subtopic))
    if not scores:
        fallback = (
            ("Modern physics", "modern physics", ("relativ", "photon", "electron", "nuclear", "atom")),
            ("Optics", "geometric optics", ("light ray", "lens", "mirror", "refractive")),
            ("Electricity", "electrostatics", ("electric", "charge", "voltage", "current")),
            ("Magnetism", "magnetic fields", ("magnet", "tesla", "flux")),
            ("Thermodynamics", "thermal physics", ("temperature", "heat", "gas", "pressure")),
            ("Fluids", "fluid mechanics", ("water", "fluid", "density", "buoy")),
            ("Gravitation", "gravitation", ("star", "planet", "satellite", "gravity", "gravitational")),
            ("Rotation", "rotational motion", ("angular", "rotat", "disk", "disc", "wheel")),
            ("Momentum", "momentum", ("momentum", "collid", "impulse")),
            ("Energy", "work and energy", ("energy", "work", "power")),
            ("Waves", "wave motion", ("wave", "frequency", "sound")),
            ("Oscillations", "oscillations", ("oscillat", "pendulum", "spring")),
            ("Circular motion", "circular motion", ("circle", "circular", "revolution")),
            ("Dynamics", "forces", ("force", "friction", "tension", "pulley", "rope", "scale")),
            ("Kinematics", "motion", ("velocity", "speed", "acceleration", "displacement", "distance", "trajectory")),
        )
        for topic, subtopic, words in fallback:
            if any(word in lower for word in words):
                return topic, subtopic
        return "Mixed/advanced", "general physics"
    _, topic, subtopic = max(scores, key=lambda item: (item[0], -list(TOPICS).index(item[1])))
    return topic, subtopic


def fma_records(exam: Path, solution: Path | None, year: int, var: str):
    exam_blocks = split_numbered(pdf_text(exam))
    solution_text = pdf_text(solution) if solution else ""
    solution_blocks = split_numbered(solution_text)
    keys = answer_keys(solution_text, solution_blocks)
    bold_keys = bold_answer_keys(solution)
    records = []
    for number, block in sorted(exam_blocks.items()):
        statement, choices = parse_choices(block)
        if not statement or number > 25:
            continue
        topic, subtopic = classify(statement)
        level = 1 if number <= 8 else 2 if number <= 18 else 3
        explicit_letter = keys.get(number, "")
        evidence = "explicit solution marker/key" if explicit_letter else ""
        solution_block = solution_blocks.get(number, "")
        if not explicit_letter:
            direct = re.search(r"correct answer is\s+([A-E])", solution_block, re.I)
            if direct:
                explicit_letter = direct.group(1).upper()
                evidence = "explicit solution statement"
        inferred_letter = ""
        if not explicit_letter and choices:
            normalized_solution = compact(solution_block)
            for choice_index, choice in enumerate(choices):
                probe = compact(choice)[:45]
                if len(probe) < 3:
                    continue
                at = normalized_solution.find(probe)
                if at >= 0:
                    before = normalized_solution[max(0, at - 5):at]
                    bare = re.search(r"(?:^|\s)([A-E])\s*$", before)
                    expected = chr(65 + choice_index)
                    if bare and bare.group(1) == expected:
                        inferred_letter = expected
                        break
        bold_letter = bold_keys.get(number, "")
        conflict = bool(explicit_letter and bold_letter and explicit_letter != bold_letter)
        if conflict:
            verified_letter = ""
            evidence = f"conflict: text={explicit_letter}, bold={bold_letter}"
        elif explicit_letter:
            verified_letter = explicit_letter
        elif bold_letter:
            verified_letter = bold_letter
            evidence = "bold choice in official solution PDF"
        else:
            verified_letter = ""
            evidence = "unverified text inference" if inferred_letter else "not recoverable"
        answer = ""
        if verified_letter:
            choice_index = ord(verified_letter) - 65
            choice_text = choices[choice_index] if choice_index < len(choices) else ""
            answer = f"{verified_letter} — {choice_text}" if choice_text else verified_letter
        explanation = solution_excerpt(solution_block, choices)
        records.append({
            "title": f"{year} F=ma{(' ' + var) if var else ''} · Question {number}",
            "topic": topic,
            "subtopic": subtopic,
            "source": "F=ma",
            "year": year,
            "variant": var,
            "problemNumber": str(number),
            "difficulty": level,
            "difficultyBasis": "inferred from exam position",
            "statement": statement,
            "statementLatex": latexify_prose(statement),
            "choices": choices,
            "choicesLatex": [latexify_choice(choice) for choice in choices],
            "answer": answer or "Answer available in the official solution PDF.",
            "answerLatex": latexify_answer(answer) if answer else "Answer available in the official solution PDF.",
            "correctChoice": verified_letter,
            "answerVerified": bool(verified_letter),
            "answerEvidence": evidence,
            "answerConflict": conflict,
            "explanation": explanation or "See the paired official solution PDF.",
            "explanationLatex": latexify_prose(explanation) if explanation else "See the paired official solution PDF.",
            "hasDiagram": bool(re.search(r"\b(shown|graph|figure|diagram|below|pictured)\b", statement, re.I)),
            "examFile": exam.name,
            "solutionFile": solution.name if solution else "",
        })
    return records


def split_usapho(text: str):
    matches = list(re.finditer(r"(?mi)^\s*(?:Question|Problem)\s+([ABC]?\d+)(?::\s*([^\n]+))?\s*$", text))
    result = {}
    for index, match in enumerate(matches):
        label = match.group(1).upper()
        if label in result:
            continue
        end = matches[index + 1].start() if index + 1 < len(matches) else len(text)
        title = (match.group(2) or "").strip()
        body = text[match.end():end].strip()
        result[label] = f"{title}\n{body}".strip()
    return result


def usapho_records(exam: Path, solution: Path | None, year: int):
    exam_blocks = split_usapho(pdf_text(exam))
    solution_blocks = split_usapho(pdf_text(solution)) if solution else {}
    records = []
    for label, block in exam_blocks.items():
        statement = compact(block)
        if len(statement) < 40:
            continue
        topic, subtopic = classify(statement)
        solution_block = solution_blocks.get(label, "")
        marker = re.search(r"\bSolution\b", solution_block, re.I)
        explanation = compact(solution_block[marker.start():] if marker else solution_block, 5000)
        short_title = ""
        first_line = block.strip().splitlines()[0].strip() if block.strip() else ""
        if 2 <= len(first_line.split()) <= 9 and len(first_line) < 70 and not first_line.lower().startswith(("a.", "part")):
            short_title = first_line
        records.append({
            "title": short_title or f"{year} USAPhO · Question {label}",
            "topic": topic,
            "subtopic": subtopic,
            "source": "USAPhO",
            "year": year,
            "variant": "",
            "problemNumber": label,
            "difficulty": 3,
            "difficultyBasis": "USAPhO free-response level",
            "statement": statement,
            "statementLatex": latexify_prose(statement),
            "choices": [],
            "choicesLatex": [],
            "answer": "Free response — reveal the official solution excerpt below.",
            "answerLatex": "Free response — reveal the official solution excerpt below.",
            "explanation": explanation or "See the paired official solution PDF.",
            "explanationLatex": latexify_prose(explanation) if explanation else "See the paired official solution PDF.",
            "hasDiagram": bool(re.search(r"\b(shown|graph|figure|diagram|below|pictured|schematic)\b", statement, re.I)),
            "examFile": exam.name,
            "solutionFile": solution.name if solution else "",
        })
    return records


def llm_categories(source: str):
    return FMA_LLM_CATEGORIES if source == "F=ma" else USAPHO_LLM_CATEGORIES


def classification_text(record: dict, record_lookup: dict) -> str:
    """Include a shared stem when a later F=ma question depends on it."""
    statement = record.get("statement", "")
    leader = record.get("sharedContextFrom", "")
    if leader:
        key = (record["year"], record["source"], record.get("variant", ""), leader)
        context = record_lookup.get(key, {}).get("statement", "")
        if context:
            statement = f"Shared information:\n{context}\n\nQuestion:\n{statement}"
    return statement[:8000]


def classification_fingerprint(record: dict, text: str, provider: str, model: str) -> str:
    payload = {
        "promptVersion": LLM_PROMPT_VERSION,
        "provider": provider,
        "model": model,
        "source": record["source"],
        "year": record["year"],
        "variant": record.get("variant", ""),
        "problemNumber": record["problemNumber"],
        "categories": llm_categories(record["source"]),
        "text": text,
    }
    encoded = json.dumps(payload, sort_keys=True, ensure_ascii=False).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def read_llm_cache(path: Path) -> dict:
    if not path.exists():
        return {"version": 1, "promptVersion": LLM_PROMPT_VERSION, "items": {}}
    try:
        document = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as error:
        raise RuntimeError(f"Could not read LLM cache {path}: {error}") from error
    if not isinstance(document.get("items"), dict):
        raise RuntimeError(f"LLM cache {path} does not contain an items object")
    return document


def write_llm_cache(path: Path, cache: dict):
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(path.name + ".tmp")
    temporary.write_text(json.dumps(cache, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    temporary.replace(path)


def responses_output_text(response: dict) -> str:
    if isinstance(response.get("output_text"), str):
        return response["output_text"]
    parts = []
    for item in response.get("output", []):
        for content in item.get("content", []):
            if content.get("type") == "refusal":
                raise RuntimeError(f"The classification request was refused: {content.get('refusal', '')}")
            if content.get("type") == "output_text" and isinstance(content.get("text"), str):
                parts.append(content["text"])
    if not parts:
        detail = response.get("incomplete_details") or response.get("status") or "no output text"
        raise RuntimeError(f"The Responses API returned {detail}")
    return "".join(parts)


def classification_schema(source: str) -> dict:
    categories = llm_categories(source)
    return {
        "type": "object",
        "additionalProperties": False,
        "properties": {
            "items": {
                "type": "array",
                "items": {
                    "type": "object",
                    "additionalProperties": False,
                    "properties": {
                        "id": {"type": "integer"},
                        "category": {"type": "string", "enum": list(categories)},
                        "confidence": {"type": "string", "enum": list(LLM_CONFIDENCE)},
                    },
                    "required": ["id", "category", "confidence"],
                },
            },
        },
        "required": ["items"],
    }


def classification_instructions(source: str) -> str:
    return f"""Classify each {source} physics problem into exactly one allowed category.
Choose the dominant physics skill needed to solve the problem, not merely an object or word in its story.
Return one item for every input id, preserve each id exactly, and do not add or omit ids.

Allowed taxonomy:
{LLM_DEFINITIONS[source]}"""


def validate_llm_labels(labels: list[dict], records: list[dict], source: str) -> list[dict]:
    categories = llm_categories(source)
    expected_ids = {item["id"] for item in records}
    returned_ids = [item.get("id") for item in labels]
    if len(returned_ids) != len(set(returned_ids)) or set(returned_ids) != expected_ids:
        raise RuntimeError(f"LLM returned ids {sorted(returned_ids)}; expected {sorted(expected_ids)}")
    for label in labels:
        if label.get("category") not in categories:
            raise RuntimeError(f"Invalid category returned: {label.get('category')}")
        if label.get("confidence") not in LLM_CONFIDENCE:
            raise RuntimeError(f"Invalid confidence returned: {label.get('confidence')}")
    return labels


def request_openai_labels(records: list[dict], source: str, model: str, api_key: str,
                          base_url: str, timeout: float, retries: int) -> list[dict]:
    schema = classification_schema(source)
    input_items = [{"id": item["id"], "problem": item["classificationText"]} for item in records]
    body = {
        "model": model,
        "store": False,
        "reasoning": {"effort": "low"},
        "instructions": classification_instructions(source),
        "input": json.dumps(input_items, ensure_ascii=False),
        "text": {
            "format": {
                "type": "json_schema",
                "name": "aapt_problem_categories",
                "strict": True,
                "schema": schema,
            }
        },
        "max_output_tokens": max(4000, len(records) * 150),
    }
    url = base_url.rstrip("/") + "/responses"
    data = json.dumps(body, ensure_ascii=False).encode("utf-8")
    last_error = None
    for attempt in range(retries):
        request = Request(url, data=data, method="POST", headers={
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json",
            "User-Agent": "phys-trivial-aapt-parser/2.0",
        })
        try:
            with urlopen(request, timeout=timeout) as response:
                result = json.loads(response.read().decode("utf-8"))
            parsed = json.loads(responses_output_text(result))
            return validate_llm_labels(parsed.get("items", []), records, source)
        except HTTPError as error:
            detail = error.read().decode("utf-8", errors="replace")[:1200]
            last_error = RuntimeError(f"Responses API HTTP {error.code}: {detail}")
            if error.code not in (408, 409, 429) and error.code < 500:
                break
        except (URLError, TimeoutError, OSError, json.JSONDecodeError, RuntimeError) as error:
            last_error = error
        if attempt + 1 < retries:
            time.sleep(min(2 ** attempt, 8))
    raise RuntimeError(f"LLM classification failed after {retries} attempt(s): {last_error}")


def gemini_output_text(response: dict) -> str:
    candidates = response.get("candidates") or []
    if not candidates:
        feedback = response.get("promptFeedback") or "no candidates"
        raise RuntimeError(f"Gemini returned {feedback}")
    candidate = candidates[0]
    parts = candidate.get("content", {}).get("parts", [])
    text_parts = [part["text"] for part in parts if isinstance(part.get("text"), str)]
    if not text_parts:
        raise RuntimeError(f"Gemini returned finish reason {candidate.get('finishReason', 'unknown')}")
    return "".join(text_parts)


def request_gemini_labels(records: list[dict], source: str, model: str, api_key: str,
                          base_url: str, timeout: float, retries: int) -> list[dict]:
    input_items = [{"id": item["id"], "problem": item["classificationText"]} for item in records]
    prompt = (classification_instructions(source) + "\n\nInput JSON:\n" +
              json.dumps(input_items, ensure_ascii=False))
    body = {
        "contents": [{"role": "user", "parts": [{"text": prompt}]}],
        "generationConfig": {
            "responseMimeType": "application/json",
            "responseJsonSchema": classification_schema(source),
            "temperature": 0,
            "maxOutputTokens": max(2000, len(records) * 100),
        },
    }
    url = f"{base_url.rstrip('/')}/models/{model}:generateContent"
    data = json.dumps(body, ensure_ascii=False).encode("utf-8")
    last_error = None
    for attempt in range(retries):
        request = Request(url, data=data, method="POST", headers={
            "x-goog-api-key": api_key,
            "Content-Type": "application/json",
            "User-Agent": "phys-trivial-aapt-parser/2.0",
        })
        try:
            with urlopen(request, timeout=timeout) as response:
                result = json.loads(response.read().decode("utf-8"))
            parsed = json.loads(gemini_output_text(result))
            return validate_llm_labels(parsed.get("items", []), records, source)
        except HTTPError as error:
            detail = error.read().decode("utf-8", errors="replace")[:1200]
            last_error = RuntimeError(f"Gemini API HTTP {error.code}: {detail}")
            if error.code not in (408, 409, 429) and error.code < 500:
                break
        except (URLError, TimeoutError, OSError, json.JSONDecodeError, RuntimeError) as error:
            last_error = error
        if attempt + 1 < retries:
            time.sleep(min(2 ** attempt, 8))
    raise RuntimeError(f"Gemini classification failed after {retries} attempt(s): {last_error}")


def request_llm_labels(records: list[dict], source: str, provider: str, model: str,
                       api_key: str, base_url: str, timeout: float, retries: int) -> list[dict]:
    if provider == "gemini":
        return request_gemini_labels(records, source, model, api_key, base_url, timeout, retries)
    return request_openai_labels(records, source, model, api_key, base_url, timeout, retries)


def apply_llm_classification(records: list[dict], provider: str, model: str, api_key: str, base_url: str,
                             cache_path: Path, batch_size: int, timeout: float,
                             retries: int, overwrite_cache: bool):
    cache = read_llm_cache(cache_path)
    cache.update({"version": 1, "promptVersion": LLM_PROMPT_VERSION,
                  "provider": provider, "model": model})
    cached_items = cache["items"]
    lookup = {
        (record["year"], record["source"], record.get("variant", ""), record["problemNumber"]): record
        for record in records
    }
    pending_by_source = {"F=ma": [], "USAPhO": []}
    hits = 0

    for record in records:
        text = classification_text(record, lookup)
        fingerprint = classification_fingerprint(record, text, provider, model)
        record["classificationText"] = text
        record["classificationFingerprint"] = fingerprint
        cached = None if overwrite_cache else cached_items.get(fingerprint)
        if (cached and cached.get("category") in llm_categories(record["source"])
                and cached.get("confidence") in LLM_CONFIDENCE):
            record["llmCategory"] = cached["category"]
            record["classificationConfidence"] = cached["confidence"]
            record["classificationProvider"] = provider
            hits += 1
        else:
            pending_by_source[record["source"]].append(record)

    missing = sum(len(items) for items in pending_by_source.values())
    request_count = sum((len(items) + batch_size - 1) // batch_size
                        for items in pending_by_source.values())
    print(f"LLM classification: {hits} cached, {missing} to classify in "
          f"{request_count} request(s) using {model}")
    for source, pending in pending_by_source.items():
        for start in range(0, len(pending), batch_size):
            batch = pending[start:start + batch_size]
            print(f"  {source}: classifying {start + 1}-{start + len(batch)} of {len(pending)}")
            labels = request_llm_labels(
                batch, source, provider, model, api_key, base_url, timeout, retries
            )
            by_id = {item["id"]: item for item in labels}
            for record in batch:
                label = by_id[record["id"]]
                record["llmCategory"] = label["category"]
                record["classificationConfidence"] = label["confidence"]
                record["classificationProvider"] = provider
                cached_items[record["classificationFingerprint"]] = {
                    "category": label["category"],
                    "confidence": label["confidence"],
                    "provider": provider,
                    "model": model,
                }
            write_llm_cache(cache_path, cache)

    for record in records:
        record["heuristicTopic"] = record["topic"]
        record["heuristicSubtopic"] = record["subtopic"]
        record["topic"] = record.pop("llmCategory")
        record["classificationMethod"] = f"{provider}-structured-output"
        record["classificationModel"] = model
        record["classificationPromptVersion"] = LLM_PROMPT_VERSION
        record.pop("classificationText", None)
        record.pop("classificationFingerprint", None)
    write_llm_cache(cache_path, cache)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("zipfile", type=Path)
    parser.add_argument("output", type=Path)
    parser.add_argument("--assets-dir", type=Path,
                        help="Render exact PDF question/solution crops into this assets directory")
    parser.add_argument("--dpi", type=int, default=144, help="PDF snippet resolution (default: 144)")
    parser.add_argument("--llm-classify", action="store_true",
                        help="Replace heuristic topics with the requested source-specific LLM taxonomy")
    parser.add_argument("--llm-provider", choices=("gemini", "openai"), default="gemini",
                        help="Classification API provider (default: gemini)")
    parser.add_argument("--llm-model",
                        help="Model id (default: gemini-3.5-flash-lite or gpt-5.6-luna)")
    parser.add_argument("--llm-base-url",
                        help="Override the selected provider's API base URL")
    parser.add_argument("--llm-api-key-env",
                        help="Override the selected provider's API-key environment variable")
    parser.add_argument("--llm-cache", type=Path,
                        help="Persistent classification cache (default: aapt-llm-tags.json beside output)")
    parser.add_argument("--llm-batch-size", type=int, default=50,
                        help="Problems per API request (default and maximum: 50)")
    parser.add_argument("--llm-timeout", type=float, default=120.0)
    parser.add_argument("--llm-retries", type=int, default=5)
    parser.add_argument("--llm-overwrite-cache", action="store_true",
                        help="Ignore cached classifications and request all labels again")
    args = parser.parse_args()
    if args.dpi < 72 or args.dpi > 300:
        parser.error("--dpi must be between 72 and 300")
    if args.llm_batch_size < 1 or args.llm_batch_size > 50:
        parser.error("--llm-batch-size must be between 1 and 50")
    if args.llm_timeout <= 0 or args.llm_retries < 1:
        parser.error("--llm-timeout and --llm-retries must be positive")
    provider_defaults = {
        "gemini": {
            "model": "gemini-3.5-flash-lite",
            "base_url": "https://generativelanguage.googleapis.com/v1beta",
            "api_key_env": "GEMINI_API_KEY",
        },
        "openai": {
            "model": "gpt-5.6-luna",
            "base_url": "https://api.openai.com/v1",
            "api_key_env": "OPENAI_API_KEY",
        },
    }
    selected = provider_defaults[args.llm_provider]
    llm_model = args.llm_model or selected["model"]
    llm_base_url = args.llm_base_url or selected["base_url"]
    llm_api_key_env = args.llm_api_key_env or selected["api_key_env"]
    api_key = os.environ.get(llm_api_key_env, "") if args.llm_classify else ""
    if args.llm_classify and not api_key:
        parser.error(
            f"--llm-classify with {args.llm_provider} requires an API key in "
            f"the {llm_api_key_env} environment variable"
        )
    records = []
    parsed_exams = []
    with tempfile.TemporaryDirectory(prefix="aapt-parse-") as temporary:
        with zipfile.ZipFile(args.zipfile) as archive:
            archive.extractall(temporary)
        root = Path(temporary)
        for exam, solution, kind, year, var in pair_files(root):
            print(f"Parsing {year} {kind}{(' ' + var) if var else ''}: {exam.name}")
            parsed_exams.append({"year": year, "source": kind, "variant": var, "examFile": exam.name,
                                 "solutionFile": solution.name if solution else ""})
            if kind == "F=ma":
                exam_records = fma_records(exam, solution, year, var)
            else:
                exam_records = usapho_records(exam, solution, year)
            if args.assets_dir:
                print(f"  Rendering PDF snippets at {args.dpi} dpi")
                problem_images = generate_pdf_snippets(
                    exam, kind, year, var, "problems", args.assets_dir, args.dpi,
                    expected_labels={record["problemNumber"] for record in exam_records}
                )
                solution_images = generate_pdf_snippets(
                    solution, kind, year, var, "solutions", args.assets_dir, args.dpi
                )
            else:
                problem_images, solution_images = {}, {}
            shared_groups = shared_question_groups(exam, kind)
            for record in exam_records:
                label = record["problemNumber"]
                record["problemImages"] = problem_images.get(label, [])
                record["solutionImages"] = solution_images.get(label, [])
                shared = shared_groups.get(label)
                record["contextImages"] = problem_images.get(shared["leader"], []) if shared else []
                record["sharedContextFrom"] = shared["leader"] if shared else ""
                record["sharedContextMembers"] = shared["members"] if shared else []
                record["displayMode"] = "pdf-snippets" if record["problemImages"] else "text-fallback"
            records.extend(exam_records)
    def record_order(record):
        label = record["problemNumber"]
        letter = re.sub(r"\d", "", label)
        number = int(re.sub(r"\D", "", label) or 0)
        return (record["year"], record["source"], record["variant"], letter, number)

    records.sort(key=record_order)
    for index, record in enumerate(records, 1):
        record["id"] = index
    if args.llm_classify:
        cache_path = args.llm_cache or args.output.with_name("aapt-llm-tags.json")
        apply_llm_classification(
            records, args.llm_provider, llm_model, api_key, llm_base_url, cache_path,
            args.llm_batch_size, args.llm_timeout, args.llm_retries,
            args.llm_overwrite_cache,
        )
    document = {
        "schemaVersion": 5,
        "generatedFrom": args.zipfile.name,
        "problemCount": len(records),
        "examCount": len(parsed_exams),
        "taggingNote": ("Topics use source-specific LLM classification; difficulty and LaTeX reconstruction "
                        "remain inferred automatically." if args.llm_classify else
                        "Topics, difficulty, and LaTeX reconstruction are inferred heuristically and can be edited."),
        "classification": {
            "method": f"{args.llm_provider}-structured-output" if args.llm_classify else "keyword-heuristic",
            "provider": args.llm_provider if args.llm_classify else "",
            "model": llm_model if args.llm_classify else "",
            "promptVersion": LLM_PROMPT_VERSION if args.llm_classify else "",
            "taxonomies": {
                "F=ma": list(FMA_LLM_CATEGORIES),
                "USAPhO": list(USAPHO_LLM_CATEGORIES),
            },
        },
        "mathFormat": "MathJax TeX using \\( ... \\) inline delimiters; plain-text fields are retained as fallbacks.",
        "latexRecoveryNote": "The PDFs were produced by pdfTeX but contain no embedded TeX source. LaTeX fields are conservative reconstructions from extracted PDF text and math symbols.",
        "assetFormat": "Exact grayscale WebP crops rendered from the supplied PDFs. Paths are relative to the website root.",
        "answerValidation": "Only independently verified correctChoice values should drive UI correctness; unverified F=ma choices remain neutral.",
        "topicCounts": dict(sorted(Counter(x["topic"] for x in records).items())),
        "exams": parsed_exams,
        "problems": records,
    }
    args.output.write_text(json.dumps(document, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(f"Wrote {len(records)} problems from {len(parsed_exams)} exams to {args.output}")


if __name__ == "__main__":
    main()