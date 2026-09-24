"""Shared build inputs for Windows and Mac Unicode document exports."""

from pathlib import Path


def collect_pdf_runtime(root: Path):
    from PyInstaller.utils.hooks import collect_all, collect_data_files, copy_metadata

    datas, binaries, imports = [], [], []
    for package in ("fpdf", "fontTools", "uharfbuzz", "regex", "defusedxml"):
        package_data, package_binaries, package_imports = collect_all(package)
        datas.extend(package_data)
        binaries.extend(package_binaries)
        imports.extend(package_imports)
    # Keep the complete fpdf2 Python source editable alongside the application.
    # The runtime hook gives this copy precedence over PyInstaller's archive.
    datas.extend(
        (source, "pdf_runtime/" + destination)
        for source, destination in collect_data_files("fpdf", include_py_files=True)
    )
    for distribution in (
        "fpdf2",
        "fonttools",
        "uharfbuzz",
        "regex",
        "defusedxml",
        "pillow",
    ):
        datas.extend(copy_metadata(distribution))
    datas.extend(
        (str(path), "pdf_runtime/licenses")
        for path in (root / "knight_flow/assets/licenses/pdf").glob("*.txt")
    )
    datas.append((str(root / "THIRD_PARTY_NOTICES.md"), "."))
    return datas, binaries, imports
