#!/usr/bin/env python
# coding=utf-8

import grpc
from datetime import datetime, timezone
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
from threading import Timer

import sdk_service_pb2
import sdk_service_pb2_grpc
import config_service_pb2
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
    if option == 'cfg':
        entry = config_service_pb2.ConfigSubscriptionRequest()
        # entry.key.js_path = '.' + agent_name
        request = sdk_service_pb2.NotificationRegisterRequest(op=op, stream_id=stream_id, config=entry)

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
metrics = {}
def Update_Metric(metric, contributor, contrib_status):
    js_path = '.' + agent_name + f'.health.metric{{.name=="{metric}"}}.contribution{{.name=="{contributor}"}}'
    metric_data = {
      'status' : { 'value' : contrib_status }
    }
    response = Add_Telemetry( js_path=js_path, js_data=json.dumps(metric_data) )
    logging.info(f"Update_Metric Telemetry_Update_Response :: {response}")

    def worst(s1,s2):
        if s1=="red" or s2=="red":
            return "red"
        elif s1=="orange" or s2=="orange":
            return "orange"
        else:
            return "green"

    # Update the parent
    global metrics
    if metric in metrics:
        m = metrics[metric]
    else:
        metrics[metric] = m = {}

    m.update( { contributor : contrib_status } )
    overall = contrib_status
    cause = contributor
    for c,v in m.items():
        w = worst( overall, v )
        if w!=overall:
            overall = w
            cause = c

    logging.info( f"Updated metric {metric}: {overall} cause={cause}" )
    js_path = '.' + agent_name + f'.health.metric{{.name=="{metric}"}}'
    data = {
       'status' : { 'value' : overall },
       'cause'  : { 'value' : cause }
    }
    response = Add_Telemetry( js_path=js_path, js_data=json.dumps(data) )

def Show_Dummy_Health(controlplane="green",links="green"):

    now = datetime.now()
    now_ts = now.strftime("%Y-%m-%dT%H:%M:%SZ")
    update_data = {
      'last_updated' : { "value" : now_ts },
      'controlplane': { "value" : controlplane },
      'links': { "value": links },
    }
    js_path = '.' + agent_name + '.health'
    response = Add_Telemetry( js_path=js_path, js_data=json.dumps(update_data) )
    logging.info(f"Telemetry_Update_Response :: {response}")

    js_path += f'.metric{{.name=="CPU"}}.contribution{{.name=="spikes"}}'
    metric_data = {
      'status' : { 'value' : 'not happening right now' }
    }
    # response = Add_Telemetry( js_path=js_path, js_data=json.dumps(metric_data) )

def Grafana_Test():
    now = datetime.now()
    now_ts = now.strftime("%Y-%m-%dT%H:%M:%SZ")
    update_data = {
      'leaflist' : [ 123, 456 ],
      'timestamp' : { "value" : now_ts },
      'timestamp_int' : now.timestamp(),
      'count' : 69
      #'mylist' : [
      # { 'name' : { 'value': 'name1' }, 'value' : { 'value' : 'v1' } },
      # { 'name' : { 'value': 'name2' }, 'value' : { 'value' : 'v2' } },
      # ]
    }
    # js_path = '.' + agent_name + '.intensive_care.observe{.name=="' + name + '"}.statistics'
    js_path = '.' + agent_name + '.grafana_test'
    response = Add_Telemetry( js_path=js_path, js_data=json.dumps(update_data) )
    logging.info(f"Telemetry_Update_Response :: {response}")

    response = Add_Telemetry( js_path=js_path+'.mylist{.name=="name1"}', js_data=json.dumps({'value':'v1','count':2, 'nested' : ['n1','n2'] }) )
    response = Add_Telemetry( js_path=js_path+'.mylist{.name=="2021-08-23_18:43:54.633636"}', js_data=json.dumps({'value':'v2','count':3}) )

reports_count = 0 # Total
filter_count = 0

