#!/bin/bash

# Define the input and output file paths
input_file="ip-ranges.json"
output_file="aws-ip-ranges.txt"

curl -O https://ip-ranges.amazonaws.com/ip-ranges.json

# Use jq to extract the required data and format the output
jq -r '.prefixes[] | select(.region=="us-east-1") | select(.service=="AMAZON") | "- cidr: \(.ip_prefix)"' < "$input_file" > "$output_file"

echo "IP ranges have been written to $output_file"

rm ./ip-ranges.json
