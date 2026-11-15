"""Check repository Markdown relative file links, anchors and screenshot references."""

import re
from pathlib import Path
from urllib.parse import unquote

ROOT = Path(__file__).resolve().parents[1]


def headings(text):
    seen, result = {}, set()
    for line in text.splitlines():
        if re.match(r"^#{1,6} ", line):
            heading = re.sub(r"^#{1,6} +", "", line).strip().lower()
            heading = re.sub(r"[^\w\- ]", "", heading).replace(" ", "-")
            index = seen.get(heading, 0)
            seen[heading] = index + 1
            result.add(heading + (f"-{index}" if index else ""))
    return result


def main():
    files = sorted([*ROOT.glob("*.md"), *(ROOT / "docs").rglob("*.md")])
    errors, checked, images = [], 0, set()
    for path in files:
        text = path.read_text(encoding="utf-8-sig")
        for match in re.finditer(r"(!?)\[[^\]]*\]\(([^)\s]+)(?:\s+[^)]*)?\)", text):
            target = unquote(match[2].strip("<>"))
            if re.match(r"^[a-z]+:", target):
                continue
            name, _, anchor = target.partition("#")
            destination = (path.parent / name).resolve() if name else path
            checked += 1
            if not destination.is_relative_to(ROOT) or not destination.is_file():
                errors.append(f"{path.relative_to(ROOT)}: missing/unsafe file {target}")
            elif (
                anchor
                and destination.suffix == ".md"
                and anchor not in headings(destination.read_text(encoding="utf-8-sig"))
            ):
                errors.append(f"{path.relative_to(ROOT)}: missing heading {target}")
            if match[1]:
                images.add(destination)
    screenshots = set((ROOT / "docs/images").glob("*.jpg"))
    if len(screenshots) != 7 or not screenshots <= images:
        errors.append("Expected seven referenced genuine screenshot files")
    if errors:
        raise SystemExit("\n".join(errors))
    print(f"PASS: {len(files)} Markdown files, {checked} local links, seven screenshots")


if __name__ == "__main__":
    main()
