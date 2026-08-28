# c2pip/cli.py

from __future__ import annotations

import argparse
import re
import shutil
import sys
from pathlib import Path
from typing import Sequence

from .builder import BuildError, build_project
from .generator import ProjectGenerator
from .publisher import PublishError, publish_project
from .scanner import ScanError, scan_file


VERSION = "0.1.0"


class CLIError(Exception):
    """Raised for expected command-line errors."""


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="c2pip",
        description=(
            "Build Python packages from C source/header files "
            "with minimal configuration."
        ),
    )

    parser.add_argument(
        "--version",
        action="version",
        version=f"%(prog)s {VERSION}",
    )

    subparsers = parser.add_subparsers(
        dest="command",
        required=True,
        metavar="COMMAND",
    )

    # ---------------------------------------------------------
    # init
    # ---------------------------------------------------------

    init_parser = subparsers.add_parser(
        "init",
        help="Create a c2pip project from a C source/header file.",
        description=(
            "Scan a C file, generate a Python extension wrapper, "
            "and create the package project."
        ),
    )

    init_parser.add_argument(
        "source",
        type=Path,
        help="C source/header file to scan.",
    )

    init_parser.add_argument(
        "--name",
        required=True,
        help="PyPI package name.",
    )

    init_parser.add_argument(
        "--author",
        required=True,
        help="Package author.",
    )

    init_parser.add_argument(
        "--output",
        "-o",
        type=Path,
        default=Path("."),
        help="Output project directory. Defaults to the current directory.",
    )

    init_parser.set_defaults(func=command_init)

    # ---------------------------------------------------------
    # build
    # ---------------------------------------------------------

    build_parser = subparsers.add_parser(
        "build",
        help="Build a wheel for the current project.",
    )

    build_parser.add_argument(
        "--sdist",
        action="store_true",
        help="Build both wheel and source distribution.",
    )

    build_parser.add_argument(
        "--clean",
        action="store_true",
        help="Remove previous build artifacts before building.",
    )

    build_parser.set_defaults(func=command_build)

    # ---------------------------------------------------------
    # publish
    # ---------------------------------------------------------

    publish_parser = subparsers.add_parser(
        "publish",
        help="Check and upload distributions to PyPI.",
    )

    publish_parser.add_argument(
        "--repository",
        default="pypi",
        help=(
            "Twine repository name. Defaults to 'pypi'. "
            "Use a configured repository such as 'testpypi' when needed."
        ),
    )

    publish_parser.add_argument(
        "--skip-check",
        action="store_true",
        help="Skip 'twine check' before uploading.",
    )

    publish_parser.set_defaults(func=command_publish)

    # ---------------------------------------------------------
    # new
    # ---------------------------------------------------------

    new_parser = subparsers.add_parser(
        "new",
        help="Create an empty C-to-Python project.",
    )

    new_parser.add_argument(
        "name",
        help="Project/package name.",
    )

    new_parser.add_argument(
        "--author",
        default="",
        help="Package author.",
    )

    new_parser.add_argument(
        "--output",
        "-o",
        type=Path,
        default=Path("."),
        help="Parent directory. Defaults to the current directory.",
    )

    new_parser.set_defaults(func=command_new)

    # ---------------------------------------------------------
    # clean
    # ---------------------------------------------------------

    clean_parser = subparsers.add_parser(
        "clean",
        help="Remove generated build artifacts.",
    )

    clean_parser.set_defaults(func=command_clean)

    return parser


def command_init(args: argparse.Namespace) -> int:
    source: Path = args.source

    if not source.exists():
        raise CLIError(f"Source file does not exist: {source}")

    if not source.is_file():
        raise CLIError(f"Source path is not a file: {source}")

    print(f"Scanning {source}...")

    functions = scan_file(source)

    print(f"Found {len(functions)} function(s).")

    generator = ProjectGenerator(
        name=args.name,
        author=args.author,
        functions=functions,
        source_file=source.name,
        output_dir=args.output,
    )

    project_dir = generator.generate()

    print()
    print(f"✓ Project created: {project_dir}")
    print()
    print("Next steps:")
    print(f"  cd {project_dir}")
    print("  c2pip build")
    print("  c2pip publish")

    return 0


