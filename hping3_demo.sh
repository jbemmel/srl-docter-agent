#!/bin/bash

docker exec -it clab-srl-docter-lab-client1 apk add hping3 --update-cache --repository http://dl-cdn.alpinelinux.org/alpine/edge/testing

# Ping SRL from client1, 10 pps
docker exec -it clab-srl-docter-lab-client1 hping3 10.10.10.1 --icmp -c 100 --fast
