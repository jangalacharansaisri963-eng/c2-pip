# c2pip/generator.py

from __future__ import annotations

import keyword
import re
import textwrap
from pathlib import Path
from typing import Any, Iterable


class GenerationError(Exception):
    """Raised when a c2pip project cannot be generated safely."""


class ProjectGenerator:
    """
    Generate a complete Python package containing a CPython C extension.

    The generator consumes function dictionaries produced by scanner.py.

    Example function:

        {
            "return_type": "int",
            "name": "add",
            "args": [
                {
                    "type": "int",
                    "name": "a",
                    "is_pointer": False,
                },
                {
                    "type": "int",
                    "name": "b",
                    "is_pointer": False,
                },
            ],
        }

    Generated project:

        project/
        ├── pyproject.toml
        ├── README.md
        ├── c2pip.spec
        ├── _wrapper.c
        ├── <package>/
        │   └── __init__.py
        └── <source file>

    The C extension is named `_core`.
    """

    VERSION = "0.1.0"

    INTEGER_TYPES = {
        "signed char": {
            "format": "b",
            "ctype": "signed char",
            "parser": "&",
            "return": "PyLong_FromLong",
            "cast": "long",
        },
        "unsigned char": {
            "format": "B",
            "ctype": "unsigned char",
            "parser": "&",
            "return": "PyLong_FromUnsignedLong",
            "cast": "unsigned long",
        },
        "short": {
            "format": "h",
            "ctype": "short",
            "parser": "&",
            "return": "PyLong_FromLong",
            "cast": "long",
        },
        "unsigned short": {
            "format": "H",
            "ctype": "unsigned short",
            "parser": "&",
            "return": "PyLong_FromUnsignedLong",
            "cast": "unsigned long",
        },
        "int": {
            "format": "i",
            "ctype": "int",
            "parser": "&",
            "return": "PyLong_FromLong",
            "cast": "long",
        },
        "unsigned int": {
            "format": "I",
            "ctype": "unsigned int",
            "parser": "&",
            "return": "PyLong_FromUnsignedLong",
            "cast": "unsigned long",
        },
        "long": {
            "format": "l",
            "ctype": "long",
            "parser": "&",
            "return": "PyLong_FromLong",
            "cast": "long",
        },
        "unsigned long": {
            "format": "k",
            "ctype": "unsigned long",
            "parser": "&",
            "return": "PyLong_FromUnsignedLong",
            "cast": "unsigned long",
        },
        "long long": {
            "format": "L",
            "ctype": "long long",
            "parser": "&",
            "return": "PyLong_FromLongLong",
            "cast": "long long",
        },
        "unsigned long long": {
            "format": "K",
            "ctype": "unsigned long long",
            "parser": "&",
            "return": "PyLong_FromUnsignedLongLong",
            "cast": "unsigned long long",
        },
        "_Bool": {
            "format": "p",
            "ctype": "_Bool",
            "parser": "&",
            "return": "PyBool_FromLong",
            "cast": "int",
        },
        "bool": {
            "format": "p",
            "ctype": "bool",
            "parser": "&",
            "return": "PyBool_FromLong",
            "cast": "int",
        },
    }

    FLOAT_TYPES = {
        "float": {
            "format": "f",
            "ctype": "float",
        },
        "double": {
            "format": "d",
            "ctype": "double",
        },
    }

    STRING_TYPES = {
        "char *",
        "const char *",
    }

    VOID_TYPES = {
        "void",
    }

    PYTHON_KEYWORDS = set(
        keyword.kwlist
    )

    def __init__(
        self,
        name: str,
        author: str,
        functions: list[dict[str, Any]],
        source_file: str,
        output_dir: str | Path = ".",
        *,
        version: str = VERSION,
        description: str | None = None,
        license_name: str = "MIT",
        homepage: str | None = None,
        repository: str | None = None,
    ) -> None:
        self.name = self._validate_name(name)
        self.author = self._validate_author(author)
        self.functions = self._validate_functions(functions)

        self.source_file = self._validate_source_file(
            source_file
        )

        self.output_dir = Path(
            output_dir
        ).resolve()

        self.version = self._validate_version(
            version
        )

        self.description = (
            description
            or f"Python bindings for {self.name}"
        )

        self.license_name = license_name

        self.homepage = (
            homepage
            or f"https://pypi.org/project/{self.name}/"
        )

        self.repository = repository

        self.package_name = (
            self._normalize_package_name(
                self.name
            )
        )

    # ==================================================================
    # Public API
    # ==================================================================

    def generate(self) -> Path:
        """
        Generate the complete project.

        Existing generated files are overwritten deliberately.
        User C source files are never overwritten.
        """

        self.output_dir.mkdir(
            parents=True,
            exist_ok=True,
        )

        package_dir = (
            self.output_dir
            / self.package_name
        )

        package_dir.mkdir(
            parents=True,
            exist_ok=True,
        )

        self._write(
            self.output_dir / "pyproject.toml",
            self._generate_pyproject(),
        )

        self._write(
            self.output_dir / "README.md",
            self._generate_readme(),
        )

        self._write(
            package_dir / "__init__.py",
            self._generate_init(),
        )

        self._write(
            self.output_dir / "c2pip.spec",
            self._generate_spec(),
        )

        self._write(
            self.output_dir / "_wrapper.c",
            self._generate_wrapper(),
        )

        return self.output_dir

    # ==================================================================
    # Validation
    # ==================================================================

    @staticmethod
    def _validate_name(name: str) -> str:
        if not isinstance(name, str):
            raise TypeError(
                "name must be a string"
            )

        name = name.strip()

        if not name:
            raise GenerationError(
                "Package name cannot be empty."
            )

        if len(name) > 214:
            raise GenerationError(
                "Package name exceeds the PyPI limit of 214 characters."
            )

        if not re.fullmatch(
            r"[A-Za-z0-9][A-Za-z0-9._-]*",
            name,
        ):
            raise GenerationError(
                "Invalid package name. Use only letters, "
                "digits, '.', '_' and '-'."
            )

        return name

    @staticmethod
    def _validate_author(author: str) -> str:
        if not isinstance(author, str):
            raise TypeError(
                "author must be a string"
            )

        author = author.strip()

        if not author:
            raise GenerationError(
                "Author cannot be empty."
            )

        return author

    @staticmethod
    def _validate_version(version: str) -> str:
        if not isinstance(version, str):
            raise TypeError(
                "version must be a string"
            )

        version = version.strip()

        if not version:
            raise GenerationError(
                "Version cannot be empty."
            )

        if not re.fullmatch(
            r"[0-9]+(?:\.[0-9]+)*(?:[-+][A-Za-z0-9.-]+)?",
            version,
        ):
            raise GenerationError(
                f"Invalid package version: {version!r}"
            )

        return version

    @staticmethod
    def _validate_source_file(
        source_file: str,
    ) -> str:
        if not isinstance(source_file, str):
            raise TypeError(
                "source_file must be a string"
            )

        source_file = source_file.strip()

        if not source_file:
            raise GenerationError(
                "source_file cannot be empty."
            )

        suffix = Path(
            source_file
        ).suffix.lower()

        if suffix not in {
            ".c",
            ".cc",
            ".cpp",
            ".cxx",
        }:
            raise GenerationError(
                "source_file must be a C/C++ implementation "
                "file (.c, .cc, .cpp, .cxx)."
            )

        return source_file

    @classmethod
    def _validate_functions(
        cls,
        functions: list[dict[str, Any]],
    ) -> list[dict[str, Any]]:
        if not isinstance(functions, list):
            raise TypeError(
                "functions must be a list"
            )

        result: list[dict[str, Any]] = []
        seen: set[str] = set()

        for index, function in enumerate(
            functions
        ):
            if not isinstance(
                function,
                dict,
            ):
                raise GenerationError(
                    f"Function {index} is not a dictionary."
                )

            for key in (
                "return_type",
                "name",
                "args",
            ):
                if key not in function:
                    raise GenerationError(
                        f"Function {index} is missing "
                        f"'{key}'."
                    )

            name = str(
                function["name"]
            ).strip()

            if not re.fullmatch(
                r"[A-Za-z_][A-Za-z0-9_]*",
                name,
            ):
                raise GenerationError(
                    f"Invalid C function name: {name!r}"
                )

            if name in seen:
                raise GenerationError(
                    f"Duplicate function: {name}"
                )

            seen.add(name)

            return_type = cls._normalize_type(
                function["return_type"]
            )

            cls._validate_return_type(
                return_type,
                name,
            )

            raw_args = function["args"]

            if not isinstance(
                raw_args,
                list,
            ):
                raise GenerationError(
                    f"{name}: args must be a list."
                )

            args: list[dict[str, Any]] = []

            for arg_index, raw_arg in enumerate(
                raw_args
            ):
                args.append(
                    cls._validate_argument(
                        name,
                        arg_index,
                        raw_arg,
                    )
                )

            result.append(
                {
                    "return_type": return_type,
                    "name": name,
                    "args": args,
                }
            )

        return result

    @classmethod
    def _validate_argument(
        cls,
        function_name: str,
        index: int,
        arg: Any,
    ) -> dict[str, Any]:
        if not isinstance(arg, dict):
            raise GenerationError(
                f"{function_name}: argument {index} "
                "must be a dictionary."
            )

        for key in (
            "type",
            "name",
            "is_pointer",
        ):
            if key not in arg:
                raise GenerationError(
                    f"{function_name}: argument {index} "
                    f"is missing '{key}'."
                )

        arg_type = cls._normalize_type(
            arg["type"]
        )

        arg_name = str(
            arg["name"]
        ).strip()

        if not re.fullmatch(
            r"[A-Za-z_][A-Za-z0-9_]*",
            arg_name,
        ):
            raise GenerationError(
                f"{function_name}: invalid argument name "
                f"{arg_name!r}."
            )

        is_pointer = bool(
            arg["is_pointer"]
        )

        if arg_type == "void":
            raise GenerationError(
                f"{function_name}: argument '{arg_name}' "
                "cannot have type void."
            )

        if is_pointer:
            if arg_type not in cls.STRING_TYPES:
                raise GenerationError(
                    f"{function_name}: pointer argument "
                    f"'{arg_name}' has unsupported type "
                    f"'{arg_type}'."
                )

        elif arg_type not in (
            set(cls.INTEGER_TYPES)
            | set(cls.FLOAT_TYPES)
            | cls.STRING_TYPES
        ):
            raise GenerationError(
                f"{function_name}: unsupported argument "
                f"type '{arg_type}'."
            )

        return {
            "type": arg_type,
            "name": arg_name,
            "is_pointer": is_pointer,
        }

    @classmethod
    def _validate_return_type(
        cls,
        return_type: str,
        function_name: str,
    ) -> None:
        supported = (
            return_type in cls.INTEGER_TYPES
            or return_type in cls.FLOAT_TYPES
            or return_type in cls.STRING_TYPES
            or return_type in cls.VOID_TYPES
        )

        if not supported:
            raise GenerationError(
                f"{function_name}: unsupported return type "
                f"'{return_type}'."
            )

    # ==================================================================
    # General helpers
    # ==================================================================

    @staticmethod
    def _normalize_type(
        type_name: Any,
    ) -> str:
        if not isinstance(
            type_name,
            str,
        ):
            raise GenerationError(
                "C type must be a string."
            )

        value = " ".join(
            type_name.strip().split()
        )

        replacements = {
            "char*": "char *",
            "const char*": "const char *",
            "signed": "signed int",
            "unsigned": "unsigned int",
            "short int": "short",
            "unsigned short int":
                "unsigned short",
            "long int": "long",
            "unsigned long int":
                "unsigned long",
            "long long int":
                "long long",
            "unsigned long long int":
                "unsigned long long",
        }

        return replacements.get(
            value,
            value,
        )

    @staticmethod
    def _normalize_package_name(
        name: str,
    ) -> str:
        package_name = re.sub(
            r"[-.]+",
            "_",
            name.strip(),
        ).lower()

        package_name = re.sub(
            r"[^A-Za-z0-9_]",
            "_",
            package_name,
        )

        if package_name[0].isdigit():
            package_name = (
                "_" + package_name
            )

        if keyword.iskeyword(
            package_name
        ):
            package_name += "_"

        return package_name

    def _write(
        self,
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

    # ==================================================================
    # pyproject.toml
    # ==================================================================

    def _generate_pyproject(self) -> str:
        name = self._toml_string(
            self.name
        )

        author = self._toml_string(
            self.author
        )

        description = self._toml_string(
            self.description
        )

        source = self._toml_string(
            self.source_file
        )

        package = self._toml_string(
            self.package_name
        )

        homepage = self._toml_string(
            self.homepage
        )

        repository = self._toml_string(
            self.repository
        ) if self.repository else None

        repository_line = ""

        if repository:
            repository_line = (
                f'Repository = {repository}\n'
            )

        return textwrap.dedent(
            f"""\
            [build-system]
            requires = [
                "setuptools>=69",
                "wheel",
            ]
            build-backend = "setuptools.build_meta"

            [project]
            name = {name}
            version = "{self.version}"
            description = {description}
            readme = "README.md"
            requires-python = ">=3.9"
            license = {{text = "MIT"}}

            authors = [
                {{name = {author}}},
            ]

            keywords = [
                "c",
                "c-extension",
                "python",
                "bindings",
                "native",
                "cppextension",
                "cython-alternative",
            ]

            classifiers = [
                "Development Status :: 3 - Alpha",
                "Intended Audience :: Developers",
                "License :: OSI Approved :: MIT License",
                "Programming Language :: C",
                "Programming Language :: Python :: 3",
                "Programming Language :: Python :: 3 :: Only",
                "Programming Language :: Python :: 3.9",
                "Programming Language :: Python :: 3.10",
                "Programming Language :: Python :: 3.11",
                "Programming Language :: Python :: 3.12",
                "Programming Language :: Python :: 3.13",
                "Programming Language :: Python :: 3.14",
                "Operating System :: OS Independent",
                "Topic :: Software Development :: Libraries",
                "Topic :: Software Development :: Libraries :: Python Modules",
            ]

            [project.urls]
            Homepage = {homepage}
            {repository_line}

            [tool.setuptools]
            include-package-data = true
            packages = [{package}]

            [[tool.setuptools.ext-modules]]
            name = "_core"
            sources = [
                "_wrapper.c",
                {source},
            ]
            """
        )

    @staticmethod
    def _toml_string(
        value: str,
    ) -> str:
        escaped = (
            value
            .replace("\\", "\\\\")
            .replace('"', '\\"')
        )

        return f'"{escaped}"'

    # ==================================================================
    # README
    # ==================================================================

    def _generate_readme(self) -> str:
        function_table = self._generate_function_table()

        return textwrap.dedent(
            f"""\
            # {self.name}

            {self.description}.

            This project was generated by **c2pip**.

            ## Installation

            ```bash
            pip install {self.name}
            ```

            ## Usage

            ```python
            import {self.package_name}

            # Access the generated native extension:
            from {self.package_name} import _core
            ```

            ## Native Functions

            {function_table}

            ## Building From Source

            A working C compiler and Python development environment
            are required when building the package from source.

            ```bash
            python -m pip install build
            python -m build
            ```

            ## License

            MIT License.

            ## Author

            {self.author}
            """
        )

    def _generate_function_table(
        self,
    ) -> str:
        if not self.functions:
            return "No functions were discovered."

        lines = [
            "| Function | Return type | Arguments |",
            "|---|---|---|",
        ]

        for function in self.functions:
            args = function["args"]

            arguments = ", ".join(
                f"`{arg['type']} {arg['name']}`"
                for arg in args
            )

            if not arguments:
                arguments = "None"

            lines.append(
                f"| `{function['name']}` "
                f"| `{function['return_type']}` "
                f"| {arguments} |"
            )

        return "\n".join(lines)

    # ==================================================================
    # Python package
    # ==================================================================

    def _generate_init(self) -> str:
        return textwrap.dedent(
            """\
            """
            """
            Public interface for the generated c2pip extension.
            """

            from . import _core

            __all__ = [
                "_core",
            ]

            __version__ = "0.1.0"
            """
        )

    # ==================================================================
    # c2pip.spec
    # ==================================================================

    def _generate_spec(self) -> str:
        return textwrap.dedent(
            f"""\
            # c2pip project configuration

            [project]
            name = {self.name}
            version = {self.version}
            package = {self.package_name}
            author = {self.author}

            [native]
            extension = _core
            wrapper = _wrapper.c
            source = {self.source_file}

            [build]
            backend = setuptools
            python = >=3.9

            [publish]
            repository = pypi
            """
        )

    # ==================================================================
    # C wrapper
    # ==================================================================

    def _generate_wrapper(self) -> str:
        prototypes = self._generate_prototypes()

        wrappers = self._generate_wrappers()

        methods = self._generate_method_table()

        return textwrap.dedent(
            f"""\
            /*
             * ============================================================
             * c2pip generated CPython extension
             * ============================================================
             *
             * Package: {self.name}
             * Version: {self.version}
             *
             * DO NOT EDIT THIS FILE MANUALLY.
             */

            #define PY_SSIZE_T_CLEAN

            #include <Python.h>
            #include <stddef.h>
            #include <stdint.h>
            #include <stdbool.h>

            /*
             * Native function declarations
             */
            {prototypes}

            /*
             * Python wrapper functions
             */
            {wrappers}

            /*
             * Module method table
             */
            static PyMethodDef c2pip_methods[] = {{
            {methods}
                {{NULL, NULL, 0, NULL}}
            }};

            /*
             * Module definition
             */
            static struct PyModuleDef c2pip_module = {{
                PyModuleDef_HEAD_INIT,
                "_core",
                "Native C extension generated by c2pip.",
                -1,
                c2pip_methods,
                NULL,
                NULL,
                NULL,
                NULL
            }};

            /*
             * Module initialization
             */
            PyMODINIT_FUNC
            PyInit__core(void)
            {{
                return PyModule_Create(
                    &c2pip_module
                );
            }}
            """
        )

    # ==================================================================
    # C prototypes
    # ==================================================================

    def _generate_prototypes(self) -> str:
        if not self.functions:
            return "/* No functions discovered. */"

        return "\n".join(
            self._prototype(function)
            for function in self.functions
        )

    def _prototype(
        self,
        function: dict[str, Any],
    ) -> str:
        return_type = function[
            "return_type"
        ]

        name = function["name"]

        args = function["args"]

        if args:
            declaration = ", ".join(
                self._argument_declaration(
                    arg
                )
                for arg in args
            )
        else:
            declaration = "void"

        return (
            f"extern {return_type} "
            f"{name}({declaration});"
        )

    @staticmethod
    def _argument_declaration(
        arg: dict[str, Any],
    ) -> str:
        return (
            f"{arg['type']} "
            f"{arg['name']}"
        )

    # ==================================================================
    # C wrappers
    # ==================================================================

    def _generate_wrappers(self) -> str:
        if not self.functions:
            return (
                "/* No functions discovered. */"
            )

        return "\n\n".join(
            self._generate_single_wrapper(
                function
            )
            for function in self.functions
        )

    def _generate_single_wrapper(
        self,
        function: dict[str, Any],
    ) -> str:
        name = function["name"]

        args = function["args"]

        return_type = function[
            "return_type"
        ]

        declarations = (
            self._generate_argument_declarations(
                args
            )
        )

        parser = self._generate_parser(
            args
        )

        call = self._generate_native_call(
            function
        )

        conversion = (
            self._generate_return_conversion(
                return_type
            )
        )

        return textwrap.dedent(
            f"""\
            static PyObject *
            py_{name}(
                PyObject *self,
                PyObject *args
            )
            {{
                (void)self;

            {declarations}
            {parser}
            {call}
            {conversion}
            }}
            """
        )

    def _generate_argument_declarations(
        self,
        args: list[dict[str, Any]],
    ) -> str:
        if not args:
            return ""

        lines: list[str] = []

        for arg in args:
            arg_type = arg["type"]
            arg_name = arg["name"]

            if arg_type in self.STRING_TYPES:
                # PyArg_ParseTuple's "s" format produces a
                # const char * pointer.
                lines.append(
                    f"    const char *{arg_name};"
                )
            else:
                lines.append(
                    f"    {arg_type} {arg_name};"
                )

        return "\n".join(lines)

    def _generate_parser(
        self,
        args: list[dict[str, Any]],
    ) -> str:
        if not args:
            return ""

        formats: list[str] = []
        addresses: list[str] = []

        for arg in args:
            arg_type = arg["type"]
            arg_name = arg["name"]

            if arg_type in self.INTEGER_TYPES:
                formats.append(
                    self.INTEGER_TYPES[
                        arg_type
                    ]["format"]
                )
                addresses.append(
                    f"&{arg_name}"
                )

            elif arg_type in self.FLOAT_TYPES:
                formats.append(
                    self.FLOAT_TYPES[
                        arg_type
                    ]["format"]
                )
                addresses.append(
                    f"&{arg_name}"
                )

            elif arg_type in self.STRING_TYPES:
                formats.append("s")
                addresses.append(
                    f"&{arg_name}"
                )

            else:
                raise GenerationError(
                    f"Unsupported parser type: "
                    f"{arg_type}"
                )

        format_string = "".join(
            formats
        )

        address_string = ", ".join(
            addresses
        )

        return textwrap.dedent(
            f"""\
                if (!PyArg_ParseTuple(
                        args,
                        "{format_string}",
                        {address_string}
                    )) {{
                    return NULL;
                }}
            """
        )

    def _generate_native_call(
        self,
        function: dict[str, Any],
    ) -> str:
        name = function["name"]

        args = function["args"]

        call_arguments: list[str] = []

        for arg in args:
            arg_name = arg["name"]
            arg_type = arg["type"]

            if arg_type == "char *":
                call_arguments.append(
                    f"(char *){arg_name}"
                )
            else:
                call_arguments.append(
                    arg_name
                )

        joined = ", ".join(
            call_arguments
        )

        return_type = function[
            "return_type"
        ]

        if return_type == "void":
            return (
                f"    {name}({joined});"
            )

        return textwrap.dedent(
            f"""\
                {return_type} result =
                    {name}({joined});
            """
        )

    # ==================================================================
    # Return conversion
    # ==================================================================

    def _generate_return_conversion(
        self,
        return_type: str,
    ) -> str:
        if return_type == "void":
            return "    Py_RETURN_NONE;"

        if return_type in self.INTEGER_TYPES:
            info = self.INTEGER_TYPES[
                return_type
            ]

            converter = info["return"]
            cast = info["cast"]

            if return_type in {
                "_Bool",
                "bool",
            }:
                return (
                    "    return "
                    f"{converter}((long)result);"
                )

            return (
                "    return "
                f"{converter}(({cast})result);"
            )

        if return_type in self.FLOAT_TYPES:
            return (
                "    return PyFloat_FromDouble("
                "(double)result"
                ");"
            )

        if return_type in self.STRING_TYPES:
            return textwrap.dedent(
                """\
                    if (result == NULL) {
                        Py_RETURN_NONE;
                    }

                    return PyUnicode_FromString(
                        result
                    );
                """
            )

        raise GenerationError(
            f"Unsupported return type: "
            f"{return_type}"
        )

    # ==================================================================
    # Method table
    # ==================================================================

    def _generate_method_table(
        self,
    ) -> str:
        if not self.functions:
            return ""

        lines: list[str] = []

        for function in self.functions:
            name = function["name"]

            doc = self._method_doc(
                function
            )

            lines.append(
                f'    {{"{name}", '
                f"py_{name}, "
                f"METH_VARARGS, "
                f'"{doc}"}},'
            )

        return "\n".join(
            lines
        ) + "\n"

    @staticmethod
    def _method_doc(
        function: dict[str, Any],
    ) -> str:
        args = ", ".join(
            f"{arg['type']} {arg['name']}"
            for arg in function["args"]
        )

        doc = (
            f"{function['name']}"
            f"({args})"
            f" -> "
            f"{function['return_type']}"
        )

        return (
            doc
            .replace("\\", "\\\\")
            .replace('"', '\\"')
            .replace("\n", "\\n")
        )
