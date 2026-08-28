# c2pip/cli.py

from __future__ import annotations

import argparse
import re
import shutil
import sys
from pathlib import Path
from typing import Sequence

from .builder import BuildError, build_project
from .generator import GenerationError, ProjectGenerator
from .publisher import PublishError, check_project, publish_project
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

    init_parser = subparsers.add_parser(
        "init",
        help="Create a c2pip project from a C source/header file.",
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
        help="Output directory.",
    )

    init_parser.set_defaults(func=command_init)

    build_parser = subparsers.add_parser(
        "build",
        help="Build a wheel for the current project.",
    )

    build_parser.add_argument(
        "--clean",
        action="store_true",
        help="Remove previous build artifacts first.",
    )

    build_parser.add_argument(
        "--verbose",
        "-v",
        action="store_true",
        help="Show detailed build information.",
    )

    build_parser.set_defaults(func=command_build)

    publish_parser = subparsers.add_parser(
        "publish",
        help="Check and upload distributions to PyPI.",
    )

    publish_parser.add_argument(
        "--repository",
        choices=("pypi", "testpypi"),
        default="pypi",
        help="Repository to upload to.",
    )

    publish_parser.add_argument(
        "--skip-check",
        action="store_true",
        help="Skip distribution validation.",
    )

    publish_parser.add_argument(
        "--token",
        default=None,
        help="PyPI API token.",
    )

    publish_parser.add_argument(
        "--verbose",
        "-v",
        action="store_true",
        help="Show detailed publishing information.",
    )

    publish_parser.set_defaults(func=command_publish)

    new_parser = subparsers.add_parser(
        "new",
        help="Create an empty c2pip project.",
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
        help="Parent directory.",
    )

    new_parser.set_defaults(func=command_new)

    clean_parser = subparsers.add_parser(
        "clean",
        help="Remove generated build artifacts.",
    )

    clean_parser.set_defaults(func=command_clean)

    return parser


def command_init(args: argparse.Namespace) -> int:
    source = args.source.resolve()

    if not source.exists():
        raise CLIError(
            f"Source file does not exist: {source}"
        )

    if not source.is_file():
        raise CLIError(
            f"Source path is not a file: {source}"
        )

    allowed_extensions = {
        ".h",
        ".c",
        ".cc",
        ".cpp",
        ".cxx",
    }

    if source.suffix.lower() not in allowed_extensions:
        raise CLIError(
            "Source must be a C or C++ source/header file."
        )

    output_root = args.output.resolve()
    output_root.mkdir(
        parents=True,
        exist_ok=True,
    )

    project_dir = (
        output_root
        / _normalize_package_name(args.name)
    )

    if project_dir.exists():
        raise CLIError(
            f"Project directory already exists: {project_dir}"
        )

    print(f"Scanning {source}...")

    try:
        functions = scan_file(source)
    except ScanError:
        raise
    except Exception as exc:
        raise CLIError(
            f"Failed to scan {source}: {exc}"
        ) from exc

    print(
        f"Found {len(functions)} function(s)."
    )

    generator = ProjectGenerator(
        name=args.name,
        author=args.author,
        functions=functions,
        source_file=source.name,
        output_dir=project_dir,
    )

    try:
        generated_dir = generator.generate()
    except GenerationError:
        raise
    except Exception as exc:
        raise CLIError(
            f"Failed to generate project: {exc}"
        ) from exc

    destination_source = (
        generated_dir / source.name
    )

    if source.resolve() != destination_source.resolve():
        shutil.copy2(
            source,
            destination_source,
        )

    print()
    print(
        f"✓ Project created: {generated_dir}"
    )
    print()
    print("Next steps:")
    print(f"  cd {generated_dir}")
    print("  c2pip build")
    print("  c2pip publish")

    return 0


def command_build(args: argparse.Namespace) -> int:
    project_dir = Path.cwd()

    print(
        f"Building project in {project_dir}..."
    )

    wheels = build_project(
        project_dir=project_dir,
        clean=args.clean,
        verbose=args.verbose,
    )

    print()
    print("✓ Build successful.")
    print(
        f"Distributions are available in: "
        f"{project_dir / 'dist'}"
    )

    for wheel in wheels:
        print(f"  → {wheel.name}")

    return 0


