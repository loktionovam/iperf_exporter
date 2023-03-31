#!/usr/bin/env python

import os
from setuptools import setup, find_packages

libpath = os.path.dirname(os.path.realpath(__file__))
requirements = f"{libpath}/requirements.txt"
install_requires = []
if os.path.isfile(requirements):
    with open(requirements) as f:
        install_requires = f.read().splitlines()

setup(
  name="iperf_exporter",
  packages=find_packages(),
  version=os.environ.get("VERSION", "dev"),
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
