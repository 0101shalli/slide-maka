import subprocess
from pathlib import Path
import os


def convert_to_pdf(pptx_path: Path) -> Path:
    """
    Convert PPTX to PDF using the shared libreoffice service.
    Files are written to /tmp which is mounted to the libreoffice container.
    """
    output_dir = pptx_path.parent
    
    # Ensure the path is accessible (in /tmp or app mounted directory)
    cmd = [
        "libreoffice",
        "--headless",
        "--convert-to",
        "pdf",
        "--outdir",
        str(output_dir),
        str(pptx_path),
    ]
    
    try:
        subprocess.run(cmd, check=True, timeout=120)
    except FileNotFoundError:
        raise RuntimeError(
            "libreoffice not found. Ensure the libreoffice service is running "
            "or install it in the container."
        )
    
    pdf_path = pptx_path.with_suffix(".pdf")
    if not pdf_path.exists():
        raise RuntimeError(f"PDF conversion failed: {pdf_path} was not created")
    
    return pdf_path
