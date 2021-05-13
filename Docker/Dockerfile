FROM registry.srlinux.dev/pub/srlinux:latest

RUN sudo curl -sL https://github.com/karimra/gnmic/releases/download/v0.10.0/gnmic_0.10.0_Linux_x86_64.rpm -o /tmp/gnmic.rpm && sudo yum localinstall -y /tmp/gnmic.rpm

# --chown=srlinux:srlinux
# COPY ./appmgr/ /etc/opt/srlinux/appmgr/ # doesn't stick
COPY ./appmgr/ /home/appmgr

COPY 42_sr_copy_custom_appmgr.sh /opt/srlinux/bin/bootscript/

# RUN sudo mkdir -p /etc/opt/srlinux/appmgr/ && sudo cp /home/appmgr/* /etc/opt/srlinux/appmgr/

# Install balena, a modern Docker application to run containers within SRL
# Requires cSRL to be started using
# sudo docker run -it --privileged -v /tmp/var_lib_docker:/var/lib/balena-engine srl/auto-config:latest
RUN curl -sfL https://balena.io/engine/install.sh | sh

# Integrate CLI agent
COPY cliplugin/*.py /opt/srlinux/python/virtual-env/lib/python3.6/site-packages/srlinux/mgmt/cli/plugins/reports/
RUN sudo sh -c ' echo "fabric = srlinux.mgmt.cli.plugins.reports.fabric:Plugin" >> /opt/srlinux/python/virtual-env/lib/python3.6/site-packages/srlinux-0.1-py3.6.egg-info/entry_points.txt'

# Add Dublin trace-route
#RUN sudo curl -4sL https://copr.fedorainfracloud.org/coprs/teknoraver/networking/repo/epel-7/teknoraver-networking-epel-7.repo -o /etc/yum.repos.d/teknoraver-networking-epel-7.repo && \
#    sudo yum install -y epel-release && \
#    sudo yum install -y dublin-traceroute

# Add Paris traceroute
COPY --from=paris-traceroute /usr/local/bin/paris-* /usr/local/bin/
COPY --from=paris-traceroute /usr/local/lib/* /usr/local/lib/

# Using a build arg to set the release tag, set a default for running docker build manually
ARG SRL_AUTO_CONFIG_RELEASE="[custom build]"
ENV SRL_AUTO_CONFIG_RELEASE=$SRL_AUTO_CONFIG_RELEASE
