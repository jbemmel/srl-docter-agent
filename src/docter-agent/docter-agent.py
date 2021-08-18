#!/usr/bin/env python
# coding=utf-8

import grpc
import datetime
import sys
import logging
import socket
import os
import re
import ipaddress
import json
import signal
import traceback
import subprocess

import sdk_service_pb2
import sdk_service_pb2_grpc
import lldp_service_pb2
import config_service_pb2
import route_service_pb2
import nexthop_group_service_pb2
import sdk_common_pb2

# To report state back
import telemetry_service_pb2
import telemetry_service_pb2_grpc

# See opt/rh/rh-python36/root/usr/lib/python3.6/site-packages/sdk_protos/bfd_service_pb2.py
import bfd_service_pb2

from pygnmi.client import gNMIclient, telemetryParser

from logging.handlers import RotatingFileHandler

############################################################
## Agent will start with this name
############################################################
agent_name='docter_agent'

############################################################
## Open a GRPC channel to connect to sdk_mgr on the dut
## sdk_mgr will be listening on 50053
############################################################
#channel = grpc.insecure_channel('unix:///opt/srlinux/var/run/sr_sdk_service_manager:50053')
channel = grpc.insecure_channel('127.0.0.1:50053')
metadata = [('agent_name', agent_name)]
stub = sdk_service_pb2_grpc.SdkMgrServiceStub(channel)

# Global gNMI channel, used by multiple threads
#gnmi_options = [('username', 'admin'), ('password', 'admin')]
#gnmi_channel = grpc.insecure_channel(
#   'unix:///opt/srlinux/var/run/sr_gnmi_server', options = gnmi_options )

############################################################
## Subscribe to required event
## This proc handles subscription of: Interface, LLDP,
##                      Route, Network Instance, Config
############################################################
def Subscribe(stream_id, option):
    op = sdk_service_pb2.NotificationRegisterRequest.AddSubscription
    if option == 'lldp':
        entry = lldp_service_pb2.LldpNeighborSubscriptionRequest()
        # TODO filter out 'mgmt0' interfaces
        request = sdk_service_pb2.NotificationRegisterRequest(op=op, stream_id=stream_id, lldp_neighbor=entry)
    elif option == 'cfg':
        entry = config_service_pb2.ConfigSubscriptionRequest()
        # entry.key.js_path = '.' + agent_name
        request = sdk_service_pb2.NotificationRegisterRequest(op=op, stream_id=stream_id, config=entry)
    elif option == 'bfd':
        entry = bfd_service_pb2.BfdSessionSubscriptionRequest()
        request = sdk_service_pb2.NotificationRegisterRequest(op=op, stream_id=stream_id, bfd_session=entry)
    elif option == 'route':
        # This includes all network namespaces, i.e. including mgmt
        entry = route_service_pb2.IpRouteSubscriptionRequest()
        request = sdk_service_pb2.NotificationRegisterRequest(op=op, stream_id=stream_id, route=entry)
    elif option == 'nexthop_group':
        entry = nexthop_group_service_pb2.NextHopGroupSubscriptionRequest()
        request = sdk_service_pb2.NotificationRegisterRequest(op=op, stream_id=stream_id, nhg=entry)

    subscription_response = stub.NotificationRegister(request=request, metadata=metadata)
    print('Status of subscription response for {}:: {}'.format(option, subscription_response.status))

############################################################
## Subscribe to all the events that Agent needs
############################################################
def Subscribe_Notifications(stream_id):
    '''
    Agent will receive notifications to what is subscribed here.
    '''
    if not stream_id:
        logging.info("Stream ID not sent.")
        return False

    # Subscribe to config changes, first
    Subscribe(stream_id, 'cfg')

    # Subscribe(stream_id, 'bfd')

    # To map route notifications to BGP peers
    # Subscribe(stream_id, 'nexthop_group')

    ##Subscribe to LLDP Neighbor Notifications -> moved
    ## Subscribe(stream_id, 'lldp')

############################################################
## Function to populate state of agent config
## using telemetry -- add/update info from state
############################################################
def Add_Telemetry(js_path, js_data):
    telemetry_stub = telemetry_service_pb2_grpc.SdkMgrTelemetryServiceStub(channel)
    telemetry_update_request = telemetry_service_pb2.TelemetryUpdateRequest()
    telemetry_info = telemetry_update_request.state.add()
    telemetry_info.key.js_path = js_path
    telemetry_info.data.json_content = js_data
    logging.info(f"Telemetry_Update_Request :: {telemetry_update_request}")
    telemetry_response = telemetry_stub.TelemetryAddOrUpdate(request=telemetry_update_request, metadata=metadata)
    return telemetry_response

