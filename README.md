# invest-compute
APIs and backend for running invest in the cloud

## pygeoapi server

To launch the server:
```
export PYGEOAPI_CONFIG=pygeoapi-config.yml
export PYGEOAPI_OPENAPI=example-openapi.yml
pygeoapi openapi generate $PYGEOAPI_CONFIG --output-file $PYGEOAPI_OPENAPI
pygeoapi serve
```

Access the OpenAPI Swagger page in your browser at http://localhost:5000/openapi
