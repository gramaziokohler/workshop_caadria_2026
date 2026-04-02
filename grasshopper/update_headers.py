"""
Parses a .ghx file, finds all base64-encoded script Text items,
decodes them, updates the # r: and # venv: header lines,
re-encodes to base64, and writes back to the file.

Usage:
    python update_script_headers.py <path_to.ghx> [--dry-run]
"""

import argparse
import base64
import re

# ============================================================
# CONFIGURATION - edit these values to set the new header
# ============================================================

# New requirements line (everything after "# r: ")
# Set to None to leave existing value unchanged
NEW_REQUIREMENTS = "timber_design==0.2.0"

# New venv line (everything after "# venv: ")
# Set to None to leave existing value unchanged
NEW_VENV = "caddria2026"

# ============================================================


def _is_header_line(line):
    return re.match(r"^#\s+(r|venv|env):", line) is not None


def ensure_header(script_text, new_requirements, new_venv):
    """Strip any existing header lines and prepend a clean header.

    Returns (updated_text, changed).
    """
    lines = script_text.split("\n")

    # Remove all existing header lines
    body = [line for line in lines if not _is_header_line(line)]

    # Strip leading blank lines left over from removed header
    while body and body[0].strip() == "":
        body.pop(0)

    # Build new header
    header = []
    if new_requirements is not None:
        header.append("# r: " + new_requirements)
    if new_venv is not None:
        header.append("# venv: " + new_venv)

    if header:
        header.append("")  # blank line between header and body

    result = "\n".join(header + body)
    changed = result != script_text
    return result, changed


# Matches <item name="Text" ...>BASE64</item> inside <chunk name="Script"> blocks.
# We rely on the GHX structure: the Text item always appears inside a Script chunk.
TEXT_ITEM_RE = re.compile(
    r'(<chunk name="Script">.*?'
    r'<item name="Text" type_name="gh_string" type_code="10">)'
    r"([A-Za-z0-9+/=\s]+)"
    r"(</item>)",
    re.DOTALL,
)


def process_ghx(ghx_path, dry_run=False):
    with open(ghx_path, "r", encoding="utf-8") as f:
        content = f.read()

    report = []
    count = 0

    def _replace(m):
        nonlocal count
        prefix = m.group(1)
        b64 = m.group(2).strip()
        suffix = m.group(3)

        try:
            code = base64.b64decode(b64).decode("utf-8")
        except Exception:
            return m.group(0)

        new_code, changed = ensure_header(code, NEW_REQUIREMENTS, NEW_VENV)
        if not changed:
            first_line = code.split("\n")[0][:60]
            report.append("  unchanged: {}...".format(first_line))
            return m.group(0)

        count += 1
        new_b64 = base64.b64encode(new_code.encode("utf-8")).decode("utf-8")
        first_line = new_code.split("\n")[0][:60]
        report.append("  updated:   {}...".format(first_line))
        return prefix + new_b64 + suffix

    new_content = TEXT_ITEM_RE.sub(_replace, content)

    print("Scripts processed: {}".format(len(report)))
    print("Scripts updated:   {}".format(count))
    for line in report:
        print(line)

    if dry_run:
        print("\nDry run - no file written.")
    elif count > 0:
        with open(ghx_path, "w", encoding="utf-8") as f:
            f.write(new_content)
        print("\nFile written: {}".format(ghx_path))
    else:
        print("\nNo changes needed.")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Update script headers in a .ghx file")
    parser.add_argument("ghx_file", help="Path to the .ghx file")
    parser.add_argument(
        "--dry-run", action="store_true", help="Preview changes without writing"
    )
    args = parser.parse_args()
    process_ghx(args.ghx_file, dry_run=args.dry_run)
