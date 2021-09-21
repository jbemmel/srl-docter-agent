#!/bin/bash

docker exec -it clab-srl-docter-lab-client1 apk add iperf
docker exec -it clab-srl-docter-lab-client2 apk add iperf

# Run iperf as UDP daemon on client2
docker exec -it clab-srl-docter-lab-client2 iperf -s -u -D

# Connect from client1, 100 kbps
docker exec -it clab-srl-docter-lab-client1 iperf -c 10.10.10.12 -u --time 120 --bandwidth 100k