def Update_Filtered(o, timestamp_ns, path, val):
    global reports_count
    global filter_count
    filter_count = filter_count + 1

    now = datetime.now()
    now_ts = now.strftime("%Y-%m-%dT%H:%M:%SZ")
    update_data = {
      'last_updated' : { "value" : now_ts },
      'count': reports_count,
      'filtered': filter_count,
    }
    # js_path = '.' + agent_name + '.intensive_care.observe{.name=="' + name + '"}.statistics'
    js_path = '.' + agent_name + '.reports'
    response = Add_Telemetry( js_path=js_path, js_data=json.dumps(update_data) )
    logging.info(f"Telemetry_Update_Response :: {response}")

    # Use the first value not matching the filter to reset any threshold alarms
    if 'reset_flag' not in o:
      js_path2 = js_path + f'.history{{.name=="{o["name"]}"}}.path{{.path=="{path}"}}.event{{.t=="{timestamp_ns}"}}'
      response = Add_Telemetry( js_path=js_path2, js_data=json.dumps({'v': {'value':val}, 'filter': False }) )
      o['reset_flag'] = timestamp_ns

def Threshold_Color( val, thresholds ):
    try:
       if len(thresholds)==0:
           return "green"
       elif len(thresholds)==1:
           return "red" if val != thresholds[0] else "green"
       elif len(thresholds)==2:
           return ("red"    if int(val) < int(thresholds[0]) else
                  ("yellow" if int(val) < int(thresholds[1]) else
                   "green"))
       else: # 3 or more
           return ("red"    if int(val) < int(thresholds[0]) else
                  ("orange" if int(val) < int(thresholds[1]) else
                  ("yellow" if int(val) < int(thresholds[2]) else
                   "green")))
    except ValueError:
       return "grey"
#
# Given a time series history of [(ts:value)], calculate "<MISSING>" intervals
# as % of total ( ts[-1] - ts[0] ns )
#
def Calculate_SLA(history):
    logging.info( f"Calculate_SLA history={history}" )
    if len(history)==0:
        return "N/A"

    ts_start, v_start = history[0]
    ts_end, v_end = history[-1]

    if v_end == "<MISSING>":
        return "0.000" # Dont report a stale availability value, it will stay the same until samples continue

    if ts_start == ts_end:
        return "100.000"

    ts_cur = ts_start
    missing_ns = 0
    in_missing = False
    for ts,val in history:
        if val=="<MISSING>":
            missing_ns += (ts - ts_cur)
            in_missing = True
        elif in_missing:
            missing_ns += (ts - ts_cur)
            in_missing = False
        ts_cur = ts
    avail = 100.0 * (1.0 - (missing_ns / (ts_end - ts_start)))
    return f'{avail:.3f}' # 3 digits, e.g. 99.999

