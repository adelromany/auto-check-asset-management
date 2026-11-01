# Third-party notices for the visual documentation

The files in `docs/visual/` are generated with **Archify 3.2.0** from
<https://github.com/tt-a1i/archify>, pinned at commit
`a4065941f12be7967436261d9934784e381d423c`.

Archify is a development tool. It is fetched into the git-ignored
`.tools/archify` directory by `scripts/fetch_archify.sh` (or the PowerShell
equivalent) and is not an application dependency.

## Archify

- License: Apache License 2.0, except where a file, package manifest or
  third-party notice says otherwise.
- Copyright: Archify, Copyright (c) 2026 tt-a1i (Archify) and
  Copyright (c) 2025 Cocoon AI.
- Full license: [`licenses/ARCHIFY-LICENSE.txt`](licenses/ARCHIFY-LICENSE.txt)
- Notice: [`licenses/ARCHIFY-NOTICE.txt`](licenses/ARCHIFY-NOTICE.txt)
- Complete upstream third-party notices:
  [`licenses/ARCHIFY-THIRD-PARTY-NOTICES.md`](licenses/ARCHIFY-THIRD-PARTY-NOTICES.md)

Each delivered HTML file embeds Archify's viewer code and its notices; the
notices are not removed or rewritten. The diagrams themselves are authored
data owned by this repository.

## JetBrains Mono

Delivered Archify artifacts embed the JetBrains Mono variable font subsets
served by Google Fonts. The font is distributed under the SIL Open Font
License 1.1.

- Copyright 2020 The JetBrains Mono Project Authors
  (<https://github.com/JetBrains/JetBrainsMono>).
- Full license:
  [`licenses/JETBRAINS-MONO-OFL.txt`](licenses/JETBRAINS-MONO-OFL.txt)

## Brand marks

Archify can embed optional third-party brand marks. This repository does not
recolor or redraw them, and their inclusion does not imply sponsorship or
endorsement. The per-mark sources, recorded licenses and trademark caveats are
listed in
[`licenses/ARCHIFY-THIRD-PARTY-NOTICES.md`](licenses/ARCHIFY-THIRD-PARTY-NOTICES.md).

## Rebuilding

```bash
scripts/fetch_archify.sh
.venv/bin/python tools/visual/build_visuals.py build
.venv/bin/python tools/visual/build_visuals.py check
```

The generated pages are self-contained and make no network requests when
opened offline.
