import subprocess
from pathlib import Path


def convert_to_pdf(pptx_path: Path) -> Path:
    output_dir = pptx_path.parent
    cmd = [
        "libreoffice",
        "--headless",
        "--convert-to",
        "pdf",
        "--outdir",
        str(output_dir),
        str(pptx_path),
    ]
    subprocess.run(cmd, check=True)
    return pptx_path.with_suffix(".pdf")
