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

# To report state back
import telemetry_service_pb2
import telemetry_service_pb2_grpc

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

# Filter out whitespace and other possibly problematic characters
def clean(str):
    return str.replace(' ','_')

############################################################
## Subscribe to required event
## This proc handles subscription of: Config
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
def Update_Metric(ts_ns, metric, contributor, contrib_status, updates=[], sla=None ):
    base_path = '.' + agent_name + f'.metrics.metric{{.name=="{metric}"}}'
    js_path = base_path + f'.contribution{{.name=="{ clean(contributor) }"}}'
    metric_data = {
      'status' : { 'value' : contrib_status }
    }
    if sla is not None:
        metric_data['availability'] = { 'value' : sla }

    if updates!=[]:
        # Hardcoded hack: show top CPU usage per process more nicely
        def show(path,data):
            if ((isinstance(data, dict) and 'srl_nokia-platform-cpu:process' in data)
             or re.match( ".*\\[pid=([0-9]+)\\].*", path )):
               # Config is arranged such that pid->application mapping is in updates[2][1] or updates[3][1]
               pid_2_app = {}

               if isinstance(data, dict):
                 if len(updates)>3 and 'application' in updates[3][1]:
                    # Some apps are not running and have no pid
                    pid_2_app = { int(p['pid']) : p['name'] for p in updates[3][1]['application'] if 'pid' in p }
                    # logging.info( f"PID mapping: {pid_2_app}" )
                    # del updates[u][1]['application']
               # else:
                #    logging.warning( f"JvB no pid-2-app: u={u} ({updates})" )
               import psutil
               def pid_2_proc(pid):
                   try:
                       return (pid_2_app[pid] if pid in pid_2_app else
                           data['name'] if 'name' in data else
                           psutil.Process(pid).name())
                   except Exception as ex: # psutil may fail
                       logging.error( f"Error mapping pid to process name: {ex}" )
                       return str(pid)

               if 'srl_nokia-platform-cpu:process' in data:
                 pid_data = data['srl_nokia-platform-cpu:process']
                 vals = [ ( f'cpu={v["cpu-utilization"]:02d}%',
                          f'process={ pid_2_proc( pid ) }' )
                          for v in pid_data if v['cpu-utilization'] > 0
                          for pid in [ int(v["pid"]) ]
                        ]
                 return "Top 5:" + str(sorted(vals,reverse=True)[:5]) # Top 5
               else:
                 pid_cpu = re.match( ".*\\[pid=([0-9]+)\\].*", path )
                 if pid_cpu:
                     _pid = int( pid_cpu.groups()[0] )
                     _name = f"{pid_2_proc( _pid )}({_pid})"
                     return f"process {_name} details {data}"

            return f'{path}={data}'

        metric_data['reports'] = [ show(path,value) for path,value in updates ]

    response = Add_Telemetry( js_path=js_path, js_data=json.dumps(metric_data) )
    logging.info(f"Update_Metric Telemetry_Update_Response :: {response}")

    def worst(s1,s2):
        if s1=="red" or s2=="red":
            return "red"
        elif s1=="orange" or s2=="orange":
            return "orange"
        elif s1=="yellow" or s2=="yellow":
            return "yellow"
        elif s1!="green":
            return s1
        else:
            return s2

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

    data = {
       'status' : { 'value' : overall },
       'cause'  : { 'value' : cause },
       'status_summary' : { 'value' : f"{overall}:{cause}" if overall!="green" else "green" },
    }

    # If this update made things worse, report detailed status too
    if cause == contributor and contrib_status!="green":
        data['status_detail'] = { 'value': f"{contributor}:{contrib_status}:{[ f'{path}={value}' for path,value in updates[1:] ]}" }
    elif overall=="green":
        data['status_detail'] = { 'value': "green" }

    response = Add_Telemetry( js_path=base_path, js_data=json.dumps(data) )

# No longer used
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

