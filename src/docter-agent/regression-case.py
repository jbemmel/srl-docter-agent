import grpc
import json
import logging
from logging.handlers import RotatingFileHandler
import time
import os
from datetime import datetime

# SDK imports
import sdk_service_pb2_grpc, telemetry_service_pb2, telemetry_service_pb2_grpc
import config_service_pb2, sdk_service_pb2

agent_name='docter_agent'

stdout_dir = '/var/log/srlinux/stdout' # PyTEnv.SRL_STDOUT_DIR
if not os.path.exists(stdout_dir):
    os.makedirs(stdout_dir, exist_ok=True)
log_filename = f'{stdout_dir}/{agent_name}.log'
logging.basicConfig(
  handlers=[RotatingFileHandler(log_filename, maxBytes=3000000,backupCount=5)],
  format='%(asctime)s,%(msecs)03d %(name)s %(levelname)s %(message)s',
  datefmt='%H:%M:%S', level=logging.INFO)
logging.info("START TIME :: {}".format(datetime.now()))

# Wait for system to startup
time.sleep(10)

############################################################
## Open a GRPC channel to connect to sdk_mgr on the dut
## sdk_mgr will be listening on 50053
############################################################
#channel = grpc.insecure_channel('unix:///opt/srlinux/var/run/sr_sdk_service_manager:50053')
channel = grpc.insecure_channel('127.0.0.1:50053')
metadata = [('agent_name', agent_name)]
stub = sdk_service_pb2_grpc.SdkMgrServiceStub(channel)

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

response = stub.AgentRegister(request=sdk_service_pb2.AgentRegistrationRequest(), metadata=metadata)
logging.info(f"Registration response : {response.status}")

#request=sdk_service_pb2.NotificationRegisterRequest(op=sdk_service_pb2.NotificationRegisterRequest.Create)
#create_subscription_response = stub.NotificationRegister(request=request, metadata=metadata)
#stream_id = create_subscription_response.stream_id
#logging.info(f"Create subscription response received. stream_id : {stream_id}")
#Subscribe(stream_id, 'cfg')

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

logging.info( "SDK mgr crash test..." )
js_path = ".docter_agent.reports.history{.name==\"Broadcast traffic out of physical links\"}.path{.path==\"/interface[name=ethernet-1/2]/statistics/out-broadcast-packets\"}.event{.t==\"1631564696096902958\"}"
response = Add_Telemetry( js_path=js_path, js_data=json.dumps({'v': {'value': "0" } }) )
logging.info( f"SDK mgr crash test done...{response}" )
