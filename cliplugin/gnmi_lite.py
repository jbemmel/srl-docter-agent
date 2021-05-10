import logging
import grpc
from . import gnmi_pb2
import re


class GNMIHandlerLite(object):

    def __init__(self, stub):
        self.stub = stub


    @property
    def socket(self):
        socket = "unix:///opt/srlinux/var/run/sr_gnmi_server"
        return socket

    @classmethod
    def setup_connection(cls, socket="unix:///opt/srlinux/var/run/sr_gnmi_server"):
        channel = grpc.insecure_channel(socket)
        stub = gnmi_pb2.gNMIStub(channel)
        return cls(stub)


    def get_response_from_subcribe(self, xpath_list ):
        #stub = self.setup_connection()
        request_iterator = self.build_request_iterator(xpath_list=xpath_list)
        responses = self.stub.Subscribe(request_iterator=request_iterator)
        return responses


    def build_request_iterator(self, xpath_list):
        """
        :param xpath: list of xpaths to subscribe.
        :return: iterator of SubscribeRequest
        """
        subscriptions = []
        for xpath in xpath_list:
            subscription_path = self._convert_xpath_to_path(xpath)
            subscription = gnmi_pb2.Subscription(path=subscription_path, mode=1) #mode=1 means on-change
            subscriptions.append(subscription)
        subscription_list = gnmi_pb2.SubscriptionList(mode=0, encoding=4, subscription=subscriptions) #mode=0 means stream, encoding=4 means JSON_IETF
        subscribe_request = gnmi_pb2.SubscribeRequest(subscribe=subscription_list)
        yield subscribe_request

    def list_from_path(self, path):
        if path:
            if path[0] == '/':
                if path[-1] == '/':
                    return re.split('''/(?=(?:[^\[\]]|\[[^\[\]]+\])*$)''', path)[1:-1]
                else:
                    return re.split('''/(?=(?:[^\[\]]|\[[^\[\]]+\])*$)''', path)[1:]
            else:
                if path[-1] == '/':
                    return re.split('''/(?=(?:[^\[\]]|\[[^\[\]]+\])*$)''', path)[:-1]
                else:
                    return re.split('''/(?=(?:[^\[\]]|\[[^\[\]]+\])*$)''', path)
        return []

    def _convert_xpath_to_path(self, path):
        mypath = []
        for e in self.list_from_path(path):
            eName = e.split("[", 1)[0]
            eKeys = re.findall('\[(.*?)\]', e)
            dKeys = dict(x.split('=', 1) for x in eKeys)
            mypath.append(gnmi_pb2.PathElem(name=eName, key=dKeys))

        return gnmi_pb2.Path(elem=mypath)

    def _convert_xpath_to_path1(self, path):
        #ToDo enhance for filtering out particular names
        path_elems = []
        path = path.strip('/').split('/')
        for p in path:
            path_elem = gnmi_pb2.PathElem(name=p)
            path_elems.append(path_elem)

        return gnmi_pb2.Path(elem=path_elems)


    def get(self, xpath, operational_state=True):
        """
        :param xpath:
        :param operational_state: gets operational state of xpath, else gets config.
        :return:
        """
        paths = self._convert_xpath_to_path(xpath)
        #stub = self.setup_connection()

        type = 1
        if operational_state is True:
            type = 2

        return self.stub.Get(gnmi_pb2.GetRequest(path=[paths], encoding='JSON_IETF', type=type))


    def set(self, xpath, value):
        """
        Only supports set-update. Todo enhance.
        """
        paths = self._convert_xpath_to_path(xpath)
        val = gnmi_pb2.TypedValue()

        coerced_val = value
        if value.lower() == 'true':
            coerced_val = True
        elif value.lower() == 'false':
            coerced_val = False
        type_to_value = {bool: 'bool_val', int: 'int_val', float: 'float_val',
                         str: 'string_val'}
        setattr(val, type_to_value.get(type(coerced_val)), coerced_val)

        path_val = gnmi_pb2.Update(path=paths, val=val )
        return self.stub.Set(gnmi_pb2.SetRequest(update=[path_val]))





#logger = logging.getLogger(__name__)
#x = OnDeviceGNMIHandler.setup_connection(logger)
#x.set("/system/name/host-name", "usgrx1-123-02-02-dif1-gw2----mgmt")
#responses = x.get_response_from_subcribe(xpath_list=["/system/configuration/last-change"])

#for r in responses:
#    print(r)

#x.get("/system/name/host-name")
