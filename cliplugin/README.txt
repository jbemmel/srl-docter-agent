HOW TO ADD CLI PLUGIN

1) Add the uplink ports, spine/RR BGP peer groups in the python code.
2) Go to SRL bash. 
3) Copy scripts to 'reports' folder
    sudo scp username@{remote-IP}:/{path-to-scripts}/\{gnmi_lite.py,gnmi_pb2.py,fabric.py} /opt/srlinux/python/virtual-env/lib/python3.6/site-packages/srlinux/mgmt/cli/plugins/reports/

4) Add a new line for 'fabric' command in the 'entry_points.txt' file.
    sudo sh -c ' echo "fabric = srlinux.mgmt.cli.plugins.reports.fabric:Plugin" >> /opt/srlinux/python/virtual-env/lib/python3.6/site-packages/srlinux-0.1-py3.6.egg-info/entry_points.txt'

5) Restart sr cli by logging out/in or simple run 'sr_cli' from bash.
6) Try 'show fabric uplinks'
7) Try 'show fabric route-reflector'
8) Try 'show fabric statistics'
9) Try 'show fabric summary' 

Enjoy!

-AA