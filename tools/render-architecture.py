#!/usr/bin/env python3
"""Render canonical Mermaid blocks in docs/ARCHITECTURE.md with an existing local Mermaid CLI and browser."""

import hashlib
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import tempfile


def main():
    root = Path(__file__).resolve().parents[1]
    source = root / "docs/ARCHITECTURE.md"
    blocks = re.findall(r"<!-- architecture:([a-z-]+) -->\s*```mermaid\n(.*?)\n```", source.read_text(), re.S)
    if {name for name, _ in blocks} != {"overview", "turn-flow", "qq-delivery"} or len(blocks) != 3:
        raise SystemExit("Expected the three named canonical architecture blocks")
    cli = os.environ.get("MERMAID_CLI") or shutil.which("mmdc")
    if not cli or not Path(cli).is_file():
        raise SystemExit("Set MERMAID_CLI to a locally installed @mermaid-js/mermaid-cli executable")
    browser = os.environ.get("ARCHITECTURE_BROWSER") or shutil.which("chromium") or shutil.which("google-chrome")
    mac_chrome = Path("/Applications/Google Chrome.app/Contents/MacOS/Google Chrome")
    if not browser and mac_chrome.is_file():
        browser = str(mac_chrome)
    if not browser or not Path(browser).is_file():
        raise SystemExit("Set ARCHITECTURE_BROWSER to an existing Chrome/Chromium executable")
    output = root / "docs/architecture"
    output.mkdir(exist_ok=True)
    receipt = {"canonical": "docs/ARCHITECTURE.md", "mermaidCli": subprocess.check_output([cli, "--version"], text=True).strip(), "diagrams": []}
    with tempfile.TemporaryDirectory(prefix="aijade-architecture-") as temp:
        work = Path(temp)
        (work / "browser.json").write_text(json.dumps({"executablePath": browser}))
        (work / "mermaid.json").write_text(json.dumps({
            "fontFamily": "PingFang SC, Microsoft YaHei, Noto Sans CJK SC, sans-serif",
            "flowchart": {"htmlLabels": False, "curve": "linear", "wrappingWidth": 280},
            "themeVariables": {"fontSize": "17px"},
        }))
        for name, diagram in blocks:
            if "accTitle:" not in diagram or "accDescr:" not in diagram or "%%{init" in diagram:
                raise SystemExit(f"Missing accessible description or forbidden inline theme: {name}")
            mermaid = work / f"{name}.mmd"
            mermaid.write_text(diagram + "\n")
            artifacts = {}
            for extension in ["svg", "png"]:
                target = output / f"{name}.{extension}"
                command = [cli, "-i", str(mermaid), "-o", str(target), "-b", "white", "--size", "2200", "--no-font-embed",
                           "-p", str(work / "browser.json"), "-c", str(work / "mermaid.json")]
                result = subprocess.run(command, capture_output=True, text=True, check=False)
                if result.returncode or not target.is_file() or not target.stat().st_size:
                    raise SystemExit(result.stderr or result.stdout or f"Empty diagram: {target}")
                artifacts[str(target.relative_to(root))] = hashlib.sha256(target.read_bytes()).hexdigest()
            receipt["diagrams"].append({"name": name, "mermaidSha256": hashlib.sha256((diagram + "\n").encode()).hexdigest(), "artifactsSha256": artifacts})
    print(json.dumps(receipt, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