def command_build(args: argparse.Namespace) -> int:
    project_dir = Path.cwd()

    if args.clean:
        _clean_build_artifacts(project_dir)

    print("Building project...")

    build_project(
        project_dir=project_dir,
        build_sdist=args.sdist,
    )

    print()
    print("✓ Build successful.")
    print(
        f"Distributions are available in: "
        f"{project_dir / 'dist'}"
    )

    return 0


def command_publish(args: argparse.Namespace) -> int:
    project_dir = Path.cwd()

    dist_dir = project_dir / "dist"

    if not dist_dir.exists():
        raise CLIError(
            "dist/ does not exist. Run 'c2pip build' first."
        )

    print("Publishing project...")

    publish_project(
        project_dir=project_dir,
        repository=args.repository,
        skip_check=args.skip_check,
    )

    print()
    print("✓ Package published successfully.")

    return 0


def command_new(args: argparse.Namespace) -> int:
    output_root: Path = args.output.resolve()
    project_dir = output_root / args.name

    if project_dir.exists():
        raise CLIError(
            f"Directory already exists: {project_dir}"
        )

    project_dir.mkdir(parents=True)

    package_name = _normalize_package_name(args.name)

    (project_dir / package_name).mkdir()

    _write_text(
        project_dir / "README.md",
        f"""# {args.name}

Python bindings for a native C library generated with c2pip.

## Development

Build the package with:

    c2pip build
""",
    )

    _write_text(
        project_dir / "c2pip.spec",
        f"""[project]
name = {args.name}
version = 0.1.0
author = {args.author}
""",
    )

    _write_text(
        project_dir / package_name / "__init__.py",
        """from . import _core

__all__ = [
    "_core",
]
""",
    )

    _write_text(
        project_dir / ".gitignore",
        """__pycache__/
*.py[cod]
*.so
*.pyd
*.dll
*.dylib

build/
dist/
*.egg-info/
.pytest_cache/
.mypy_cache/
""",
    )

    print(f"✓ Created new project: {project_dir}")

    return 0


def command_clean(args: argparse.Namespace) -> int:
    project_dir = Path.cwd()

    removed = _clean_build_artifacts(project_dir)

    if removed:
        print("✓ Cleaned build artifacts.")
    else:
        print("Nothing to clean.")

    return 0


def _clean_build_artifacts(project_dir: Path) -> bool:
    targets = (
        "build",
        "dist",
    )

    removed = False

    for target in targets:
        path = project_dir / target

        if not path.exists():
            continue

        if path.is_dir():
            shutil.rmtree(path)
            removed = True

    for path in project_dir.glob("*.egg-info"):
        if path.is_dir():
            shutil.rmtree(path)
            removed = True

    return removed


def _normalize_package_name(name: str) -> str:
    package_name = re.sub(
        r"[-.]+",
        "_",
        name.strip(),
    ).lower()

    if not package_name:
        raise CLIError("Package name cannot be empty.")

    return package_name


def _write_text(path: Path, content: str) -> None:
    path.write_text(
        content.rstrip() + "\n",
        encoding="utf-8",
    )


def main(argv: Sequence[str] | None = None) -> int:
    parser = build_parser()

    try:
        args = parser.parse_args(argv)
        return args.func(args)

    except (
        CLIError,
        ScanError,
        BuildError,
        PublishError,
        ValueError,
    ) as exc:
        print(
            f"c2pip: error: {exc}",
            file=sys.stderr,
        )
        return 1

    except KeyboardInterrupt:
        print(
            "\nc2pip: interrupted.",
            file=sys.stderr,
        )
        return 130


if __name__ == "__main__":
    raise SystemExit(main())
