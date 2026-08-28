from __future__ import annotations

import importlib.util
import os
import shutil
import subprocess
import sys
from pathlib import Path
from typing import Sequence


class BuildError(Exception):
    """Raised when a c2pip project cannot be built."""


class ProjectBuilder:
    """Build a c2pip project into a Python wheel."""

    BUILD_MODULE = "build"

    def __init__(
        self,
        project_dir: str | Path = ".",
        *,
        clean: bool = False,
        verbose: bool = False,
    ) -> None:
        self.project_dir = Path(project_dir).resolve()
        self.clean = clean
        self.verbose = verbose

    def build(self) -> list[Path]:
        """Build the project and return generated wheel paths."""

        self._validate_project()

        if self.clean:
            self._clean_previous_build()

        self._ensure_build_available()

        before = self._existing_wheels()

        command = [
            sys.executable,
            "-m",
            self.BUILD_MODULE,
            "--wheel",
            "--outdir",
            str(self.project_dir / "dist"),
        ]

        self._run(
            command,
            description="Building wheel",
        )

        after = self._existing_wheels()

        wheels = sorted(after - before)

        if not wheels:
            wheels = sorted(self._existing_wheels())

        if not wheels:
            raise BuildError(
                "Build completed without producing a wheel."
            )

        self._validate_wheels(wheels)
        self._print_success(wheels)

        return wheels

    def _validate_project(self) -> None:
        """Validate the minimum files required for a build."""

        if not self.project_dir.exists():
            raise BuildError(
                f"Project directory does not exist: "
                f"{self.project_dir}"
            )

        if not self.project_dir.is_dir():
            raise BuildError(
                f"Project path is not a directory: "
                f"{self.project_dir}"
            )

        pyproject = self.project_dir / "pyproject.toml"

        if not pyproject.is_file():
            raise BuildError(
                "pyproject.toml is missing. "
                "Run 'c2pip init' first."
            )

        readme = self.project_dir / "README.md"

        if not readme.is_file():
            raise BuildError(
                "README.md is missing. "
                "The project metadata requires README.md."
            )

        if not readme.read_text(
            encoding="utf-8",
            errors="replace",
        ).strip():
            raise BuildError(
                "README.md exists but is empty."
            )

        wrapper = self.project_dir / "_wrapper.c"

        if not wrapper.is_file():
            raise BuildError(
                "_wrapper.c is missing. "
                "Run 'c2pip init' again."
            )

    def _ensure_build_available(self) -> None:
        """Install the PEP 517 build frontend if necessary."""

        if importlib.util.find_spec(
            self.BUILD_MODULE
        ) is not None:
            return

        self._print(
            "Build frontend not found; installing 'build'..."
        )

        command = [
            sys.executable,
            "-m",
            "pip",
            "install",
            "--upgrade",
            "build",
        ]

        self._run(
            command,
            description="Installing build",
        )

    def _run(
        self,
        command: Sequence[str],
        *,
        description: str,
    ) -> None:
        """Run a subprocess and convert failures into BuildError."""

        self._print(f"→ {description}...")

        if self.verbose:
            self._print(
                "$ "
                + " ".join(
                    self._quote_argument(argument)
                    for argument in command
                )
            )

        environment = os.environ.copy()
        environment["PYTHONUNBUFFERED"] = "1"

        try:
            process = subprocess.run(
                list(command),
                cwd=self.project_dir,
                env=environment,
                text=True,
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                check=False,
            )
        except OSError as exc:
            raise BuildError(
                f"Unable to execute build command: {exc}"
            ) from exc

        output = process.stdout or ""

        if output:
            self._print(output.rstrip())

        if process.returncode != 0:
            raise BuildError(
                self._format_build_failure(
                    command,
                    process.returncode,
                    output,
                )
            )

    def _existing_wheels(self) -> set[Path]:
        """Return all wheel files currently present in dist/."""

        dist = self.project_dir / "dist"

        if not dist.exists():
            return set()

        return {
            path.resolve()
            for path in dist.glob("*.whl")
            if path.is_file()
        }

    @staticmethod
    def _validate_wheels(
        wheels: Sequence[Path],
    ) -> None:
        """Validate generated wheel artifacts."""

        for wheel in wheels:
            if wheel.stat().st_size == 0:
                raise BuildError(
                    f"Generated wheel is empty: {wheel.name}"
                )

            if not wheel.name.endswith(".whl"):
                raise BuildError(
                    f"Invalid wheel artifact: {wheel.name}"
                )

    def _clean_previous_build(self) -> None:
        """Remove previous build artifacts."""

        for target in ("build", "dist"):
            path = self.project_dir / target

            if not path.exists():
                continue

            self._print(
                f"Removing {path.name}/..."
            )

            if path.is_dir():
                shutil.rmtree(path)
            else:
                path.unlink()

        for path in self.project_dir.glob("*.egg-info"):
            if path.is_dir():
                self._print(
                    f"Removing {path.name}..."
                )
                shutil.rmtree(path)

    @staticmethod
    def _format_build_failure(
        command: Sequence[str],
        return_code: int,
        output: str,
    ) -> str:
        """Create a useful diagnostic message for build failures."""

        lines = [
            "Wheel build failed.",
            f"Exit code: {return_code}.",
        ]

        lowered = output.lower()

        if (
            "readme" in lowered
            and (
                "missing" in lowered
                or "not found" in lowered
            )
        ):
            lines.append(
                "Hint: make sure README.md exists and matches "
                "the 'readme' field in pyproject.toml."
            )

        if (
            "license" in lowered
            and (
                "invalid" in lowered
                or "configuration" in lowered
            )
        ):
            lines.append(
                "Hint: use PEP 621 license metadata such as "
                'license = {text = "MIT"}.'
            )

        if "python.h" in lowered:
            lines.append(
                "Hint: Python development headers are required "
                "to compile the CPython extension."
            )

        if any(
            compiler in lowered
            for compiler in (
                "gcc",
                "clang",
                "cl.exe",
            )
        ):
            lines.append(
                "Hint: a working C compiler is required."
            )

        if "setuptools" in lowered:
            lines.append(
                "Hint: verify the setuptools configuration "
                "and ext-module source paths."
            )

        if output.strip():
            lines.append(
                "\nBuild output:\n"
                + output.strip()
            )

        return "\n".join(lines)

    @staticmethod
    def _quote_argument(
        argument: str,
    ) -> str:
        """Quote command-line arguments for display."""

        if not argument:
            return '""'

        if any(
            character.isspace()
            for character in argument
        ):
            return f'"{argument}"'

        return argument

    @staticmethod
    def _print(message: str) -> None:
        """Print immediately so CLI output appears in real time."""

        print(
            message,
            flush=True,
        )

    def _print_success(
        self,
        wheels: Sequence[Path],
    ) -> None:
        """Print successful build information."""

        self._print("")
        self._print("✓ Build successful.")

        for wheel in wheels:
            self._print(
                f"  → {wheel}"
            )


def build_project(
    project_dir: str | Path = ".",
    *,
    clean: bool = False,
    verbose: bool = False,
) -> list[Path]:
    """Convenience API used by c2pip.cli."""

    builder = ProjectBuilder(
        project_dir,
        clean=clean,
        verbose=verbose,
    )

    return builder.build()


__all__ = [
    "BuildError",
    "ProjectBuilder",
    "build_project",
          ]
