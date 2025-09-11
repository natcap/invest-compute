# invest-compute
APIs and backend for running invest in the cloud

## pygeoapi server

To launch the server:
```
export PYGEOAPI_CONFIG=pygeoapi-config.yml
export PYGEOAPI_OPENAPI=openapi.yml
pygeoapi openapi generate $PYGEOAPI_CONFIG --output-file $PYGEOAPI_OPENAPI
pygeoapi serve
```

Access the OpenAPI Swagger page in your browser at http://localhost:5000/openapi

### asynchronous requests
invest model execution should run asynchronously because it can take a long time. To use asynchronous mode, include the `'Prefer: respond-async'` header in the request, as required by `pygeoapi` and the OGC Processes specification ([source](https://docs.pygeoapi.io/en/latest/data-publishing/ogcapi-processes.html#asynchronous-support)).

it seems that the async execution request is supposed to return a JSON object containing info about the job including its ID, which you can then use to query the job status and results. however the request actually returns null, and the only job info is available in the `location` response header. I asked about this here: https://github.com/geopython/pygeoapi/issues/2105

for now, given a `location` header value like `http://localhost:5000/jobs/XXXXXX`, you can check its status at that url, and retrieve results at `http://localhost:5000/jobs/XXXXXX/results`.