############################################################
## Function to populate state fields of the agent
## It updates command: info from state auto-config-agent
############################################################
def Update_Peer_State(peer_ip, section, update_data):
    _ip_key = '.'.join([i.zfill(3) for i in peer_ip.split('.')]) # sortable
    js_path = '.' + agent_name + '.peer{.peer_ip=="' + _ip_key + '"}.'+section
    response = Add_Telemetry( js_path=js_path, js_data=json.dumps(update_data) )
    logging.info(f"Telemetry_Update_Response :: {response}")

def Update_Observation(name, trigger, updates):
    now = datetime.datetime.now().strftime("%Y-%m-%dT%H:%M:%SZ")
    update_data = {
      'last_observed' : { "value" : now },
      'trigger' : { "value" : trigger },
      'count': 1234,
      # 'report_history': [ report ] # This replaces the whole list, instead of appending
    }
    js_path = '.' + agent_name + '.intensive_care.observe{.name=="' + name + '"}.statistics'
    response = Add_Telemetry( js_path=js_path, js_data=json.dumps(update_data) )
    logging.info(f"Telemetry_Update_Response :: {response}")

    for path,value in updates:
      js_path2 = js_path + f'.report{{.timestamp=="{now}"}}.values{{.path=="{path}"}}'
      response = Add_Telemetry( js_path=js_path2, js_data=json.dumps({'value':value}) )
      logging.info(f"Telemetry_Update_Response2 :: {response}")

def Update_Global_State(state, var, val):
    js_path = '.' + agent_name + '.' + var
    response = Add_Telemetry( js_path=js_path, js_data=json.dumps(val) )
    logging.info(f"Telemetry_Update_Response :: {response}")