def Color(o,val,history=None):
    if 'thresholds' in o['conditions']:
        # XXX could do this one when processing config
        thresholds = [ t['value'] for t in o['conditions']['thresholds'] ]
        if len(thresholds)>0 and thresholds[0]=="availability" and history:
            sla = val = Calculate_SLA(history)
        else:
            sla = None
        color = Threshold_Color(val,thresholds)
        return color, thresholds, sla
    elif val is None: # <MISSING> case
        return o['conditions']['missing']['value'] # Default: grey
    else:
        for c in ["red","orange","yellow","green"]:
            if c in o['conditions']:
                exp = o['conditions'][c]['value']
                try:
                  if eval( exp, {}, { 'value': val } ):
                    return c, None, None
                except Exception as ex:
                  logging.error( f"Error evaluating color {c}={exp}: {ex} (value={val} type={type(val)})" )
        logging.error( f"None of the color expressions matched '{val}' -> None" )
        return None, None, None

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
    if 'reset_flag' not in o or o['reset_flag'] != "green":
      js_path2 = js_path + f'.history{{.name=="{clean(o["name"])}"}}.path{{.path=="{path}"}}.event{{.t=="{timestamp_ns}"}}'
      response = Add_Telemetry( js_path=js_path2, js_data=json.dumps({'v': {'value':val}, 'filter': False }) )
      color = None
      if 'metric' in o['conditions']:
          metric = o['conditions']['metric']['value']
          color, _, sla = Color(o, val)
          if color:
             Update_Metric( timestamp_ns, metric, o['name'], color, sla=sla )
      o['reset_flag'] = color or "green"

def Threshold_Color( val, thresholds ):
    logging.info( f"Threshold_Color({val}) with thresholds={thresholds}" )
    availability = [ "red", "orange", "yellow", "green" ]
    colors = [ "green", "yellow", "orange", "red" ]
    if thresholds[0]=="availability" or thresholds[0]=="red-to-green":
        colors = availability
        thresholds = thresholds[1:]
    try:
       if len(thresholds)==0:
           return "green"
       elif len(thresholds)==1:
           return "red" if val != thresholds[0] else "green"
       elif isinstance(val, (int,float)) or val.isnumeric():
         if len(thresholds)==2:
           return (colors[0] if int(val) <= int(thresholds[0]) else
                  (colors[1] if int(val) <= int(thresholds[1]) else
                   colors[2]))
         else: # 3 or more
           return (colors[0] if int(val) <= int(thresholds[0]) else
                  (colors[1] if int(val) <= int(thresholds[1]) else
                  (colors[2] if int(val) <= int(thresholds[2]) else
                   colors[3])))
       else: # Compare strings in order
          for i,t in enumerate(thresholds):
              if val==t:
                  return colors[i]
          logging.warning( f"None of threshold values {thresholds} matched {val}" )

    except ValueError as ve:
       logging.error(ve)

    return "red" # e.g. <MISSING> or no match
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
        return 0 # Dont report a stale availability value, it will stay the same until samples continue

    if ts_start == ts_end:
        return 100

    ts_cur = ts_start
    missing_ns = 0
    in_missing = False
    for ts,val in history:
        if val=="<MISSING>":
            missing_ns += (ts - ts_cur)
            in_missing = True
        elif in_missing:
            # Weigh more recent outages more, ts==ts_end = most recent
            missing_ns += (ts - ts_cur) * (ts/ts_end)
            in_missing = False
        ts_cur = ts
    avail = 100.0 * (1.0 - (missing_ns / (ts_end - ts_start)))
    return avail # f'{avail:.3f}' # 3 digits, e.g. 99.999

