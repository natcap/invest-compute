#!/bin/bash

scl enable gcc-toolset-12 bash

# install micromamba
curl -Ls https://micro.mamba.pm/api/micromamba/linux-64/latest | tar -xvj ~/bin/micromamba
eval "$(~/bin/micromamba shell hook -s posix)"
micromamba --version

# create and activate the environment
micromamba create -y -n invest_env python=3.13 gdal
micromamba activate invest_env
pip install setuptools setuptools_scm build cython babel
pip install --no-build-isolation git+https://github.com/natcap/pygeoprocessing.git
pip install --no-build-isolation git+https://github.com/emlys/invest.git@bugfix/2572
invest --version

# activate the environment in future shells
echo 'echo "activating micromamba env"' >> /etc/bashrc
echo 'eval "$(~/bin/micromamba shell hook -s posix)" && micromamba activate invest_env' >> ~/.bashrc
