# srl-docter-agent: Tailored telemetry for every network node

Networks form complex, distributed systems whose primary function of providing connectivity and data transport services is constantly challenged by real-world events that disrupt the normal flow of operations. As engineers who are assigned to monitor and troubleshoot networks know well, figuring out what the hell happened, or what causes packet drops every so often, can be a daunting task.

With the SRL Docter agent, engineers can put specific nodes under intensive care, monitoring for specific correlated events that expose patterns of causality not seen through ordinary approaches.

# Example 1: Suspected BGP flaps due to MAC table exhaustion

Assume a scenario where a customer complains about their BGP session flapping, and engineering suspects it may be due to
MAC table exhausture in the service (as the customer seems to be doing something funky with virtual MACs and VRRP).
We can place a monitoring probe for BGP down events, reporting on the MAC table status at that moment:

```
event: /network-instance[name=default]/protocols/bgp/neighbor[peer-ipaddress=1.1.0.1]/session-state != "established"
report:
- /network-instance[name=lag2]/bridge-table/statistics/total-entries
- /platform/linecard[slot=1]/forwarding-complex[name=0]/datapath/xdp/resource/mac-addresses/used-percent
```

# Example 2: Sporadic conjunction of events

Investigating a correlation between the number of routes announced by a customer and high CPU utilization, we configure
the agent to report on high CPU utilization beyond a threshold, but only when preceeded by a certain increase in route count:

```
event: sample( /platform/control[card=A]/cpu/all/total/average-1, 3 ) > 80
when:
- /network-instance[name=overlay]/route-table/ipv4-unicast/statistics/total-routes > 10
- /platform/linecard[slot=1]/forwarding-complex[name=0]/datapath/asic/resource/overlay-ecmp-members/used-percent
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

# SRL Docter Agent: A scalable approach
Ordinary link flap or BGP session down events are a solved problem: They can easily be monitored today.
But when it comes to out-of-the-ordinary elusive behavior, correlation of system state and events over time,
a local agent with programmable processing logic could save the day
