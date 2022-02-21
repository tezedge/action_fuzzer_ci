#!/bin/sh

docker run -d --net host -v $(pwd)/_data:/data -v /var/lib/fuzzing-data/reports/:/coverage -ti action_fuzzer
