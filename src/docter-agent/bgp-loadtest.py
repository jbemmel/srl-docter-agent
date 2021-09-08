#!/usr/bin/env python
# coding=utf-8

import eventlet

# BGPSpeaker needs sockets patched -> breaks SRL registration if done too late
# eventlet.monkey_patch( socket=True, select=True ) # adding only ( socket=True ) allows SRL, but then BGP doesn't work :(
eventlet.monkey_patch() # need thread too

import logging
import netns
import signal

from ryu.services.protocols.bgp.bgpspeaker import (BGPSpeaker,
                                                  EVPN_MULTICAST_ETAG_ROUTE,
                                                  EVPN_MAC_IP_ADV_ROUTE,
                                                  RF_L2_EVPN,
                                                  PMSI_TYPE_INGRESS_REP)


LOCAL_LOOPBACK = "1.1.1.1" # system0.0 IP
AS=65000
EVI=10000
VNI=10000

def peer_up_handler(router_id, remote_as):
    logging.warning( f'Peer UP: {router_id} {remote_as}' )

def peer_down_handler(router_id, remote_as):
    logging.warning( f'Peer DOWN: {router_id} {remote_as}' )

def announceEVPNRoute( bgpSpeaker, rd: str, vni: int, mac: str, static_vtep: str, ip=None ):
   bgpSpeaker.evpn_prefix_add(
     route_type=EVPN_MAC_IP_ADV_ROUTE, # RT2
     route_dist=rd,
     esi=0, # Single homed
     ethernet_tag_id=0,
     mac_addr=mac,
     ip_addr=ip, # SRL peers are L2 only, ignoring this IP
     next_hop=static_vtep, # on behalf of remote VTEP
     tunnel_type='vxlan',
     vni=vni,
     gw_ip_addr=static_vtep,
   )

def withdrawEVPNRoute( bgpSpeaker, rd: str, mac: str, ip=None ):
   bgpSpeaker.evpn_prefix_del(
     route_type=EVPN_MAC_IP_ADV_ROUTE, # RT2
     route_dist=rd, # original RD
     # vni=vni, # not used/allowed in withdraw
     ethernet_tag_id=0,
     mac_addr=mac,
     ip_addr=ip
   )

if __name__ == '__main__':
   with netns.NetNS(nsname="srbase-default"):
     speaker = BGPSpeaker(bgp_server_hosts=[LOCAL_LOOPBACK], bgp_server_port=1179,
                          as_number=AS,
                          router_id=LOCAL_LOOPBACK,
                          peer_up_handler=peer_up_handler,
                          peer_down_handler=peer_down_handler)

     rd = f"{LOCAL_LOOPBACK}:{EVI}"
     rt = f"{AS}:{EVI}"
     speaker.vrf_add(route_dist=rd,import_rts=[rt],export_rts=[rt],route_family=RF_L2_EVPN)

     logging.info( f"Connecting to neighbor {LOCAL_LOOPBACK}..." )

     # TODO enable_four_octet_as_number=True, enable_enhanced_refresh=True
     speaker.neighbor_add( LOCAL_LOOPBACK,
                           remote_as=AS,
                           local_as=AS,
                           enable_ipv4=False, enable_evpn=True,
                           connect_mode='active')

     eventlet.sleep(10)

   # exit netns

   # Advertise/withdraw same route 1000 times
   MAC = "00:11:22:33:44:55"
   IP = "1.2.3.4"
   for i in range(0,1000):
       announceEVPNRoute(speaker, rd, VNI, MAC, LOCAL_LOOPBACK, IP )
       withdrawEVPNRoute(speaker, rd, MAC, IP )

   logging.info( f"Disconnecting from neighbor {LOCAL_LOOPBACK}..." )
   speaker.neighbor_del( LOCAL_LOOPBACK )
   speaker.shutdown()
   logging.info( "Done" )
