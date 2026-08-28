# setup.py
from setuptools import setup, find_packages

setup(
    name="c2pip",
    version="0.1.0",
    packages=find_packages(),
    include_package_data=True,
    install_requires=[
        "setuptools>=68.0.0",
        "wheel>=0.40.0",
        "build>=1.0.0",
        "twine>=4.0.0"
    ],
    entry_points={
        "console_scripts": [
            "c2pip=c2pip.cli:main",
        ],
    },
    author="Dan Studios",
    description="Buildozer-grade automation tool for compiling and publishing native C extensions to PyPI.",
    long_description=open("README.md", encoding="utf-8").read(),
    long_description_content_type="text/markdown",
    classifiers=[
        "Programming Language :: Python :: 3",
        "License :: OSI Approved :: MIT License",
        "Operating System :: OS Independent",
    ],
    python_requires=">=3.8",
)
