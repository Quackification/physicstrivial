# phys trivial

A zero-build static practice site for browsing physics olympiad problems by topic. The supplied archive has been parsed into 658 problems from 40 F=ma and USAPhO exams covering 2008–2025.

## Run locally
Extract and run

```sh
python3 -m http.server 8000
```

Then visit `http://localhost:8000`.

If you open `index.html` directly by double-clicking it, most browsers block JavaScript from fetching a neighboring JSON file. The site displays a **choose aapt-problems.json** button as a fallback, but serving the folder is recommended because the problem and solution crops are separate image assets.

## Content note

Problem statements, answer choices, diagrams, and solutions are displayed as exact cropped images rendered from the user-supplied PDFs. The dataset contains:

- 550 F=ma multiple-choice problems
- 108 USAPhO free-response problems
- Topic, subtopic, source exam, year, problem number, and inferred difficulty tags
- Recovered answer keys for 492 F=ma problems
- Exact PDF crops for all 658 problems
- PDF solution crops for 632 problems; answer-key-only PDFs use the recovered answer letter
- Five letter-only response buttons for F=ma and no response buttons for USAPhO
- Shared stems are repeated above all 38 dependent follow-up questions across two- and three-question groups
- 447 F=ma answer letters independently verified from explicit keys/markers or reliable bold-font metadata
- 103 ambiguous answer letters left neutral; selecting them reveals the official solution without claiming right or wrong

The structured data lives in `aapt-problems.json`, while 1,713 WebP crops live under `assets/problems/` and `assets/solutions/`. By default, topic and difficulty tags are generated heuristically and can be edited directly.

The parser validates that every F=ma exam has question labels 1–25 and that each USAPhO crop set contains the exact six labels parsed from that historical exam. It aborts rather than silently pairing a crop with the wrong problem.

To rebuild the dataset after changing or replacing the ZIP, run:

```sh
python3 parse_aapt_archive.py aapt-exams.zip aapt-problems.json \
  --assets-dir assets --dpi 144
```

## LLM topic classification

Add `--llm-classify` to replace the broad keyword topics with a source-specific, one-category LLM classification. The F=ma taxonomy is Collisions, Dynamics, Energy, Fluids, Gravity, Kinematics, Oscillatory Motion, Dimensional Analysis, Rigid Bodies, and Other. The USAPhO taxonomy is Mechanics, Electromagnetism, Thermodynamics, Relativity, Nuclear, Particle Physics, Waves, Optics, and Other. The classifier is instructed to use Other only when none of the named physics categories is a defensible primary fit.

Set an API key, then rebuild:

```sh
export OPENAI_API_KEY="your-key-here"
python3 parse_aapt_archive.py aapt-exams.zip aapt-problems.json \
  --assets-dir assets --dpi 144 --llm-classify
```

The classifier uses the OpenAI Responses API with strict structured output and defaults to `gpt-5.6-luna`. Change it with `--llm-model`. Results are saved incrementally to `aapt-llm-tags.json`, so reruns reuse completed classifications and only request changed or missing problems. Use `--llm-overwrite-cache` only when you intentionally want to classify everything again.

For questions that depend on “the following information,” the shared stem is included in the LLM input. The original keyword topic and subtopic are retained in `heuristicTopic` and `heuristicSubtopic`; the website's `topic` field becomes the LLM category.

The source PDFs were created with pdfTeX, but they do not embed their original `.tex` files. Exact image crops are therefore the primary display. Reconstructed LaTeX and plain text remain only as fallbacks when an image is unavailable.

The website loads MathJax from jsDelivr and automatically renders the generated LaTeX fields. An internet connection is required for MathJax unless you download and host MathJax locally.

## Download the official exam PDFs

Prism keeps the downloader as `download_aapt_exams.py.txt`. Download or copy it, remove only the final `.txt`, and run:

```sh
python3 download_aapt_exams.py --output aapt-exams
```

Preview links without downloading:

```sh
python3 download_aapt_exams.py --dry-run
```

Download selected years:

```sh
python3 download_aapt_exams.py --year 2024 --year 2025
```

The script uses only Python's standard library, pauses between requests, skips existing files, organizes PDFs by year, and creates a `manifest.json` containing source URLs and SHA-256 checksums.
