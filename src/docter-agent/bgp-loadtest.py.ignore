#!/usr/bin/env python
# coding=utf-8

import eventlet

# BGPSpeaker needs sockets patched -> breaks SRL registration if done too late
# eventlet.monkey_patch( socket=True, select=True ) # adding only ( socket=True ) allows SRL, but then BGP doesn't work :(
eventlet.monkey_patch() # need thread too

import netns
import signal

from ryu.services.protocols.bgp.bgpspeaker import (BGPSpeaker,
                                                  EVPN_MULTICAST_ETAG_ROUTE,
                                                  EVPN_MAC_IP_ADV_ROUTE,
                                                  RF_L2_EVPN,
                                                  PMSI_TYPE_INGRESS_REP)


LOCAL_LOOPBACK = "1.1.1.1" # system0.0 IP
ROUTER_ID = "99.99.99.99"  # Test
AS=65000
EVI=10000
VNI=10000

def peer_up_handler(router_id, remote_as):
    print( f'Peer UP: {router_id} {remote_as}' )

def peer_down_handler(router_id, remote_as):
    print( f'Peer DOWN: {router_id} {remote_as}' )


def announceEVPNMulticastRoute( bgpSpeaker, rd: str, vni: int, static_vtep: str ):
    #
    # For RD use the static VTEP's IP, just like it would do if it was
    # EVPN enabled itself. That way, any proxy will announce the same
    # route
    #
    bgpSpeaker.evpn_prefix_add(
        route_type=EVPN_MULTICAST_ETAG_ROUTE,
        route_dist=rd,
        # esi=0, # should be ignored
        ethernet_tag_id=0,
        # mac_addr='00:11:22:33:44:55', # not relevant for MC route
        ip_addr=static_vtep, # originator == VTEP IP
        tunnel_type='vxlan',
        vni=vni, # Not sent in advertisement
        gw_ip_addr=static_vtep,
        next_hop=static_vtep, # on behalf of remote VTEP
        pmsi_tunnel_type=PMSI_TYPE_INGRESS_REP,
        # Added via patch
        tunnel_endpoint_ip=static_vtep
    )

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
                          router_id=ROUTER_ID,
                          peer_up_handler=peer_up_handler,
                          peer_down_handler=peer_down_handler)

     rd = f"{LOCAL_LOOPBACK}:{EVI}"
     rt = f"{AS}:{EVI}"
     speaker.vrf_add(route_dist=rd,import_rts=[rt],export_rts=[rt],route_family=RF_L2_EVPN)
     announceEVPNMulticastRoute(speaker,rd,VNI,LOCAL_LOOPBACK)

     print( f"Connecting to neighbor {LOCAL_LOOPBACK}..." )

     # TODO enable_four_octet_as_number=True, enable_enhanced_refresh=True
     speaker.neighbor_add( LOCAL_LOOPBACK,
                           remote_as=AS,
                           local_as=AS,
                           enable_ipv4=False, enable_evpn=True,
                           connect_mode='active')

     eventlet.sleep(10)

   # exit netns

   # Advertise/withdraw same route 1000 times?
   print( "Start announcing 1000 EVPN routes..." )
   for i in range(0,1):
       MAC = f"00:11:22:33:{(i//256)%256:02x}:{i%256:02x}"
       IP = None # f"1.2.{(i//255)%255}.{i%255}"
       announceEVPNRoute(speaker, rd, VNI, MAC, LOCAL_LOOPBACK, IP )
       withdrawEVPNRoute(speaker, rd, MAC, IP )

   print( f"Disconnecting from neighbor {LOCAL_LOOPBACK}..." )
   speaker.neighbor_del( LOCAL_LOOPBACK )
   speaker.shutdown()
   print( "Done" )
