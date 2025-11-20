#!/bin/bash
gcloud compute ssh "$@" --tunnel-through-iap
