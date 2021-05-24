from srlinux.data import ColumnFormatter, TagValueFormatter, Border, Data, Borders, Alignment
from srlinux.mgmt.cli import CliPlugin
from srlinux.schema import FixedSchemaRoot
from srlinux.syntax import Syntax
from srlinux.location import build_path
# from srlinux.mgmt.cli.plugins.reports.gnmi_lite import GNMIHandlerLite
import datetime

# JvB added
import logging
import traceback
# from nsenter import Namespace
############################ INPUTs here... ############################

# interfaces = ['ethernet-1/1.0', 'ethernet-1/2.0']
uplink_peer_group = 'spines'
rr_peer_group = 'EVPN-NVO'
uplink_network_instance = "default"

########################################################################


class Plugin(CliPlugin):

    def load(self, cli, **_kwargs):
        fabric = cli.show_mode.add_command(Syntax('fabric', help='shows how to give the input parameters for "show fabric" commands'))
        help = fabric.add_command(Syntax('help', help='requires uplinks, route-reflector, statistics or summary keywords'),update_location=False, callback=self._show_help)
        summary = fabric.add_command(Syntax('summary', help='shows uplinks, route-reflector and statistics all together'), update_location=False, callback=self._show_summary, schema=self._get_schema())
        uplink = fabric.add_command(Syntax('uplink', help='shows uplinks in a table'), update_location=False, callback=self._show_uplinks, schema=self._get_schema())
        route_reflector = fabric.add_command(Syntax('route-reflector', help='shows route-reflectors in a table'), update_location=False, callback=self._show_rr, schema=self._get_schema())
        statistics =  fabric.add_command(Syntax('statistics', help='shows statistics in a table'), update_location=False, callback=self._show_stats, schema=self._get_schema())

    def _show_help (self,state,output,**_kwargs):
        print('''
        This 'show fabric' command shows you statistics and the status of the uplinks and BGP peerings.
        Therefore it requires some inputs that need to be added in the 'fabric.py' file.

        '/opt/srlinux/python/virtual-env/lib/python3.6/site-packages/srlinux/mgmt/cli/plugins/reports/fabric.py'

        Example:
        uplink_peer_group = 'spines'
        rr_peer_group = 'EVPN-NVO'
        ''')

    def _show_summary(self, state, output, **_kwargs):

        header = f'Fabric Connectivity Report'
        result_header = self._populate_header(header)
        self._set_formatters_header(result_header)
        output.print_data(result_header)
        self._show_uplinks(state,output)
        self._show_rr(state,output)
        self._show_stats(state,output)

    def _show_uplinks(self, state, output, **_kwargs):
        result = Data(self._get_schema())
        self._set_formatter_uplink(result)
        with output.stream_data(result):
          self._populate_data(result, state)


    def _show_rr(self, state, output, **_kwargs):
        result_rr = Data(self._get_schema())
        self._set_formatters_rr(result_rr)
        with output.stream_data(result_rr):
          self._populate_data_rr(result_rr, state)

    def _show_stats(self, state, output, **_kwargs):
        result_stats = Data(self._get_schema())
        self._set_formatters_stats(result_stats)
        with output.stream_data(result_stats):
          self._populate_data_stats(result_stats, state)

    def _get_header_schema(self):
        root = FixedSchemaRoot()
        root.add_child(
            'header',
            fields=['Summary']
        )
        return root

    def _get_schema(self):
        root = FixedSchemaRoot()
        uplink_header = root.add_child(
            'uplink_header',
            fields=['uplinks']
        )
        uplink_header.add_child(
            'uplink_child',
            key='Local Interface',
            fields=['Local Router', 'Link Status','eBGP Status','Remote Router', 'Remote Interface']
        )
        rr_header = root.add_child(
            'rr_header',
            fields=['Route Reflectors']
        )
        rr_header.add_child(
            'rr_child',
            key='Route Reflector Address',
            fields=['iBGP Status', 'Neighbor Description', 'Rx/Active/Tx', 'Uptime (hh:mm:ss)']
        )
        stats_header = root.add_child(
            'stats_header',
            fields=['Uplink Stats']
        )
        stats_header.add_child(
            'stats_child',
            key='Local Interface',
            fields=['Traffic Bps In/Out','Packets In/Out', 'Errored In/Out', 'FCS Err', 'CRC Err','Transceiver Volt']
        )
        return root

    def _fetch_state(self, state, uplink, interf):
        int_oper_state_path = build_path(f'/interface[name={interf[0]}]/subinterface[index={interf[1]}]/oper-state')
        self.int_oper_state_data = state.server_data_store.stream_data(int_oper_state_path, recursive=True)

        sys_name_path = build_path(f'/system/name/host-name')
        self.sys_name_data = state.server_data_store.stream_data(sys_name_path, recursive=True)

        lldp_neighbor_path = build_path(f'/system/lldp/interface[name={interf[0]}]/neighbor')
        self.lldp_neighbor_data = state.server_data_store.stream_data(lldp_neighbor_path, recursive=True)

        session_state_path = build_path(f'/network-instance[name={uplink_network_instance}]/protocols/bgp/neighbor[peer-address={uplink}]')
        self.session_state_data = state.server_data_store.stream_data(session_state_path, recursive=True)

    def _fetch_state_rr(self, state, rr):
        rr_path = build_path(f'/network-instance[name={uplink_network_instance}]/protocols/bgp/neighbor[peer-address={rr}]')
        self.rr_data = state.server_data_store.stream_data(rr_path, recursive=True)

        time_path = build_path(f'/system/information/current-datetime')
        self.time_data = state.server_data_store.stream_data(time_path, recursive=True)

        # rr_tcp_path = build_path(f'/network-instance[name={uplink_network_instance}]/tcp/connections[remote-address={rr}]')
        # self.rr_tcp_data = state.server_data_store.stream_data(rr_tcp_path, recursive=True)

    def _fetch_state_stats(self, state, uplink):
        gen_path = build_path(f'/interface[name={uplink}]')
        self.gen_data = state.server_data_store.stream_data(gen_path, recursive=True)

    def _time_handler (self, dt0, dt1):
        now = datetime.datetime(int(dt0[:4]),int(dt0[5:7]),int(dt0[8:10]),int(dt0[11:13]),int(dt0[14:16]),int(dt0[17:19]))
        then = datetime.datetime(int(dt1[:4]),int(dt1[5:7]),int(dt1[8:10]),int(dt1[11:13]),int(dt1[14:16]),int(dt1[17:19]))
        return (now-then)

    def _populate_header(self, header):
        result_header = Data(self._get_header_schema())
        data = result_header.header.create()
        data.summary = header
        return result_header

    def _populate_peer_list(self, state, group):
        peer_list_path = build_path(f'/network-instance[name={uplink_network_instance}]/protocols/bgp/neighbor/peer-group')
        peer_list_data = state.server_data_store.stream_data(peer_list_path, recursive=True)
        # logging.info(f'JvB peer_list_data={peer_list_data}')
        peer_list = []
        try: # peer_list_data.network_instance may not exist
           for peer in peer_list_data.network_instance.get().protocols.get().bgp.get().neighbor.items():
               if peer.peer_group == group:
                   # logging.info(f'JvB: appending {peer.peer_address}')
                   peer_list.append(peer.peer_address)
        except Exception as e:
           logging.error(f'JvB _populate_peer_list Ex={e}')
        # logging.info(f'JvB->peer_list={peer_list}')
        return peer_list

    # JvB added
    def _get_peer_interfaces(self, state, peer_addr):
        # logging.info(f'JvB _get_peer_interfaces peer_addr={peer_addr}')
        nexthop_list_path = build_path(f'/network-instance[name={uplink_network_instance}]/route-table/next-hop')
        nexthop_data = state.server_data_store.stream_data(nexthop_list_path, recursive=True)
        intf_list = []
        for nh in nexthop_data.network_instance.get().route_table.get().next_hop.items():
            # logging.info(f'JvB _get_peer_interfaces nh={nh}')
            if nh.ip_address == peer_addr and nh.subinterface is not None:
                intf_list.append(nh.subinterface)
        return intf_list

    def _populate_data(self, result, state):
        uplink_peer_list = self._populate_peer_list(state,uplink_peer_group)
        result.synchronizer.flush_fields(result)

        data = result.uplink_header.create()
        for uplink in uplink_peer_list:
          # For now, support at most 1 interface per peer
          interfaces = self._get_peer_interfaces(state, uplink)
          if interfaces!=[]:
            server_data = self._fetch_state(state, uplink, interfaces[0].split('.'))
            data_child = data.uplink_child.create(interfaces[0].split('.')[0])
            data_child.local_router = self.sys_name_data.system.get().name.get().host_name or '<Unknown>'
            data_child.link_status = self.int_oper_state_data.interface.get().subinterface.get().oper_state or '<Unknown>'
            data_child.ebgp_status = self.session_state_data.network_instance.get().protocols.get().bgp.get().neighbor.get().session_state or '<Unknown>'
            data_child.remote_router = self.lldp_neighbor_data.system.get().lldp.get().interface.get().neighbor.get().system_name or '<Unknown>'
            data_child.remote_interface = self.lldp_neighbor_data.system.get().lldp.get().interface.get().neighbor.get().port_id or '<Unknown>'
            data_child.synchronizer.flush_fields(data_child)

            # JvB Test gNMI connection; assumes DNS maps lldp name
            # SRL sends with mgmt IP source -> must send to mgmt IP
            #try:
            #  gnmi = GNMIHandlerLite.setup_connection( data_child.remote_router + ':57400' )
              # with Namespace('/var/run/netns/srbase-default', 'net'):
              # gnmi = GNMIHandlerLite.setup_connection( uplink + ':57400' )
            #  hostname = gnmi.get("/system/name/host-name")
            #  logging.info( f'Remote GNMI result: {hostname}' )
            #except Exception as e:
            #  logging.info(traceback.format_exc())

        result.synchronizer.flush_children(result.uplink_header)
        return result

    def _populate_data_rr(self, result, state):
        rr_peer_list = self._populate_peer_list(state,rr_peer_group)
        result.synchronizer.flush_fields(result)
        i=0
        data = result.rr_header.create()
        for rr in rr_peer_list:
          server_data = self._fetch_state_rr(state, rr)
          data_child = data.rr_child.create(rr)
          data_child.ibgp_status = self.rr_data.network_instance.get().protocols.get().bgp.get().neighbor.get().session_state or '<Unknown>'
          data_child.neighbor_description = self.rr_data.network_instance.get().protocols.get().bgp.get().neighbor.get().description or '<Unknown>'
          data_child.rx_active_tx = f'{self.rr_data.network_instance.get().protocols.get().bgp.get().neighbor.get().evpn.get().received_routes}/'\
                                    f'{self.rr_data.network_instance.get().protocols.get().bgp.get().neighbor.get().evpn.get().active_routes}/'\
                                    f'{self.rr_data.network_instance.get().protocols.get().bgp.get().neighbor.get().evpn.get().sent_routes}'
          data_child.uptime__hh_mm_ss_ = self._time_handler(self.time_data.system.get().information.get().current_datetime, self.rr_data.network_instance.get().protocols.get().bgp.get().neighbor.get().last_established)
          data_child.synchronizer.flush_fields(data_child)
          i=i+1
        result.synchronizer.flush_children(result.rr_header)
        return result

    def _populate_data_stats(self, result, state):
        uplink_peer_list = self._populate_peer_list(state,uplink_peer_group)
        result.synchronizer.flush_fields(result)

        data = result.stats_header.create()
        for uplink in uplink_peer_list:
          # For now, support at most 1 interface per peer
          interfaces = self._get_peer_interfaces(state, uplink)
          if interfaces!=[]:
            server_data = self._fetch_state_stats(state, interfaces[0].split('.')[0])
            data_child = data.stats_child.create(interfaces[0].split('.')[0])
            data_child.traffic_bps_in_out = f'{self.gen_data.interface.get().traffic_rate.get().in_bps}/{self.gen_data.interface.get().traffic_rate.get().in_bps}'
            data_child.packets_in_out = f'{self.gen_data.interface.get().statistics.get().in_unicast_packets}/{self.gen_data.interface.get().statistics.get().out_unicast_packets or "<Unknown>"}'
            data_child.errored_in_out = f'{self.gen_data.interface.get().statistics.get().in_error_packets }/{self.gen_data.interface.get().statistics.get().out_error_packets}'
            data_child.fcs_err = self.gen_data.interface.get().statistics.get().in_fcs_error_packets
            data_child.crc_err = self.gen_data.interface.get().ethernet.get().statistics.get().in_crc_error_frames
            try: data_child.transceiver_volt =  self.gen_data.interface.get().transceiver.get().voltage.get().latest_value or 'N/A'
            except: data_child.transceiver_volt = 'N/A'
            data_child.synchronizer.flush_fields(data_child)

        result.synchronizer.flush_children(result.stats_header)
        return result

    def _set_formatters_header(self, data):
        data.set_formatter('/header',Border(TagValueFormatter()))

    def _set_formatters_stats(self, data):
        data.set_formatter('/stats_header/stats_child', ColumnFormatter())

    def _set_formatters_rr(self, data):
        data.set_formatter('/rr_header/rr_child', ColumnFormatter())

    def _set_formatter_uplink(self, data):
        data.set_formatter('/uplink_header/uplink_child', ColumnFormatter(horizontal_alignment={'Link Status':Alignment.Center}))
