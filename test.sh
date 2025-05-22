#!/bin/bash

VM_NAME="truenas"
NAMESPACE="virtualization"
OUTPUT_PATH="/tmp/disk.img"

# Stop the VM
echo "Stopping VM..."
virtctl stop $VM_NAME -n $NAMESPACE

# Wait for VM to be stopped
echo "Waiting for VM to stop..."
until [[ $(kubectl get vm $VM_NAME -n $NAMESPACE -o jsonpath='{.status.ready}') != "true" ]]; do
  sleep 5
done

# Start export
echo "Creating VM export..."
virtctl vmexport download $VM_NAME --vm=$VM_NAME --format=raw --ttl=1h --volume=truenas-scale-os-disk --output=$OUTPUT_PATH -n $NAMESPACE &
EXPORT_PID=$!

# Wait for the export to finish
wait $EXPORT_PID

# Restart the VM
echo "Starting VM..."
virtctl start $VM_NAME -n $NAMESPACE
