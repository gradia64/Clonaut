#!/usr/bin/env python3
"""Aggiorna i cataloghi clonaut/locale/<lingua>.po dai testi nel codice.

Estrae ogni `tr("…")` e `N_("…")` dei moduli clonaut (anche i testi spezzati
su più righe: per Python sono un'unica costante), conserva le traduzioni già
fatte, aggiunge i testi nuovi con traduzione vuota e toglie quelli che non
esistono più. Poi elenca le voci da tradurre.

    python3 scripts/update-po.py            aggiorna tutti i cataloghi
    python3 scripts/update-po.py --check    solo controllo: esce con 1 se un
                                            catalogo non è aggiornato o completo

tests/test_i18n.py fa lo stesso controllo.
"""

from __future__ import annotations

import ast
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
PACKAGE = ROOT / "clonaut"
sys.path.insert(0, str(ROOT))
from clonaut.i18n import LANGUAGES, LOCALE_DIR, SOURCE_LANGUAGE, parse_po  # noqa: E402

MARKERS = {"tr", "N_"}


def extract(package: Path = PACKAGE) -> dict[str, list[str]]:
    """{testo: ["clonaut/…py:riga", …]} nell'ordine in cui compaiono."""
    found: dict[str, list[str]] = {}
    for path in sorted(package.rglob("*.py")):
        tree = ast.parse(path.read_text(encoding="utf-8"), str(path))
        for node in ast.walk(tree):
            if not (isinstance(node, ast.Call) and isinstance(node.func, ast.Name)
                    and node.func.id in MARKERS and node.args):
                continue
            arg = node.args[0]
            if isinstance(arg, ast.Name) and node.func.id == "tr":
                continue   # tr(label): un testo già marcato altrove con N_()
            if not (isinstance(arg, ast.Constant) and isinstance(arg.value, str)):
                rel = path.relative_to(package.parent)
                raise SystemExit(f"{rel}:{node.lineno}: {node.func.id}() vuole un "
                                 "testo fisso (niente f-string: usa .format())")
            ref = f"{path.relative_to(package.parent)}:{node.lineno}"
            found.setdefault(arg.value, []).append(ref)
    # ast.walk non segue l'ordine del file: si riordina per posizione
    def key(item):
        file, line = item[1][0].rsplit(":", 1)
        return file, int(line)
    return dict(sorted(found.items(), key=key))


def _quote(text: str) -> str:
    out = text.replace("\\", "\\\\").replace('"', '\\"').replace("\t", "\\t")
    lines = out.split("\n")
    parts = [line + "\\n" for line in lines[:-1]] + ([lines[-1]] if lines[-1] else [])
    if len(parts) <= 1 and len(out) < 70:
        return f'"{parts[0] if parts else ""}"'
    chunks = []
    for part in parts:   # a capo sugli spazi, righe di al più ~76 caratteri
        line = ""
        for word in part.split(" "):
            if line and len(line) + len(word) > 74:
                chunks.append(line)
                line = ""
            line += word + " "
        chunks.append(line[:-1])
    return '""\n' + "\n".join(f'"{c}"' for c in chunks)


def render(lang: str, messages: dict[str, list[str]], old: dict[str, dict]) -> str:
    header = (f"# Clonaut — {LANGUAGES[lang]}\n"
              "# Generato da scripts/update-po.py: si modificano solo i msgstr.\n"
              'msgid ""\n'
              'msgstr ""\n'
              '"Content-Type: text/plain; charset=UTF-8\\n"\n'
              f'"Language: {lang}\\n"\n')
    blocks = [header]
    for msgid, refs in messages.items():
        prev = old.get(msgid, {})
        lines = [f"#: {' '.join(refs)}"]
        if "fuzzy" in prev.get("flags", ()):
            lines.append("#, fuzzy")
        if "{" in msgid:
            lines.append("#, python-brace-format")
        lines.append(f"msgid {_quote(msgid)}")
        lines.append(f"msgstr {_quote(prev.get('msgstr', ''))}")
        blocks.append("\n".join(lines) + "\n")
    return "\n".join(blocks)


def main(argv: list[str]) -> int:
    check = "--check" in argv
    messages = extract()
    status = 0
    for lang in LANGUAGES:
        if lang == SOURCE_LANGUAGE:
            continue
        path = LOCALE_DIR / f"{lang}.po"
        text = path.read_text(encoding="utf-8") if path.exists() else ""
        old = {e["msgid"]: e for e in parse_po(text) if e["msgid"]}
        new = render(lang, messages, old)
        todo = [m for m in messages
                if not old.get(m, {}).get("msgstr") or "fuzzy" in old[m]["flags"]]
        if check:
            if new != text:
                print(f"{path.relative_to(ROOT)}: non aggiornato "
                      "(python3 scripts/update-po.py)")
                status = 1
        else:
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(new, encoding="utf-8")
            gone = len(set(old) - set(messages))
            print(f"{path.relative_to(ROOT)}: {len(messages)} testi, "
                  f"{len(todo)} da tradurre, {gone} tolti")
        if todo:
            status = status or (1 if check else 0)
            for m in todo[:20]:
                print("  da tradurre:", m.replace("\n", "⏎")[:90])
            if len(todo) > 20:
                print(f"  … e altri {len(todo) - 20}")
    return status


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
