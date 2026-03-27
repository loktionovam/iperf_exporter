#!/usr/bin/env python

import os
from setuptools import setup, find_packages

libpath = os.path.dirname(os.path.realpath(__file__))
requirements = f"{libpath}/requirements.txt"
install_requires = []
if os.path.isfile(requirements):
    with open(requirements) as f:
        install_requires = f.read().splitlines()


def normalize_version(raw_version: str) -> str:
    version = raw_version.strip().lstrip("v")
    if version in ("", "dev"):
        return "0.0.0.dev0"

    parts = version.split("-")
    if len(parts) >= 3 and parts[1].isdigit():
        local = ".".join(parts[2:])
        return f"{parts[0]}.post{parts[1]}+{local}"

    return version.replace("-", ".")

setup(
  name="iperf_exporter",
  packages=find_packages(
      include=["iperf_exporter", "iperf_exporter.*"],
      exclude=[
          "iperf_exporter.operator",
          "iperf_exporter.operator.*",
          "iperf_operator",
          "iperf_operator.*",
      ],
  ),
  version=normalize_version(os.environ.get("VERSION", "0.0.0.dev0")),
  license="GPLv3+",
  description="iperf metrics exporter",
  long_description=open('README.md', 'r').read(),
  author="Aleksandr Loktionov",
  author_email="loktionovam@gmail.com",
  url="https://github.com/loktionovam/iperf_exporter",
  keywords=['docker', 'prometheus', 'exporter', 'iperf'],
  classifiers=[],
  python_requires=' >= 3.10',
  install_requires=install_requires,
  entry_points={
    'console_scripts': [
      'iperf_exporter=iperf_exporter.cli:main'
    ]
  }
)