##################################################################
## Proc to process the config Notifications received by auto_config_agent
## At present processing config from js_path containing agent_name
##################################################################
def Handle_Notification(obj, state):
    if obj.HasField('route'):
        addr = ipaddress.ip_address(obj.route.key.ip_prefix.ip_addr.addr).__str__()
        prefix = obj.route.key.ip_prefix.prefix_length
        nhg_id = obj.route.data.nhg_id
        owner_id = obj.route.data.owner_id # To correlate Delete later on
        nh_ip = "?"
        if nhg_id in state.nhg_map:
           nh_ip = state.nhg_map[nhg_id]
        _op = ""
        if obj.route.op == "Delete":
           _op = "-"
           if owner_id in state.owner_id_map:
             nh_ip = state.owner_id_map[ owner_id ]
             delattr( state.owner_id_map, owner_id )
        elif nh_ip != "?":
           state.owner_id_map[owner_id] = nh_ip # Remember for Delete
        logging.info( f"ROUTE notification: {_op}{addr}/{prefix} nhg={nhg_id} ip={nh_ip} owner_id={owner_id}" )
        if nh_ip != "?":
           Update_RouteFlapcounts(state, nh_ip, f'{_op}{addr}/{prefix}' )

    elif obj.HasField('nhg'):
        try:
           nhg_id = obj.nhg.key
           if (obj.nhg.op == "Delete"):
             logging.info( f"NEXTHOP Delete notification: nhg={nhg_id}" )
             if nhg_id in state.nhg_map:
               peer_ip = state.nhg_map[ nhg_id ]
               Update_RouteFlapcounts(state, peer_ip, f'-nhg{nhg_id}')
               delattr( state.nhg_map, nhg_id )
           else:
             for nh in obj.nhg.data.next_hop:
              if nh.ip_nexthop.addr != b'': # type byte
               addr = ipaddress.ip_address(nh.ip_nexthop.addr).__str__()
               logging.info( f"NEXTHOP notification: {addr} nhg={nhg_id}" )
               Update_RouteFlapcounts(state, addr, f'+nhg{nhg_id}')
               state.nhg_map[nhg_id] = addr
               break
        except Exception as e: # ip_nexthop not set
           logging.error(f'Exception caught while processing nhg :: {e}')

    elif obj.HasField('config'):
        logging.info(f"GOT CONFIG :: {obj.config.key.js_path}")
        if agent_name in obj.config.key.js_path:
            logging.info(f"Got config for agent, now will handle it :: \n{obj.config}\
                            Operation :: {obj.config.op}\nData :: {obj.config.data.json}")
            if obj.config.op == 2:
                logging.info(f"Delete docter-agent cli scenario")
                # if file_name != None:
                #    Update_Result(file_name, action='delete')
                response=stub.AgentUnRegister(request=sdk_service_pb2.AgentRegistrationRequest(), metadata=metadata)
                logging.info( f'Handle_Config: Unregister response:: {response}' )
                state = State() # Reset state, works?
            else:
                json_acceptable_string = obj.config.data.json.replace("'", "\"")
                data = json.loads(json_acceptable_string)

                if 'monitor' in data:
                  _d = data['monitor']
                  if 'flaps_per_period_threshold' in _d:
                    state.flap_threshold = int( _d['flaps_per_period_threshold']['value'] )
                  if 'flaps_monitoring_period' in _d:
                    state.flap_period_mins = int( _d['flaps_monitoring_period']['value'] )
                  if 'max_flaps_history' in _d:
                    state.max_flaps_history = int( _d['max_flaps_history']['value'] )

                  # Update flap count assesments for each peer
                  logging.info( f'Updating BFD flapcounts after new hourly threshold: {state.flap_threshold}' )
                  Update_Global_State( state, "total_bfd_flaps_last_period",
                    sum( [max(len(f)-1,0) for f in state.bfd_flaps.values() ] ) )
                  for peer_ip in state.bfd_flaps.keys():
                      Update_BFDFlapcounts( state, peer_ip )

                if obj.config.key.js_path == ".docter_agent.intensive_care.observe":
                    name = obj.config.key.keys[0]
                    reports = [ i['value'] for i in data['observe']['report'] ]
                    if name in state.observations:
                       state.observations[ name ][ 'reports' ] = reports
                    else:
                       state.observations[ name ] = { 'reports' : reports }
                elif obj.config.key.js_path == ".docter_agent.intensive_care.observe.conditions":
                    name = obj.config.key.keys[0]
                    path = obj.config.key.keys[1]  # XXX only supports single path per observation for now
                    if name in state.observations:
                       state.observations[ name ][ 'path' ] = path
                    else:
                       state.observations[ name ] = { 'path' : path }

                return True # subscribe to LLDP
        elif obj.config.key.js_path == ".commit.end":
           if state.observations != {}:
              MonitoringThread( state.observations ).start()

    elif obj.HasField('lldp_neighbor'): # and not state.role is None:
        # Update the config based on LLDP info, if needed
        logging.info(f"process LLDP notification : {obj}")
        my_port = obj.lldp_neighbor.key.interface_name  # ethernet-1/x
        to_port = obj.lldp_neighbor.data.port_id
        peer_sys_name = obj.lldp_neighbor.data.system_name

        if my_port != 'mgmt0' and to_port != 'mgmt0' and hasattr(state,'peerlinks'):

          # Start listening for BFD
          link_name = f"bfd-{my_port}"
          if not hasattr(state,link_name):
             setattr( state, link_name, True )
             state_update = {
               "status" : { "value" : "Awaiting BFD from: " + obj.lldp_neighbor.data.system_description },
               "flaps_last_period" : 0,
               "flaps_history" : { "value" : "none yet" }
             }
             Update_Peer_State( peer_sys_name, 'bfd', state_update )

    elif obj.HasField('bfd_session'):
        logging.info(f"process BFD notification : {obj}")
        src_ip_addr = obj.bfd_session.key.src_ip_addr.addr
        dst_ip_addr = obj.bfd_session.key.dst_ip_addr.addr

        # Integer, 4=UP
        status = obj.bfd_session.data.status  # data.src_if_id, not always set
        src_ip_str = ipaddress.ip_address(src_ip_addr).__str__()
        dst_ip_str = ipaddress.ip_address(dst_ip_addr).__str__()
        logging.info(f"BFD : src={src_ip_str} dst={dst_ip_str} status={status}")

        Update_BFDFlapcounts( state, dst_ip_str, status )
    else:
        logging.info(f"Unexpected notification : {obj}")

    # dont subscribe to LLDP now
    return False

##
# Update agent state flapcounts for BFD
##
def Update_BFDFlapcounts(state,peer_ip,status=4):
    if peer_ip not in state.bfd_flaps:
       logging.info(f"BFD : initializing flap state for {peer_ip} status={status}")
       state.bfd_flaps[peer_ip] = {}
    now = datetime.datetime.now()
    flaps_this_period, history = Update_Flapcounts(state, now, peer_ip, status,
                                                   state.bfd_flaps,
                                                   state.flap_period_mins)
    state_update = {
      "status" : { "value" : "red" if flaps_this_period > state.flap_threshold or status!=4 else "green" },
      "flaps_last_period" : flaps_this_period,
      "flaps_history" : { "value" : history },
      "last_flap_timestamp" : { "value" : now.strftime("%Y-%m-%dT%H:%M:%SZ") }
    }
    Update_Peer_State( peer_ip, 'bfd', state_update )
    Update_Global_State( state, "total_bfd_flaps_last_period", # Works??
      sum( [ max(len(f)-1,0) for f in state.bfd_flaps.values()] ) )

