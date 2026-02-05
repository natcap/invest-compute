#!/bin/bash

# install micromamba
curl -Ls https://micro.mamba.pm/api/micromamba/linux-64/latest | tar -xvj bin/micromamba
eval "$(./bin/micromamba shell hook -s posix)"
micromamba --version

# create and activate the environment
micromamba create -y -n env python=3.13 gdal natcap.invest==3.17.2
micromamba activate env

# activate the environment in future shells
echo 'echo "activating micromamba env"' >> /etc/bashrc
echo 'eval "$(./bin/micromamba shell hook -s posix)" && micromamba activate env' >> /etc/bashrc
