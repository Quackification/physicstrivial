# phys trivial

amctrivial style practice site for browsing physics olympiad problems by topic. The supplied archive has been parsed into 658 problems from 40 F=ma and USAPhO exams covering 2008–2025.

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

The structured data lives in `aapt-problems.json`, while 1,713 WebP crops live under `assets/problems/` and `assets/solutions/` Problem tags were generated from Gemini Flash (since i'm broke), so they may be inaccurate. Problem difficulty is generated heuristically from problem number.