##
# Update agent state flapcounts for Route entry
##
def Update_RouteFlapcounts(state,peer_ip,prefix):
    if peer_ip not in state.route_flaps:
       logging.info(f"ROUTE : initializing flap state for {peer_ip}")
       state.route_flaps[peer_ip] = {}
    now = datetime.datetime.now()
    flaps_this_period, history = Update_Flapcounts(state, now, peer_ip, prefix,
                                                   state.route_flaps,
                                                   state.flap_period_mins)
    state_update = {
      "status" : { "value" : "red" if flaps_this_period > state.flap_threshold else "green" },
      "flaps_last_period" : flaps_this_period,
      "flaps_history" : { "value" : history },
      "last_flap_timestamp" : { "value" : now.strftime("%Y-%m-%dT%H:%M:%SZ") }
    }
    Update_Peer_State( peer_ip, 'routes', state_update )
    # Update_Global_State( state )

##
# Update agent state flapcounts
##
def Update_Flapcounts(state,now,peer_ip,status,flapmap,period_mins):
    flaps = flapmap[peer_ip]
    if status != 0:
       flaps[now] = status
    keep_flaps = {}
    keep_history = ""
    start_of_period = now - datetime.timedelta(minutes=period_mins)
    _max = state.max_flaps_history
    for i in sorted(flaps.keys(), reverse=True):
       logging.info(f"BFD : check if {i} is within the last period {start_of_period}")
       if ( i > start_of_period and (_max==0 or _max>len(keep_flaps)) ):
           keep_flaps[i] = flaps[i]
           keep_history += f'{ i.strftime("[%H:%M:%S.%f]") } ~ {flaps[i]},'
       else:
           logging.info(f"flap happened outside monitoring period/max: {i}")
           break
    logging.info(f"BFD : keeping last period of flaps for {peer_ip}:{keep_flaps}")
    flapmap[peer_ip] = keep_flaps
    # Dont count single transition to 'up' as a flap
    return len( keep_flaps ) - 1, keep_history

#
# Runs as a separate thread
#
from threading import Thread
class MonitoringThread(Thread):
   def __init__(self, observations):
       Thread.__init__(self)
       self.observations = observations

       # Check that gNMI is connected now
       # grpc.channel_ready_future(gnmi_channel).result(timeout=5)

   def run(self):

      # Create per-thread gNMI stub, using a global channel
      # gnmi_stub = gNMIStub( gnmi_channel )
    try:
      logging.info( f"MonitoringThread: {self.observations}")

      subscribe = {
        'subscription': [
            {
                'path': value['path'],
                'mode': 'on_change',
            } for key,value in self.observations.items()
        ],
        'use_aliases': False,
        'mode': 'stream',
        'encoding': 'json'
      }

      # Build lookup map
      lookup = {}
      for name,atts in self.observations.items():
          lookup[ atts['path'] ] = { 'name': name, **atts }
      logging.info( f"Built lookup map: {lookup}" )

      # with Namespace('/var/run/netns/srbase-mgmt', 'net'):
      with gNMIclient(target=('unix:///opt/srlinux/var/run/sr_gnmi_server',57400),
                            username="admin",password="admin",
                            insecure=True, debug=False) as c:
        telemetry_stream = c.subscribe(subscribe=subscribe)
        for m in telemetry_stream:
          if m.HasField('update'): # both update and delete events
              # Filter out only toplevel events
              parsed = telemetryParser(m)
              logging.info(f"gNMI change event :: {parsed}")
              update = parsed['update']
              if update['update']:
                  logging.info( f"Update: {update['update']}")
                  for u in update['update']:
                      key = '/' + u['path'] # pygnmi strips '/'
                      if key in lookup:
                         o = lookup[ key ]
                         data = c.get(path=o['reports'], encoding='json_ietf')
                         logging.info( f"Reports:{data} val={u['val']}" )
                         # update Telemetry, iterate
                         updates = [ (u2['path'],u2['val'])
                                     for n in data['notification']
                                     for u2 in n['update']
                                   ]
                         Update_Observation( o['name'], u['val'], updates )

    except Exception as e:
       traceback_str = ''.join(traceback.format_tb(e.__traceback__))
       logging.error(f'Exception caught in gNMI :: {e} m={m} stack:{traceback_str}')

    logging.info("Leaving gNMI subscribe loop")

