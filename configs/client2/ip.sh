# Copyright 2020 Nokia
# Licensed under the BSD 3-Clause License.
# SPDX-License-Identifier: BSD-3-Clause

# Add IPv4
ip address add 10.10.10.12/24 dev eth1
ip route add 0.0.0.0/0 via 10.10.10.1

# Add IPv6
ip -6 address add 2002::172:17:22:2/112 dev eth1
ip -6 route add 2002::172:17:0:0/96 via 2002::172:17:22:1