def command_publish(args: argparse.Namespace) -> int:
    project_dir = Path.cwd()
    dist_dir = project_dir / "dist"

    if not dist_dir.is_dir():
        raise CLIError(
            "dist/ does not exist. Run 'c2pip build' first."
        )

    distributions = [
        path
        for path in dist_dir.iterdir()
        if path.is_file()
        and path.suffix in {
            ".whl",
            ".gz",
            ".zip",
        }
    ]

    if not distributions:
        raise CLIError(
            "No distributions were found in dist/. "
            "Run 'c2pip build' first."
        )

    if not args.skip_check:
        print("Checking distributions...")
        check_project(project_dir)

    print()
    print(
        f"Publishing to {args.repository}..."
    )

    publish_project(
        project_dir=project_dir,
        repository=args.repository,
        token=args.token,
        verbose=args.verbose,
    )

    print()
    print(
        "✓ Package published successfully."
    )

    return 0


def command_new(args: argparse.Namespace) -> int:
    output_root = args.output.resolve()
    project_name = args.name.strip()

    if not project_name:
        raise CLIError(
            "Project name cannot be empty."
        )

    package_name = _normalize_package_name(
        project_name
    )

    project_dir = (
        output_root / project_name
    )

    if project_dir.exists():
        raise CLIError(
            f"Directory already exists: {project_dir}"
        )

    project_dir.mkdir(
        parents=True
    )

    package_dir = (
        project_dir / package_name
    )

    package_dir.mkdir()

    _write_text(
        project_dir / "README.md",
        f"""# {project_name}

Python bindings for a native C library generated with c2pip.

## Development

Build the package with:

    c2pip build

## Installation

    pip install .
""",
    )

    _write_text(
        project_dir / "c2pip.spec",
        f"""[project]
name = {project_name}
version = 0.1.0
author = {args.author}
""",
    )

    _write_text(
        package_dir / "__init__.py",
        """from . import _core

__all__ = [
    "_core",
]

__version__ = "0.1.0"
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

    _write_text(
        project_dir / "example.c",
        """#include "example.h"

int add(int a, int b)
{
    return a + b;
}
""",
    )

    _write_text(
        project_dir / "example.h",
        """#ifndef EXAMPLE_H
#define EXAMPLE_H

int add(int a, int b);

#endif
""",
    )

    print(
        f"✓ Created new project: {project_dir}"
    )

    print()
    print("Next steps:")
    print(f"  cd {project_dir}")
    print(
        "  c2pip init example.h "
        f"--name {project_name} "
        f'--author "{args.author}"'
    )
    print("  c2pip build")

    return 0


def command_clean(args: argparse.Namespace) -> int:
    project_dir = Path.cwd()

    removed = _clean_build_artifacts(
        project_dir
    )

    if removed:
        print(
            "✓ Cleaned build artifacts."
        )
    else:
        print(
            "Nothing to clean."
        )

    return 0


def _clean_build_artifacts(
    project_dir: Path,
) -> bool:
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
        else:
            path.unlink()
            removed = True

    for path in project_dir.glob(
        "*.egg-info"
    ):
        if path.is_dir():
            shutil.rmtree(path)
            removed = True

    return removed


def _normalize_package_name(
    name: str,
) -> str:
    package_name = re.sub(
        r"[-.]+",
        "_",
        name.strip(),
    ).lower()

    package_name = re.sub(
        r"[^a-zA-Z0-9_]",
        "_",
        package_name,
    )

    if not package_name:
        raise CLIError(
            "Package name cannot be empty."
        )

    if package_name[0].isdigit():
        package_name = "_" + package_name

    return package_name


def _write_text(
    path: Path,
    content: str,
) -> None:
    path.parent.mkdir(
        parents=True,
        exist_ok=True,
    )

    path.write_text(
        content.rstrip() + "\n",
        encoding="utf-8",
    )


def main(
    argv: Sequence[str] | None = None,
) -> int:
    parser = build_parser()

    try:
        args = parser.parse_args(argv)

        if not hasattr(args, "func"):
            parser.error(
                "a command is required"
            )

        return args.func(args)

    except (
        CLIError,
        ScanError,
        BuildError,
        GenerationError,
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
    raise SystemExit(
        main()
    )
