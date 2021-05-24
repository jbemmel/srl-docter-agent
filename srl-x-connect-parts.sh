#!/bin/bash

containerlab tools veth create --debug -a clab-son-lab-spine1:e1-2 -b clab-son-lab-leaf2:e1-1
containerlab tools veth create --debug -a clab-son-lab-spine2:e1-1 -b clab-son-lab-leaf1:e1-2