class State(object):
    def __init__(self):
        # self.role = None       # May not be set in config
        self.bfd_flaps = {}    # Indexed by peer IP
        self.nhg_map = {}      # Map of nhg_id -> peer IP
        self.owner_id_map = {} # Map of owner_id (from add route) -> peer IP
        self.route_flaps = {}  # Indexed by next hop IP
        self.flap_period_mins = 60 # Make sure this is defined
        self.flap_threshold = 0
        self.max_flaps_history = 0

        self.observations = {} # Map of [name] -> { paths: [], reports: [] }

    def __str__(self):
        return str(self.__class__) + ": " + str(self.__dict__)

##################################################################################################
## This is the main proc where all processing for docter_agent starts.
## Agent registration, notification registration, Subscrition to notifications.
## Waits on the subscribed Notifications and once any config is received, handles that config
## If there are critical errors, Unregisters the fib_agent gracefully.
##################################################################################################
def Run():
    sub_stub = sdk_service_pb2_grpc.SdkNotificationServiceStub(channel)

    # optional agent_liveliness=<seconds> to have system kill unresponsive agents
    response = stub.AgentRegister(request=sdk_service_pb2.AgentRegistrationRequest(), metadata=metadata)
    logging.info(f"Registration response : {response.status}")

    request=sdk_service_pb2.NotificationRegisterRequest(op=sdk_service_pb2.NotificationRegisterRequest.Create)
    create_subscription_response = stub.NotificationRegister(request=request, metadata=metadata)
    stream_id = create_subscription_response.stream_id
    logging.info(f"Create subscription response received. stream_id : {stream_id}")

    Subscribe_Notifications(stream_id)

    stream_request = sdk_service_pb2.NotificationStreamRequest(stream_id=stream_id)
    stream_response = sub_stub.NotificationStream(stream_request, metadata=metadata)

    state = State()
    count = 1
    lldp_subscribed = False
    try:
        for r in stream_response:
            logging.info(f"Count :: {count}  NOTIFICATION:: \n{r.notification}")
            count += 1
            for obj in r.notification:
                if Handle_Notification(obj, state) and not lldp_subscribed:
                   # Subscribe(stream_id, 'lldp')
                   # Subscribe(stream_id, 'route')
                   lldp_subscribed = True

                # Program router_id only when changed
                # if state.router_id != old_router_id:
                #   gnmic(path='/network-instance[name=default]/protocols/bgp/router-id',value=state.router_id)
                logging.info(f'Updated state: {state}')

    except grpc._channel._Rendezvous as err:
        logging.info(f'GOING TO EXIT NOW: {err}')

    except Exception as e:
        logging.error(f'Exception caught :: {e}')
        #if file_name != None:
        #    Update_Result(file_name, action='delete')
        try:
            response = stub.AgentUnRegister(request=sdk_service_pb2.AgentRegistrationRequest(), metadata=metadata)
            logging.error(f'Run try: Unregister response:: {response}')
        except grpc._channel._Rendezvous as err:
            logging.info(f'GOING TO EXIT NOW: {err}')
            sys.exit()
        return True
    sys.exit()
    return True
############################################################
## Gracefully handle SIGTERM signal
## When called, will unregister Agent and gracefully exit
############################################################
def Exit_Gracefully(signum, frame):
    logging.info("Caught signal :: {}\n will unregister docter agent".format(signum))
    try:
        response=stub.AgentUnRegister(request=sdk_service_pb2.AgentRegistrationRequest(), metadata=metadata)
        logging.error('try: Unregister response:: {}'.format(response))
        sys.exit()
    except grpc._channel._Rendezvous as err:
        logging.info('GOING TO EXIT NOW: {}'.format(err))
        sys.exit()

##################################################################################################
## Main from where the Agent starts
## Log file is written to: /var/log/srlinux/stdout/<agent_name>.log
## Signals handled for graceful exit: SIGTERM
##################################################################################################
if __name__ == '__main__':
    # hostname = socket.gethostname()
    stdout_dir = '/var/log/srlinux/stdout' # PyTEnv.SRL_STDOUT_DIR
    signal.signal(signal.SIGTERM, Exit_Gracefully)
    if not os.path.exists(stdout_dir):
        os.makedirs(stdout_dir, exist_ok=True)
    log_filename = f'{stdout_dir}/{agent_name}.log'
    logging.basicConfig(
      handlers=[RotatingFileHandler(log_filename, maxBytes=3000000,backupCount=5)],
      format='%(asctime)s,%(msecs)03d %(name)s %(levelname)s %(message)s',
      datefmt='%H:%M:%S', level=logging.INFO)
    logging.info("START TIME :: {}".format(datetime.datetime.now()))
    if Run():
        logging.info('Docter agent unregistered')
    else:
        logging.info('Should not happen')
