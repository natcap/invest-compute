FROM mambaorg/micromamba:latest

ARG SETUPTOOLS_SCM_PRETEND_VERSION_FOR_INVEST-PROCESSES=1.0.14

# Copy over the source code
COPY --chown=$MAMBA_USER:$MAMBA_USER . /app/invest_processes
WORKDIR /app/invest_processes

ENV PYGEOAPI_CONFIG=pygeoapi-config.yml
ENV PYGEOAPI_OPENAPI=openapi.yml

# Install system dependencies and gcloud
USER root
RUN apt-get update && apt-get install -y openssh-server ca-certificates gnupg curl && \
    echo "deb [signed-by=/usr/share/keyrings/cloud.google.gpg] https://packages.cloud.google.com/apt cloud-sdk main" | \
    tee -a /etc/apt/sources.list.d/google-cloud-sdk.list && \
    curl https://packages.cloud.google.com/apt/doc/apt-key.gpg | \
    gpg --batch --no-tty --dearmor -o /usr/share/keyrings/cloud.google.gpg && \
    apt-get update -y && \
    apt-get install google-cloud-cli -y && \
    gcloud --help && micromamba create -y -n env python=3.12 gdal natcap.invest==3.17.2 && \
    micromamba run -n env pip install pygeoapi rasterio==1.5 && \
    micromamba run -n env pygeoapi --version && \
    micromamba run -n env pip install . && \
    micromamba run -n env pygeoapi openapi generate $PYGEOAPI_CONFIG --output-file $PYGEOAPI_OPENAPI

# Cloud Run services must listen on the port specified by the PORT environment variable
# The default is 8080, but can be configured in the service settings
ENV PORT=5000
EXPOSE 5000

# launch the pygeoapi server, running in the mamba environment
CMD ["micromamba", "run", "-n", "env", "pygeoapi", "serve"]
