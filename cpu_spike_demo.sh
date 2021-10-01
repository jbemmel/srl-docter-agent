#!/bin/bash

stress --cpu 8 --timeout 7s; sleep 5; stress --cpu 8 --timeout 7s; sleep 5; stress --cpu 8 --timeout 7s 
