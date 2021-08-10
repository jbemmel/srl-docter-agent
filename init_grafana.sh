#!/bin/bash

GRAFANA="172.20.20.10"

docker container exec clab-srl-docter-lab-grafana grafana-cli plugins install flant-statusmap-panel
docker container exec clab-srl-docter-lab-grafana grafana-cli plugins install agenty-flowcharting-panel
docker restart clab-srl-docter-lab-grafana

sleep 3

for f in grafana_dashboard_all.json ; do
curl -u 'admin:ZkaLIRBb0EOfn9wxBN2P' "http://${GRAFANA}:3000/api/dashboards/import" -X POST -H 'Content-Type: application/json;charset=UTF-8' -d "@./dashboards/${f}"
done

exit 0