def Update_Observation(o, timestamp_ns, trigger, sample_interval, updates, history):
    global filter_count
    global reports_count
    reports_count = reports_count + 1

    # Clear any reset flag
    o.pop('reset_flag', None)

    name = o['name']
    thresholds = [ t['value'] for t in (o['conditions']['thresholds'] if 'thresholds' in o['conditions'] else []) ]

    now = datetime.now()
    now_ts = now.strftime("%Y-%m-%dT%H:%M:%SZ")
    update_data = {
      'last_updated' : { "value" : now_ts },
      'count': reports_count,
      'filtered': filter_count,
      # test
      # 'count2': 2*reports_count,
      # 'count3': 3*reports_count,
      # 'report_history': [ report ] # This replaces the whole list, instead of appending
    }
    # js_path = '.' + agent_name + '.intensive_care.observe{.name=="' + name + '"}.statistics'
    js_path = '.' + agent_name + '.reports' # .intensive_care.statistics
    response = Add_Telemetry( js_path=js_path, js_data=json.dumps(update_data) )
    logging.info(f"Telemetry_Update_Response :: {response}")

    # gNMI test
    # t_path = '.' + agent_name + '.intensive_care.statistics.test{.testname=="test1"}'
    # response = Add_Telemetry( js_path=t_path, js_data=json.dumps({ 'testvalue' : { 'value' : 'X' }}) )
    #t_path = '.' + agent_name + '.intensive_care.statistics.vtest2{.testname=="test2"}'
    #response = Add_Telemetry( js_path=t_path, js_data=json.dumps({ 'testvalue' : { 'value' : 'Y' }}) )
    #t_path = '.' + agent_name + f'.intensive_care.statistics.vtest2{{.testname=="{name}"}}'
    #response = Add_Telemetry( js_path=t_path, js_data=json.dumps({ 'testvalue' : { 'value' : trigger }}) )
    # end test

    gnmi_ts = datetime.fromtimestamp(timestamp_ns // 1e9, tz=timezone.utc)
    gnmi_str = '{}.{:09.0f}'.format(gnmi_ts.strftime('%Y-%m-%dT%H:%M:%S'), timestamp_ns % 1e9)

    event_path = js_path + f'.events{{.event=="{gnmi_str} {name}"}}'
    update_data = {
      'name': { 'value': name },
      'timestamp': timestamp_ns,  # Use gNMI reported timestamp
      'sample_period': { 'value': sample_interval },
      'trigger': { 'value': trigger },
      'values': [ f'{path}={value}' for path,value in updates ],
    }
    response = Add_Telemetry( js_path=event_path, js_data=json.dumps(update_data) )

    # XXX very inefficient, could use a bulk method
    # Add only this new measurement to history, use now_ts instead of gNMI reported ts
    # for path in history:
    #  for ts,val in history[path]:
    path,val = updates[0]
    # js_path2 = js_path + f'.history{{.name=="{name}"}}.path{{.path=="{path}"}}.event{{.t=="{now_ts}"}}'
    # js_path2 = js_path + f'.history{{.name=="{name}"}}.path{{.path=="{path}"}}'
    # response = Add_Telemetry( js_path=js_path2, js_data=json.dumps({'t': now.timestamp(), 'v': {'value':val} }) )

    js_path2 = js_path + f'.history{{.name=="{name}"}}.path{{.path=="{path}"}}.event{{.t=="{timestamp_ns}"}}'
    response = Add_Telemetry( js_path=js_path2, js_data=json.dumps({'v': {'value': str(val) } }) )

    if sample_interval != 0:
        if path == "count":
           max_count = max( [ len(vs) for t,vs in history ] + [ len(val) ] )
           avail = 100.0 * (len(val) / max_count)
           sla = f'{avail:.3f}' # 3 digits, e.g. 99.999
           data = {
             'availability': { 'value': sla },
             'count': { 'value': len(val) },
             'values': val
           }
        else:
           sla = Calculate_SLA(history)
           data = {
             'availability': { 'value': sla } # "CRASH-TEST" also crashes
           }

        # Only update if SLA has changed, else this triggers onchange events
        if True: # 'last_sla' not in o or o['last_sla'] != (sla,val):
           if thresholds != []:
              # TODO calculate min/max/avg as requested
              if thresholds[0]=="availability":
                  val = int(float(sla)) if sla!="DOWN" else 0
                  thresholds = thresholds[1:]
              else:
                  val = updates[0][1]

              status = Threshold_Color( val, thresholds )
              data['status'] = { 'value' : status }
              if 'metric' in o['conditions']:
                  metric = o['conditions']['metric']['value']
                  Update_Metric( metric, name, status )

           # js_path += f'.availability{{.name=="{name}"}}' # crashes
           js_path = '.' + agent_name + '.health.route'
           logging.info( f"SLA Add_Telemetry({o}): {js_path}={data} {sla} {val}" )
           # This leads to SRL mgr crashes
           response = Add_Telemetry( js_path=js_path, js_data=json.dumps(data) )
           o['last_sla'] = (sla,val)

      # logging.info(f"Telemetry_Update_Response history :: {response}")

def Update_Global_State(state, var, val):
    js_path = '.' + agent_name + '.' + var
    response = Add_Telemetry( js_path=js_path, js_data=json.dumps(val) )
    logging.info(f"Telemetry_Update_Response :: {response}")

##################################################################
## Proc to process the config Notifications received by auto_config_agent
## At present processing config from js_path containing agent_name
##################################################################
def Handle_Notification(obj, state):
    if obj.HasField('config'):
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
                # Don't replace ' in filter expressions
                json_acceptable_string = obj.config.data.json # .replace("'", "\"")
                data = json.loads(json_acceptable_string)

                if obj.config.key.js_path == ".docter_agent.intensive_care.observe":

                    name = obj.config.key.keys[0]
                    # Can be empty
                    reports = ([ i['value'] for i in data['observe']['report'] ] if 'observe' in data else [])
                    if name in state.observations:
                       state.observations[ name ].update( { 'reports': reports, **data } )
                    else:
                       state.observations[ name ] = { 'reports' : reports, **data }
                elif obj.config.key.js_path == ".docter_agent.intensive_care.observe.conditions":
                    name = obj.config.key.keys[0]
                    path = obj.config.key.keys[1]  # XXX only supports single path per observation for now
                    if name in state.observations:
                       state.observations[ name ].update( { 'path': path, **data } )
                    else:
                       state.observations[ name ] = { 'path' : path, **data }

                return True # subscribe to LLDP
        elif obj.config.key.js_path == ".commit.end":
           if state.observations != {}:
              MonitoringThread( state.observations ).start()

    else:
        logging.info(f"Unexpected notification : {obj}")

    # dont subscribe to LLDP now
    return False


# 2021-8-24 Yang paths in gNMI UPDATE events can have inconsistent ordering of keys, in the same update (!):
# 'network-instance[name=overlay]/bgp-rib/ipv4-unicast/rib-in-out/rib-in-post/routes[neighbor=192.168.127.3][prefix=10.10.10.10/32]/last-modified'
# 'network-instance[name=overlay]/bgp-rib/ipv4-unicast/rib-in-out/rib-in-post/routes[prefix=10.10.10.10/32][neighbor=192.168.127.3]/tie-break-reason
#
#path_key_regex = re.compile( '^(.*)\[([0-9a-zA-Z.-]+=[^]]+)\]\[([0-9a-zA-Z.-]+=[^]]+)\](.*)$' )
#def normalize_path(path):
#    double_index = path_key_regex.match( path )
#    if double_index:
#        g = double_index.groups()
#        if g[1] > g[2]:
#           return f"{g[0]}[{g[2]}][{g[1]}]{g[3]}"
#    return path # unmodified

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
                # 'mode': 'on_change'
                'mode': 'on_change' if value['conditions']['sample_period']['value'] == '0' else 'sample',
                'sample_interval':  int(value['conditions']['sample_period']['value']) * 1000000000 # in ns
            } for key,value in self.observations.items()
        ],
        'use_aliases': False,
        # 'updates_only': True, # Optional
        'mode': 'stream',
        'encoding': 'json'
      }
      logging.info( f"MonitoringThread subscription: {subscribe}")

      # Build lookup map
      lookup = {}
      regexes = []
      for name,atts in self.observations.items():
          path = atts['path']     # normalized in pygnmi patch
          update_match = atts['conditions']['update_path_match']['value']
          obj = { 'name': name, 'data': {}, **atts }
          if '*' in path or update_match!="":
             # Turn path into a Python regex
             regex = (update_match if update_match!=""
                else path.replace('*','.*').replace('[','\[').replace(']','\]'))
             regexes.append( (re.compile(regex),obj) )
          else:
             lookup[ path ] = obj
      logging.info( f"Built lookup map: {lookup} regexes={regexes} for sub={subscribe}" )

      def find_regex( path ):
        for r,o in regexes:
          if r.match( path ):
            return o
        return None

      def update_history( ts_ns, o, key, updates ):
          history = o['data'][ key ] if key in o['data'] else {}

          if 'history_window' in o['conditions']:
            window = ts_ns - int(o['conditions']['history_window']['value']) * 1000000000 # X seconds ago
          else:
            window = 0

          if 'history_items' in o['conditions']:
            max_items = int(o['conditions']['history_items']['value'])
          else:
            max_items = 0

          for path, val in updates:
             subitem = history[path] if path in history else []
             if window>0:
                subitem = [ (ts,val) for ts,val in subitem if ts>=window ]
             if max_items>0:
                subitem = subitem[ -max_items: ]
             subitem.append( (ts_ns,val) )
             history[ path ] = subitem
          o['data'][ key ] = history

          # Return top path history
          logging.info( f'update_history max={max_items} window={window} -> returning {updates[0][0]}' )
          return history[ updates[0][0] ]

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

                  # For entries with a 'count' regex, count unique values in this update
                  unique_count_o = None
                  unique_count_matches = {}
                  for u in update['update']:

                      # Ignore any updates without 'val'
                      if 'val' not in u:
                          continue;

                      key = '/' + u['path'] # pygnmi strips '/'
                      if key in lookup:
                         o = lookup[ key ]
                      elif regexes!=[]:
                         o = find_regex( key )
                         if o is None:
                            logging.info( f"No matching regex found - skipping: '{key}' = {u['val']}" )
                            continue
                      else:
                         logging.info( f"No matching key found and no regexes - skipping: '{key}' = {u['val']}" )
                         continue

                      # logging.info( f"Evaluate any filters: {o}" )
                      if 'conditions' in o and 'filter' in o['conditions']:
                          filter = o['conditions']['filter']['value']
                          _globals = { "ipaddress" : ipaddress }
                          _locals  = { "_" : u['val'] }
                          if not eval( filter, _globals, _locals ):
                              logging.info( f"Filter {filter} with value _='{u['val']}' = False, skipping..." )
                              Update_Filtered(o, int( update['timestamp'] ), key, u['val'] )
                              continue;

                      # For sampled state, reset the interval timer
                      sample_period = o['conditions']['sample_period']['value']
                      if sample_period != "0":
                          if 'timer' in o:
                              o['timer'].cancel()
                          def missing_sample( _o, _key, _sample_period, _ts ):
                             logging.info( f"Missing sample: {_key}" )
                             index = _key.rindex('/') + 1
                             ts_ns = _ts + 1000000000 * int(_sample_period)
                             history = update_history( ts_ns, _o, _key, [ (_key,"<MISSING>") ] )
                             Update_Observation( _o, ts_ns, f"{_key[index:]}=missing sample={sample_period}", int(_sample_period), [(_key,"<MISSING>")], history )

                          timer = o['timer'] = Timer( int(sample_period) + 1, missing_sample, [ o, key, sample_period, int( update['timestamp'] ) ] )
                          timer.start()

                          # Also process any 'count' regex, could compile once
                          if 'count' in o['conditions']:
                              count_regex = o['conditions']['count']['value']
                              unique_count_o = o
                              # logging.info( f"Match {count_regex} against {key}" )
                              m = re.match( count_regex, key )
                              if m:
                                # logging.info( f"Matches found: {m.groups()}" )
                                for g in m.groups():
                                   unique_count_matches[ g ] = True
                                continue  # Skip updating invidivual values

                      # Add condition path as implicit reported value
                      updates = [ (key,u['val']) ]
                      reports = o['reports']
                      if reports != []:
                        data = c.get(path=reports, encoding='json_ietf')
                        logging.info( f"Reports:{data} val={u['val']}" )
                        # update Telemetry, iterate
                        i = 0
                        for n in data['notification']:
                           if 'update' in n: # Update is empty when path is invalid
                             for u2 in n['update']:
                                updates.append( (u2['path'],u2['val']) )
                           else:
                             # Assumes updates are in same order
                             updates.append( (reports[i], 'GET failed') )
                           i = i + 1

                      # Update historical data, indexed by key. Remove old entries
                      history = update_history( int( update['timestamp'] ), o, key, updates )
                      index = key.rindex('/') + 1
                      sample = o['conditions']['sample_period']['value']
                      Update_Observation( o, int( update['timestamp'] ), f"{key[index:]}={u['val']} sample={sample}", int(sample), updates, history )

                  if unique_count_o is not None:
                      logging.info( f"Reporting unique values: {unique_count_matches}" )
                      vals = sorted( list(unique_count_matches.keys()) )
                      updates = [("count",vals)]
                      series = update_history( int( update['timestamp'] ), unique_count_o, "count", updates )
                      cur_set = set( v for ts,vs in series for v in vs )
                      summary = [( "count", sorted(list(cur_set)) )]
                      sample = unique_count_o['conditions']['sample_period']['value']
                      Update_Observation( unique_count_o, int( update['timestamp'] ), f"count={summary}", int(sample), summary, series )

    except Exception as e:
       traceback_str = ''.join(traceback.format_tb(e.__traceback__))
       logging.error(f'Exception caught in gNMI :: {e} stack:{traceback_str}')
    except:
       logging.error(f"Unexpected error: {sys.exc_info()[0]}")

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

    # Grafana_Test()
    Show_Dummy_Health( controlplane="green", links="orange" )

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
    logging.info("START TIME :: {}".format(datetime.now()))
    if Run():
        logging.info('Docter agent unregistered')
    else:
        logging.info('Should not happen')
