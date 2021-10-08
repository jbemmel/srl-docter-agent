# srl-docter-agent: Tailored telemetry for every network node

Networks form complex, distributed systems whose primary function of providing connectivity and data transport services is constantly challenged by real-world events that disrupt the normal flow of operations. As engineers who are assigned to monitor and troubleshoot networks know well, figuring out what the hell happened, or what causes packet drops every so often, can be a daunting task.

With the SRL Docter agent, engineers can put specific nodes under intensive care, monitoring for specific correlated events that expose patterns of causality not seen through ordinary approaches.

# Example 1: Suspected BGP flaps due to MAC table exhaustion

Assume a scenario where a customer complains about their BGP session flapping, and engineering suspects it may be due to
MAC table exhausture in the service (as the customer seems to be doing something funky with virtual MACs and VRRP).
We can instantiate a monitoring probe for BGP session status change events, reporting on the MAC table status and global system resources at that moment:

```
"docter-agent:docter-agent": {
   "intensive-care": {
      "observe": [
        {
          "name": "bgp-flaps-due-to-mac-table-overflow",
          "conditions": [
            {
              "gnmi-path": "/network-instance[name=default]/protocols/bgp/neighbor[peer-address=1.1.0.1]/session-state"
            }
          ],
          "report": [
            "/network-instance[name=lag3]/bridge-table/statistics/total-entries",
            "/platform/linecard[slot=1]/forwarding-complex[name=0]/datapath/xdp/resource[name=mac-addresses]/used-entries"
          ]
        }
      ]
    }
  }
```

# Example 2: Sporadic conjunction of events

Investigating a possible correlation between the number of routes announced by a customer and high CPU utilization, we configure
the agent to report on high CPU utilization beyond a threshold, but only when preceeded by a certain increase in route count:

```
event: sample( /platform/control[card=A]/cpu/all/total/average-1, 3 ) > 80
when:
- /network-instance[name=overlay]/route-table/ipv4-unicast/statistics/total-routes > 10
- /platform/linecard[slot=1]/forwarding-complex[name=0]/datapath/asic/resource/overlay-ecmp-members/used-percent > 80
report:
- /network-instance[name=overlay]/route-table/ipv4-unicast/statistics/total-routes
- /platform/linecard[slot=1]/forwarding-complex[name=0]/datapath/asic/resource/overlay-ecmp-members/used-percent
```

# Example 3: Investigating number of customers affected by reboot related issues

```
event: /platform/control[slot=A]/process[pid=1]/cpu-utilization > 50
when: /system/information/current-datetime - /platform/chassis/last-booted < 10 minutes
report:
- /network-instance[name=default]/protocols/bgp/neighbor[peer-ipaddress=*]/session-state
```

## Other use cases
* Figure out when MACs are learnt from remote VTEPs in a mac-vrf: 
  path /network-instance[name=some-mac-vrf]/bridge-table/mac-table/mac/destination
  filter 'vxlan' in _
* ASIC resources: /platform/linecard[slot=1]/forwarding-complex[name=0]/datapath/asic/resource[name=*]/used-entries

# SRL Docter Agent: A scalable decentralized approach
Ordinary link flap or BGP session down events are a solved problem: They can easily be monitored today.
But when it comes to one-off out-of-the-ordinary elusive behavior, correlation of system state and events over time,
a local agent with programmable monitoring logic can provide the timely data points you need to draw the right conclusions

# Lab installation
Prerequisites:
* A Linux machine with 4 vCPUs and 16GB of RAM (or more)
* Docker
* Containerlab

To deploy this prototype agent in a demo setup complete with Grafana, Telegraf, gNMIc, Prometheus, InfluxDb:
```
git clone --recurse-submodules https://github.com/jbemmel/srl-docter-agent.git
cd srl-docter-agent
git submodule foreach -q --recursive 'git pull origin main'
make -C ./Docker all
sudo containerlab deploy -t ./srl-leafspine.lab
```