def Update_Observation(o, timestamp_ns, trigger, sample_interval, updates, history, path=None, value=None ):
    global filter_count
    global reports_count
    reports_count = reports_count + 1

    # Clear any reset flag
    o.pop('reset_flag', None)

    name = o['name']

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

    # event_path = js_path + f'.events{{.event=="{gnmi_str} {name}"}}'
    # Try to avoid crashes, keep keys small?
    event_path = js_path + f'.events{{.event=="{gnmi_str}"}}'
    update_data = {
      'name': { 'value': name },
      'timestamp': timestamp_ns,  # Use gNMI reported timestamp
      'sample_period': { 'value': sample_interval },
      'trigger': { 'value': trigger },
      'values': [ f'{path}={value}' for path,value in updates ],
    }
    response = Add_Telemetry( js_path=event_path, js_data=json.dumps(update_data) )

    # Try to avoid SDK mgr crash
    regex,val = updates[0]
    _key = path if path is not None else regex
    js_path2 = js_path + f'.history{{.name=="{clean(name)}"}}.path{{.path=="{_key}"}}.event{{.t=="{timestamp_ns}"}}'
    response = Add_Telemetry( js_path=js_path2, js_data=json.dumps({'v': {'value': str(val) } }) )

    color, thresholds, sla = Color(o,value,history) # May calculate SLA if "availability" in thresholds
    if color:
      data = { 'status' : { 'value' : color } }
      if sla is not None:
        data['availability'] = { 'value': sla }
        # TODO more?

      if 'metric' in o['conditions']:
         metric = o['conditions']['metric']['value']
         Update_Metric( timestamp_ns, metric, name, color, updates, sla )

         # If requested, start a 'clear' timer to reset any non-green state
         if color != 'green' and 'reset' in o['conditions']:
             reset_timer_s = int(o['conditions']['reset']['value'])
             logging.info( f"Starting reset timer({reset_timer_s}) to clear {color} for {name}" )
             def reset_status():
                ts = timestamp_ns + 1e9 * reset_timer_s
                Update_Metric( ts, metric, name, "green",
                  [ (gnmi_str+f"+{reset_timer_s}s", f"reset '{color}' to green" ) ] )
             # Could save this in o['reset_timer']
             timer = Timer( reset_timer_s, reset_status )
             timer.start()

      else:
        # Legacy reporting structure of route availability
        # js_path += f'.availability{{.name=="{name}"}}' # crashes SRL mgr
        js_path = '.' + agent_name + '.health.route'
        logging.info( f"Legacy Add_Telemetry({name}): {js_path}={data} {val}" )
        response = Add_Telemetry( js_path=js_path, js_data=json.dumps(data) )
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
                       logging.info( f"Check insertion order: {name}" )
                       state.observations[ name ] = { 'path' : path, **data }

                elif obj.config.key.js_path == ".docter_agent":
                    if 'intensive_care' in data:
                      _ic = data['intensive_care']
                      if 'startup_delay' in _ic:
                         state.startup_delay = int( _ic['startup_delay']['value'] )

                return True # subscribe to LLDP
        elif obj.config.key.js_path == ".commit.end":
           if state.observations != {}:
              MonitoringThread( state.observations, state.startup_delay ).start()

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
   def __init__(self, observations, startup_delay):
       Thread.__init__(self)
       self.observations = observations
       self.startup_delay = startup_delay
       # Check that gNMI is connected now
       # grpc.channel_ready_future(gnmi_channel).result(timeout=5)


   def run(self):

      # Create per-thread gNMI stub, using a global channel
      # gnmi_stub = gNMIStub( gnmi_channel )
    try:
      logging.info( f"MonitoringThread: {self.observations} startup-delay={self.startup_delay}s")

      # Publish some pending gNMI state so subscriptions work
      def Set_Booting(status):
        for key,value in self.observations.items():
          if 'metric' in value['conditions']:
            metric = value['conditions']['metric']['value']
            Update_Metric( 0, metric, "Booting", status )
          else:
            # Legacy health too, default to "red"
            js_path = '.' + agent_name + '.health.route'
            data = {
              'status' : { 'value' : status if status!="green" else "red" },
              'availability' : { 'value': 0 }
            }
            Add_Telemetry( js_path=js_path, js_data=json.dumps(data) )

      Set_Booting("pending" if self.startup_delay > 0 else "green")

      if self.startup_delay > 0:
          import time
          time.sleep( self.startup_delay )
          Set_Booting("green")

      # TODO expand paths like in opergroup agent, to allow regex generators
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

      def fix(regex):
          return regex.replace('*','.*').replace('[','\[').replace(']','\]')

      for name,atts in self.observations.items():
          path = atts['path']     # normalized in pygnmi patch
          update_match = atts['conditions']['update_path_match']['value']
          obj = { 'name': name, 'history': {}, 'last_known': {}, 'prev_known': {}, **atts }
          # range_match = re.match("(.*)(\\[\d+[-]\d+\\])(.*)",path)

          # Turn path into a Python regex
          if update_match!="":
             regexes.append( (re.compile(update_match),obj) )
             #if range_match:
             #   logging.warning( f"update_match overrides range match in gnmi-path: {path}" )
          #elif range_match:
          #     p1 = fix( range_match.groups()[0] )
          #     r  = range_match.groups()[1]
          #     p2 = fix( range_match.groups()[2] )
          #     regex = p1 + r + p2
          elif '*' in path:
             regexes.append( (re.compile( fix(path) ),obj) )
          else:
             lookup[ path ] = obj

      logging.info( f"Built lookup map: {lookup} regexes={regexes} for sub={subscribe}" )

      def find_regex( path ):
        for r,o in regexes:
          if r.match( path ):
            return o, r.pattern
        return None,None

      def update_history( ts_ns, o, key, updates ):
          history = o['history'][ key ] if key in o['history'] else {}
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
                if subitem==[]:
                   subitem = [(window,"<MISSING>")] # Start as MISSING
                else:
                    ts1, first = subitem[0]
                    ts2, last = subitem[-1]
                    if (ts2<window and last=="<MISSING>"):
                        # Move <MISSING> to edge of window, rest gets flushed
                        subitem = [ (window,last) ]
                    elif ts1!=ts2 and ts1<window and first=="<MISSING>":
                        if subitem[1][0] > window:
                           subitem = [ (window,first) ] + subitem[1:] # Move it along
                subitem = [ (ts,val) for ts,val in subitem if ts>=window ]
             if max_items>0:
                subitem = subitem[ -max_items: ]
             subitem.append( (ts_ns,val) )
             history[ path ] = subitem
          o['history'][ key ] = history

          # Return aggregated regex path history
          logging.info( f'update_history key={key} max={max_items} window={window} -> returning { history[ key ] }' )
          return history[ key ]

      # with Namespace('/var/run/netns/srbase-mgmt', 'net'):
      with gNMIclient(target=('unix:///opt/srlinux/var/run/sr_gnmi_server',57400),
                            username="admin",password="admin",
                            insecure=True, debug=False) as c:
        logging.info( f"gNMIclient: subscribe={subscribe}" )

        #
        # TODO check why this hangs for '/bfd/network-instance[name=default]/peer/oper-state'
        #
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
                  # unique_count_o = None
                  # unique_count_matches = {}
                  for u in update['update']:

                      # Ignore any updates without 'val'
                      if 'val' not in u:
                          continue;

                      key = '/' + u['path'] # pygnmi strips '/'
                      regex = None
                      if key in lookup:
                         o = lookup[ key ]
                      elif regexes!=[]:
                         o, regex = find_regex( key )
                         if o is None:
                            logging.info( f"No matching regex found - skipping: '{key}' = {u['val']}" )
                            continue

                      else:
                         logging.info( f"No matching key found and no regexes - skipping: '{key}' = {u['val']}" )
                         continue

                      value = u['val']

                      # Use regex to aggregate history values (common path)
                      history_key = regex if regex is not None else key

                      # Add regex='val' and path='val' as implicit reported value? Just key=val for now
                      updates = [ (key,value) ] + ( [ (history_key,value) ] if regex else [] )

                      if 'conditions' in o: # Should be the case always
                        # To group subscriptions matching multiple paths, can collect by custom regex 'index'
                        # index = key
                        #if 'index' in o['conditions']:
                        #    _re = o['conditions']['index']['value']
                        #    _i = re.match( _re, key)
                        #    if _i and len(_i.groups()) > 0:
                        #      index = _i.groups()[0]
                        #    else:
                        #      logging.error( f"Error applying 'index' regex: {_re} to {key}" )
                        o['prev_known'][ key ] = o['last_known'][ key ] if key in o['last_known'] else 0
                        o['last_known'][ key ] = u['val']

                        # Helper function
                        def last_known_ints():
                          # List over all subpaths matching this observation
                          vs = list(map(int,o['last_known'].values()))
                          return vs if vs!=[] else [0]

                        def history_ints():
                          # List over a single path's history
                          history = o['history'][history_key] if history_key in o['history'] else {}
                          # history = { path -> (ts,val) } ??
                          logging.info( f"history_ints: {history}" )
                          values = history[history_key] if history_key in history else [(0,0)]

                          # Could calculate diffs: [ abs(vs[n]-vs[n-1]) for n in range(1,len(vs)) ]
                          return [ int(v) for t,v in values ]

                        def max_in_history(value_if_no_history=0):
                            hist = history_ints()
                            return max(hist) if hist!=[] else int(value_if_no_history)

                        def avg_in_history(value_if_no_history=0):
                            hist = history_ints()
                            return (sum(hist)/len(hist)) if hist!=[] else int(value_if_no_history)

                        def max_or_0(vals,x=0):
                            return max(vals) if vals!=[] else x

                        def min_or_0(vals,x=0):
                            return min(vals) if vals!=[] else x

                        def last_known_deltas():
                            ds = [ abs(int(v)-int(o['prev_known'][k])) for k,v in o['last_known'].items() ]
                            return ds if ds!=[] else [0] # Allow min/max to work

                        _globals = { "ipaddress" : ipaddress }
                        _locals  = { "_" : u['val'], **o,
                                     "last_known_ints": last_known_ints,
                                     "history_ints": history_ints,
                                     "max_in_history": max_in_history,
                                     "avg_in_history": avg_in_history,
                                     "max_or_0": max_or_0,
                                     "min_or_0": min_or_0,
                                     "last_known_deltas": last_known_deltas,
                                   }

                        # Custom value calculation, before filter
                        if 'value' in o['conditions']:
                          value_exp = o['conditions']['value']['value']
                          try:
                             value = eval( value_exp, _globals, _locals )
                             updates.append( (value_exp,value) )
                          except Exception as e:
                             logging.error( f"Custom value {value_exp} failed: {e}")
                        else:
                          updates.append( ('value',value) )

                        # logging.info( f"Evaluate any filters: {o}" )
                        if 'filter' in o['conditions']:
                          filter = o['conditions']['filter']['value']
                          _locals.update( { 'value': value } )
                          try:
                            if not eval( filter, _globals, _locals ):
                              logging.info( f"Filter {filter} with _='{u['val']}' value='{value}' = False, skipping..." )
                              Update_Filtered(o, int( update['timestamp'] ), key, value )
                              continue;
                          except Exception as ex:
                            logging.error( f"Exception during filter {filter}: {ex}" )

                      # For sampled state, reset the interval timer
                      sample_period = o['conditions']['sample_period']['value']
                      if sample_period != "0":
                          if 'timer' in o:
                              if key in o['timer']:
                                 o['timer'][key].cancel()
                          else:
                              o['timer'] = {}
                          def missing_sample(_o,_key,_hist_key,_ts_ns,_sample_period):
                             logging.info( f"Missing sample timer: {_key} aggregate history_key={_hist_key}" )
                             _i = _key.rindex('/') + 1
                             _history = update_history( _ts_ns, _o, _hist_key, [ (_key,"<MISSING>"),( _hist_key,"<MISSING>") ] )
                             Update_Observation( _o, _ts_ns, f"{_key[_i:]}=missing sample={_sample_period}",
                                                 int(_sample_period), [(_hist_key,"<MISSING>")], _history, path=_key )

                          ts_ns = int( update['timestamp'] ) + 1000000000 * int(sample_period)
                          timer = o['timer'][key] = Timer( int(sample_period) + 1, missing_sample,
                                                           [o,key,history_key,ts_ns,sample_period] )
                          timer.start()

                        # Also process any 'count' regex, could compile once
                        # if 'count' in o['conditions']:
                        #      count_regex = o['conditions']['count']['value']
                        #      unique_count_o = o
                        #      # logging.info( f"Match {count_regex} against {key}" )
                        #      m = re.match( count_regex, key )
                        #      if m:
                        #        # logging.info( f"Matches found: {m.groups()}" )
                        #        for g in m.groups():
                        #           unique_count_matches[ g ] = True
                        #        continue  # Skip updating invidivual values

                      reports = o['reports']
                      if reports != []:
                        def _lookup(param): # match looks like {x}
                           _var = param[1:-1]  # Strip '{' and '}'
                           _val = re.match( f".*\[{_var}=([^]]+)\].*", key)
                           if _val:
                              return _val.groups()[0]
                           else:
                              logging.error( f"Unable to resolve {param} in {key}, returning '*'" )
                              return "*" # Avoid causing gNMI errors

                        # Substitute any {key} values in paths
                        resolved_paths = [ re.sub('\{(.*)\}', lambda m: _lookup(m.group()), path) for path in reports ]

                        data = c.get(path=resolved_paths, encoding='json_ietf')
                        logging.info( f"Reports:{data} val={value}" )
                        # update Telemetry, iterate
                        i = 0
                        for n in data['notification']:
                           if 'update' in n: # Update is empty when path is invalid
                             for u2 in n['update']:
                                updates.append( (u2['path'],u2['val']) )
                           else:
                             # Assumes updates are in same order
                             updates.append( (resolved_paths[i], 'GET failed') )
                           i = i + 1

                      # Update historical data, indexed by key. Remove old entries
                      history = update_history( int( update['timestamp'] ), o, history_key, updates )
                      s_index = key.rindex('/') + 1
                      sample = o['conditions']['sample_period']['value']
                      try:
                         Update_Observation( o, int( update['timestamp'] ), f"{key[s_index:]}={value} sample={sample}",
                                             int(sample), updates, history,
                                             path=key, value=value ) # Use actual path for event reporting
                      except Exception as ex:
                         traceback_str = ''.join(traceback.format_tb(ex.__traceback__))
                         logging.error( f"Exception while updating telemetry - EXITING: {ex} ~ {traceback_str}" )

                         # Force agent to exit
                         Exit_Gracefully(0,0)

                #  if unique_count_o is not None:
                #      vals = sorted( list(unique_count_matches.keys()) )
                #      updates = [("count",vals)]
                #      series = update_history( int( update['timestamp'] ), unique_count_o, "count", updates )
                #      cur_set = set( v for ts,vs in series for v in vs )
                #      logging.info( f"Reporting unique values: {unique_count_matches} -> cur_set={cur_set}" )
                #      summary = [( "count", sorted(list(cur_set)) )]
                #      sample = unique_count_o['conditions']['sample_period']['value']
                #      Update_Observation( unique_count_o, int( update['timestamp'] ), f"count={summary}", int(sample), summary, series )

    except Exception as e:
       traceback_str = ''.join(traceback.format_tb(e.__traceback__))
       logging.error(f'Exception caught in gNMI :: {e} stack:{traceback_str}')
    except:
       logging.error(f"Unexpected error: {sys.exc_info()[0]}")

    logging.info("Leaving gNMI subscribe loop")

class State(object):
    def __init__(self):
        self.startup_delay = 0
        from collections import OrderedDict # From 3.6 default dict should be ordered
        self.observations = OrderedDict() # Map of [name] -> { paths: [], reports: [] }

    def __str__(self):
        return str(self.__class__) + ": " + str(self.__dict__)

##################################################################################################
## This is the main proc where all processing for docter_agent starts.
## Agent registration, notification registration, Subscrition to notifications.
## Waits on the subscribed Notifications and once any config is received, handles that config
## If there are critical errors, Unregisters the fib_agent gracefully.
##################################################################################################
def Run():
    # optional agent_liveliness=<seconds> to have system kill unresponsive agents
    response = stub.AgentRegister(request=sdk_service_pb2.AgentRegistrationRequest(), metadata=metadata)
    logging.info(f"Registration response : {response.status}")

    request=sdk_service_pb2.NotificationRegisterRequest(op=sdk_service_pb2.NotificationRegisterRequest.Create)
    create_subscription_response = stub.NotificationRegister(request=request, metadata=metadata)
    stream_id = create_subscription_response.stream_id
    logging.info(f"Create subscription response received. stream_id : {stream_id}")

    Subscribe_Notifications(stream_id)

    sub_stub = sdk_service_pb2_grpc.SdkNotificationServiceStub(channel)
    stream_request = sdk_service_pb2.NotificationStreamRequest(stream_id=stream_id)
    stream_response = sub_stub.NotificationStream(stream_request, metadata=metadata)

    # Grafana_Test()
    # Show_Dummy_Health( controlplane="green", links="orange" )

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
